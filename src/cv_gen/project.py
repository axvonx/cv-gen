"""CircuitVerse project documents (``.cv`` exports and API ``circuit_data``).

The document is an undocumented simulator format, so everything here reads the fields
it needs and leaves every other field untouched.
"""

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .testbench import TestData, validate

Document = dict[str, Any]


class ProjectError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Port:
    label: str
    width: int


@dataclass(frozen=True, slots=True)
class ScopeInfo:
    id: str
    name: str
    inputs: tuple[Port, ...]
    outputs: tuple[Port, ...]
    dependencies: frozenset[str]  # ids of scopes used as subcircuits
    testbench: TestData | None


def load(path: str | Path) -> Document:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(document: Document, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")


def canonical_hash(document: Document) -> str:
    text = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _ports(scope: Document, kind: str) -> tuple[Port, ...]:
    ports = []
    for element in scope.get(kind, []):
        width = element.get("customData", {}).get("constructorParamaters", [None, 1])[1]
        ports.append(Port((element.get("label") or "").strip(), int(width)))
    return tuple(ports)


def scopes(document: Document) -> list[ScopeInfo]:
    result = []
    for scope in document.get("scopes", []):
        testbench = (scope.get("testbenchData") or {}).get("testData")
        result.append(
            ScopeInfo(
                id=str(scope["id"]),
                name=scope["name"],
                inputs=_ports(scope, "Input"),
                outputs=_ports(scope, "Output"),
                dependencies=frozenset(str(sub["id"]) for sub in scope.get("SubCircuit", [])),
                testbench=TestData.from_json(testbench) if testbench else None,
            )
        )
    return result


def find_scope(document: Document, name: str) -> ScopeInfo:
    matches = [scope for scope in scopes(document) if scope.name == name or scope.id == name]
    if not matches:
        raise ProjectError(f"no circuit named {name!r} in project")
    if len(matches) > 1:
        raise ProjectError(f"circuit name {name!r} is ambiguous ({len(matches)} matches)")
    return matches[0]


def dependency_names(document: Document) -> dict[str, set[str]]:
    """Map each scope name to the names of the scopes it uses directly as subcircuits."""
    infos = scopes(document)
    names = {info.id: info.name for info in infos}
    return {info.name: {names[d] for d in info.dependencies if d in names} for info in infos}


def check_testbench(scope: ScopeInfo, data: TestData) -> list[str]:
    return validate(
        data,
        {port.label: port.width for port in scope.inputs},
        {port.label: port.width for port in scope.outputs},
    )


def inject(document: Document, testbenches: dict[str, TestData]) -> Document:
    """Return a copy of ``document`` with each named scope's testbench replaced.

    Only ``testbenchData`` of the named scopes changes. Raises ``ProjectError`` listing
    every validation problem, before anything is modified.
    """
    problems = []
    for name, data in testbenches.items():
        scope = find_scope(document, name)
        problems.extend(f"{name}: {problem}" for problem in check_testbench(scope, data))
    if problems:
        raise ProjectError("invalid testbench:\n  " + "\n  ".join(problems))

    result = copy.deepcopy(document)
    ids = {find_scope(document, name).id: data for name, data in testbenches.items()}
    for scope in result["scopes"]:
        data = ids.get(str(scope["id"]))
        if data is not None:
            scope["testbenchData"] = data.to_testbench_data()
    return result


def non_testbench_view(document: Document) -> Document:
    """The document with every testbench removed, for "only tests changed" checks."""
    view = copy.deepcopy(document)
    for scope in view.get("scopes", []):
        scope.pop("testbenchData", None)
    return view


def testbench_view(document: Document) -> dict[str, Any]:
    return {
        str(scope["id"]): (scope.get("testbenchData") or {}).get("testData")
        for scope in document.get("scopes", [])
    }
