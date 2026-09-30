"""generate -> inject -> calibrate: the shared front half of `cv-gen gen/check/push`."""

import dataclasses
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .oracles import Registry
from .project import Document, ProjectError, inject, save
from .suite import Generated, generate_suites
from .testbench import Group, Series, TestData

# (scope names, document) -> raw engine report including "results" for those scopes
Calibrator = Callable[[list[str], Document], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Build:
    document: Document
    generated: tuple[Generated, ...]

    @property
    def unchecked(self) -> dict[str, int]:
        return {g.scope: len(g.unknown) for g in self.generated if g.unknown}


def engine_calibrator(rev: str) -> Calibrator:
    from . import engine

    def calibrate(scopes: list[str], document: Document) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="cv-gen-cal-") as scratch:
            path = Path(scratch) / "calibrate.cv"
            save(document, path)
            return engine.run(rev, path, only=scopes, results_for=scopes)

    return calibrate


def _fill(generated: Generated, results: list[dict[str, list[str]]]) -> Generated:
    group = generated.data.groups[0]
    observed = results[0]
    values = {series.label: list(series.values) for series in group.outputs}
    for label, case in generated.unknown:
        value = observed[label][case]
        if value is None or set(value) - {"0", "1"}:
            raise ProjectError(
                f"{generated.scope}: output {label!r} is undriven ({value!r}) at case {case}; "
                "cannot calibrate it"
            )
        values[label][case] = value
    outputs = tuple(Series(s.label, s.bit_width, tuple(values[s.label])) for s in group.outputs)
    data = TestData(
        generated.data.type,
        generated.data.title,
        (Group(group.label, group.inputs, outputs), *generated.data.groups[1:]),
    )
    return dataclasses.replace(generated, data=data)


def build(
    config: Config,
    document: Document,
    registry: Registry,
    calibrate: Calibrator | None,
) -> Build:
    generated = generate_suites(config, document, registry)
    injected = inject(document, {g.scope: g.data for g in generated})
    pending = [g.scope for g in generated if g.unknown]
    if not pending:
        return Build(injected, tuple(generated))
    if calibrate is None:
        raise ProjectError(f"traces need engine calibration: {', '.join(pending)}")

    raw = calibrate(pending, injected)
    by_scope = {entry["scope"]: entry for entry in raw.get("scopes", [])}
    filled = []
    for g in generated:
        if g.unknown:
            entry = by_scope.get(g.scope, {})
            if entry.get("status") == "engine-error" or "results" not in entry:
                raise ProjectError(
                    f"{g.scope}: calibration run returned no results "
                    f"(status {entry.get('status', 'missing')}: {entry.get('error', '')})"
                )
            g = _fill(g, entry["results"])
        filled.append(g)
    return Build(inject(document, {g.scope: g.data for g in filled}), tuple(filled))
