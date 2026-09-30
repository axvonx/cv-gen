"""Build CircuitVerse projects from synthesizable Verilog."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

V1_REV = "efadf7a9fda9ff3bf93002e0020bd4a9ba53e920"
Format = Literal["legacy", "canonical-v1"]


class BuildError(ValueError):
    pass


@dataclass(frozen=True)
class Step:
    inputs: dict[str, int]
    sample: bool = True


@dataclass(frozen=True)
class Scenario:
    name: str
    setup: tuple[Step, ...]
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class BuildSpec:
    sources: tuple[Path, ...]
    top: str
    output: Path
    format: Format
    includes: tuple[Path, ...] = ()
    defines: dict[str, str] = field(default_factory=dict)
    parameters: dict[str, int] = field(default_factory=dict)
    clocks: tuple[str, ...] = ()
    scenarios: tuple[Scenario, ...] = ()
    seed: int = 0
    cases: int = 0


@dataclass(frozen=True)
class BuildResult:
    output: Path
    top: str
    format: Format
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class CheckResult(BuildResult):
    samples: int


def load_spec(path: str | Path = "cvgen-verilog.toml") -> BuildSpec:
    path = Path(path).resolve()
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise BuildError(f"{path}: {error}") from error
    extra = set(raw) - {"verilog", "check", "scenario"}
    if extra:
        raise BuildError(f"unknown manifest sections: {sorted(extra)}")
    table = raw.get("verilog", {})
    if not isinstance(table, dict):
        raise BuildError("[verilog] must be a table")
    extra = set(table) - {
        "sources",
        "top",
        "output",
        "format",
        "includes",
        "defines",
        "parameters",
        "clocks",
    }
    if extra:
        raise BuildError(f"unknown [verilog] keys: {sorted(extra)}")
    root = path.parent
    source_names = table.get("sources")
    if not isinstance(source_names, list) or not all(
        isinstance(name, str) for name in source_names
    ):
        raise BuildError("[verilog].sources must be a list of .v/.sv paths")
    if not all(key in table for key in ("top", "output", "format")):
        raise BuildError("[verilog] requires sources, top, output, and format")
    if not isinstance(table["output"], str):
        raise BuildError("[verilog].output must be a .cv path")
    sources = tuple((root / name).resolve() for name in source_names)
    top = table["top"]
    output = (root / table["output"]).resolve()
    fmt = table["format"]
    if not sources or any(p.suffix not in {".v", ".sv"} or not p.is_file() for p in sources):
        raise BuildError("sources must be an ordered list of existing .v/.sv files")
    if (
        not isinstance(top, str)
        or not top
        or not isinstance(fmt, str)
        or fmt not in {"legacy", "canonical-v1"}
    ):
        raise BuildError("top and format (legacy or canonical-v1) are required")
    include_names = table.get("includes", [])
    if not isinstance(include_names, list) or not all(
        isinstance(name, str) for name in include_names
    ):
        raise BuildError("[verilog].includes must be a list of directories")
    includes = tuple((root / name).resolve() for name in include_names)
    if any(not p.is_dir() for p in includes):
        raise BuildError("every include directory must exist")
    defines = table.get("defines", {})
    parameters = table.get("parameters", {})
    clock_names = table.get("clocks", [])
    if not isinstance(clock_names, list) or not all(
        isinstance(name, str) for name in clock_names
    ):
        raise BuildError("[verilog].clocks must be a list of input port names")
    clocks = tuple(clock_names)
    if not isinstance(defines, dict) or not all(
        isinstance(k, str) and (isinstance(v, str) or type(v) is int)
        for k, v in defines.items()
    ):
        raise BuildError("defines must map names to strings or integers")
    if not isinstance(parameters, dict) or not all(
        isinstance(k, str) and type(v) is int for k, v in parameters.items()
    ):
        raise BuildError("parameters must map names to integers")
    scenarios = []
    scenario_items = raw.get("scenario", [])
    if not isinstance(scenario_items, list):
        raise BuildError("[[scenario]] entries must be tables")
    for index, item in enumerate(scenario_items):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise BuildError(f"scenario {index} needs a name")

        def steps(key: str, entry: dict = item, number: int = index) -> tuple[Step, ...]:
            entries = entry.get(key, [])
            if not isinstance(entries, list):
                raise BuildError(f"scenario {number}.{key} must be a list of steps")
            parsed = []
            for step in entries:
                if not isinstance(step, dict) or not isinstance(step.get("inputs"), dict):
                    raise BuildError(f"scenario {number}.{key} step needs an inputs table")
                if set(step) - {"inputs", "sample"}:
                    raise BuildError(f"scenario {number}.{key} step has unknown keys")
                sample = step.get("sample", key == "steps")
                if type(sample) is not bool:
                    raise BuildError(f"scenario {number}.{key} sample must be a boolean")
                parsed.append(Step(step["inputs"], sample))
            return tuple(parsed)

        if set(item) - {"name", "setup", "steps"}:
            raise BuildError(f"scenario {index} has unknown keys")
        scenarios.append(Scenario(item["name"], steps("setup"), steps("steps")))
    check = raw.get("check", {})
    if not isinstance(check, dict) or set(check) - {"seed", "cases"}:
        raise BuildError("[check] supports only seed and cases")
    spec = BuildSpec(
        sources,
        top,
        output,
        fmt,
        includes,
        {k: str(v) for k, v in defines.items()},
        parameters,
        clocks,
        tuple(scenarios),
        check.get("seed", 0),
        check.get("cases", 0),
    )
    _validate_spec(spec)
    return spec


def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise BuildError(f"{name} is required; install it and place it on PATH")
    return found


def _validate_spec(spec: BuildSpec, *, for_check: bool = False) -> None:
    if not spec.sources or any(
        p.suffix not in {".v", ".sv"} or not p.is_file() for p in spec.sources
    ):
        raise BuildError("all Verilog sources must be existing .v/.sv files")
    if spec.output.suffix != ".cv":
        raise BuildError("output must have a .cv extension")
    if any(not p.is_dir() for p in spec.includes):
        raise BuildError("every include directory must exist")
    if spec.format not in {"legacy", "canonical-v1"}:
        raise BuildError(f"unsupported format: {spec.format}")
    if not spec.top or not spec.output:
        raise BuildError("top and output are required")
    identifier = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
    if not identifier.fullmatch(spec.top):
        raise BuildError("top must be a plain Verilog module identifier")
    if any(
        not identifier.fullmatch(name) for name in (*spec.defines, *spec.parameters, *spec.clocks)
    ):
        raise BuildError("define, parameter, and clock names must be plain identifiers")
    if len(set(spec.clocks)) != len(spec.clocks):
        raise BuildError("clock ports must be unique")
    if any(type(value) is not str for value in spec.defines.values()):
        raise BuildError("define values must be strings")
    if any(type(value) is not int for value in spec.parameters.values()):
        raise BuildError("parameters must map names to integers")
    if any(not re.fullmatch(r"[A-Za-z0-9_+./-]+", value) for value in spec.defines.values()):
        raise BuildError("define values must be simple Yosys tokens")
    if any(re.search(r"[\s;\r\n]", str(path)) for path in spec.includes):
        raise BuildError("Yosys include directory paths cannot contain whitespace or semicolons")
    if type(spec.seed) is not int or not 0 <= spec.seed < (1 << 64):
        raise BuildError("check seed must be an unsigned 64-bit integer")
    if type(spec.cases) is not int or not 0 <= spec.cases <= 1_000_000:
        raise BuildError("check cases must be an integer in 0..1000000")
    for scenario in spec.scenarios:
        if not scenario.name:
            raise BuildError("scenario names cannot be empty")
        for step in (*scenario.setup, *scenario.steps):
            if not isinstance(step.inputs, dict) or any(
                not isinstance(name, str) or type(value) is not int
                for name, value in step.inputs.items()
            ):
                raise BuildError(f"{scenario.name}: inputs must map port names to integers")
            if type(step.sample) is not bool:
                raise BuildError(f"{scenario.name}: sample must be a boolean")
    if for_check and spec.clocks and not spec.scenarios:
        raise BuildError("stateful designs require a scenario with explicit setup steps")
    if for_check and any(not s.setup for s in spec.scenarios):
        raise BuildError("every scenario requires setup steps")


def _generate(spec: BuildSpec, scratch: Path) -> tuple[dict, dict]:
    _tool("yosys")
    _tool("node")
    request = {
        "sources": [str(p) for p in spec.sources],
        "top": spec.top,
        "includes": [str(p) for p in spec.includes],
        "defines": spec.defines,
        "parameters": spec.parameters,
        "clocks": spec.clocks,
        "format": spec.format,
        "output": str(scratch / "project.cv"),
        "netlist": str(scratch / "netlist.json"),
    }
    request_path = scratch / "request.json"
    request_path.write_text(json.dumps(request))
    script = Path(__file__).parent / "node" / "build.cjs"
    from .engine import converter_directory

    env = {**os.environ}
    converter_modules = converter_directory() / "node_modules"
    if converter_modules.is_dir():
        env["NODE_PATH"] = str(converter_modules) + os.pathsep + env.get("NODE_PATH", "")
    result = subprocess.run(
        ["node", str(script), str(request_path)], capture_output=True, text=True, env=env
    )
    if result.returncode:
        raise BuildError((result.stderr or result.stdout).strip())
    document = json.loads((scratch / "project.cv").read_text())
    netlist = json.loads((scratch / "netlist.json").read_text())
    return document, netlist


def _validate_document(spec: BuildSpec, document: dict) -> tuple[str, ...]:
    from cv_gen import project

    if spec.format == "canonical-v1":
        if document.get("formatVersion") != "v1":
            raise BuildError("canonical serializer returned an invalid format version")
        circuits = document.get("circuits", {})
        names = tuple(c["projectMetadata"]["name"] for c in circuits.values())
        if names.count(spec.top) != 1 or names.count("Demo") != 1:
            raise BuildError("canonical project lost the top or demo scope")
        if any(c.get("verilogMetadata", {}).get("isVerilogCircuit") for c in circuits.values()):
            raise BuildError("canonical generated scope would open in Verilog editor mode")

        def find(name: str) -> dict:
            return next(c for c in circuits.values() if c["projectMetadata"]["name"] == name)

        def ports(scope: dict, kind: str) -> dict[str, int]:
            return {
                c["label"]: c["properties"]["constructorParamaters"][1]
                for c in scope["netlist"]["components"]
                if c["type"] == kind
            }

        top, demo = find(spec.top), find("Demo")
        demo_inputs = ports(demo, "Input")
        demo_inputs.update(dict.fromkeys(spec.clocks, 1))
        if ports(top, "Input") != demo_inputs or ports(top, "Output") != ports(demo, "Output"):
            raise BuildError("canonical demo ports do not match top ports")
        for scope in circuits.values():
            ids = {c["id"] for c in scope["netlist"]["components"]}
            for net in scope["netlist"]["nets"]:
                for endpoint in net["connections"]:
                    if endpoint.split(".", 1)[0] not in ids:
                        raise BuildError(f"canonical net {net['id']} has a missing endpoint")
        return names
    infos = project.scopes(document)
    names = tuple(s.name for s in infos)
    if names.count(spec.top) != 1 or "Demo" not in names:
        raise BuildError("generated project lost the top or demo scope")
    for scope in document.get("scopes", []):
        if scope.get("verilogMetadata", {}).get("isVerilogCircuit"):
            raise BuildError(f"{scope['name']}: generated scope would hide its circuit canvas")
        nodes = scope.get("allNodes", [])
        for i, node in enumerate(nodes):
            for j in node.get("connections", []):
                if not isinstance(j, int) or not 0 <= j < len(nodes):
                    raise BuildError(f"{scope['name']}: node {i} has an invalid connection {j}")
                if node.get("bitWidth") != nodes[j].get("bitWidth"):
                    raise BuildError(
                        f"{scope['name']}: connected nodes {i} and {j} have widths "
                        f"{node.get('bitWidth')} and {nodes[j].get('bitWidth')}"
                    )
    top = project.find_scope(document, spec.top)
    demo = project.find_scope(document, "Demo")
    top_inputs = {p.label: p.width for p in top.inputs}
    demo_inputs = {p.label: p.width for p in demo.inputs}
    demo_inputs.update(dict.fromkeys(spec.clocks, 1))
    if top_inputs != demo_inputs:
        raise BuildError("demo controls do not match top inputs")
    if [(p.label, p.width) for p in top.outputs] != [(p.label, p.width) for p in demo.outputs]:
        raise BuildError("demo readouts do not match top outputs")
    return names


def _publish(spec: BuildSpec, data: dict) -> None:
    spec.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=spec.output.parent, suffix=".cv", delete=False
    ) as file:
        temporary = Path(file.name)
        json.dump(data, file, separators=(",", ":"))
        file.write("\n")
    os.replace(temporary, spec.output)


def build(spec: BuildSpec) -> BuildResult:
    _validate_spec(spec)
    with tempfile.TemporaryDirectory(prefix="cv-gen-") as directory:
        scratch = Path(directory)
        document, _ = _generate(spec, scratch)
        scopes = _validate_document(spec, document)
        if spec.format == "legacy":
            from .compare import smoke_legacy

            smoke_legacy(spec, document, scratch)
    _publish(spec, document)
    return BuildResult(spec.output, spec.top, spec.format, scopes)


def check(spec: BuildSpec) -> CheckResult:
    _validate_spec(spec, for_check=True)
    with tempfile.TemporaryDirectory(prefix="cv-gen-check-") as directory:
        document, _ = _generate(spec, Path(directory))
        _validate_document(spec, document)
        # Behavioral comparison is performed before publishing; a failure leaves the output alone.
        from .compare import compare

        samples = compare(spec, document, Path(directory))
    scopes = _validate_document(spec, document)
    _publish(spec, document)
    return CheckResult(spec.output, spec.top, spec.format, scopes, samples)
