"""Interpret engine reports: statuses, root causes, and text rendering."""

from dataclasses import dataclass, field
from typing import Any

FAILING = ("fail", "engine-error", "crash")


@dataclass(frozen=True, slots=True)
class ScopeResult:
    scope: str
    status: str
    passed: int = 0
    total: int = 0
    ms: int = 0
    failures: tuple[dict[str, Any], ...] = ()
    error: str | None = None

    @property
    def failing(self) -> bool:
        return self.status in FAILING


@dataclass(frozen=True, slots=True)
class Report:
    project: str | None
    load_ms: int | None
    scopes: tuple[ScopeResult, ...]
    # failing scope -> failing scopes it (transitively) depends on
    failing_dependencies: dict[str, set[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(result.failing for result in self.scopes)

    @property
    def root_causes(self) -> list[ScopeResult]:
        return [r for r in self.scopes if r.failing and not self.failing_dependencies.get(r.scope)]

    def downstream_of(self, root: str) -> list[str]:
        return sorted(name for name, deps in self.failing_dependencies.items() if root in deps)


def _transitive(dependencies: dict[str, set[str]]) -> dict[str, set[str]]:
    closure: dict[str, set[str]] = {}

    def visit(name: str, stack: frozenset[str]) -> set[str]:
        if name in closure:
            return closure[name]
        result: set[str] = set()
        for dep in dependencies.get(name, ()):
            if dep not in stack:
                result |= {dep} | visit(dep, stack | {dep})
        closure[name] = result
        return result

    for name in dependencies:
        visit(name, frozenset({name}))
    return closure


def build_report(raw: dict[str, Any], dependencies: dict[str, set[str]]) -> Report:
    """``dependencies`` maps scope name -> names used directly as subcircuits."""
    scopes = tuple(
        ScopeResult(
            scope=entry["scope"],
            status=entry["status"],
            passed=entry.get("passed", 0),
            total=entry.get("total", 0),
            ms=entry.get("ms", 0),
            failures=tuple(entry.get("failures", ())),
            error=entry.get("error"),
        )
        for entry in raw.get("scopes", [])
    )
    failing = {result.scope for result in scopes if result.failing}
    closure = _transitive(dependencies)
    failing_dependencies = {
        name: closure.get(name, set()) & failing for name in failing
    }
    return Report(raw.get("project"), raw.get("loadMs"), scopes, failing_dependencies)


def _describe_failure(failure: dict[str, Any]) -> str:
    inputs = " ".join(f"{k}={v}" for k, v in failure["inputs"].items())
    diffs = "; ".join(
        f"{d['output']}: expected {d['expected']} got {d['got']}" for d in failure["diffs"]
    )
    return f"case {failure['case']}: {inputs} -> {diffs}"


def render_text(
    report: Report, *, unchecked: dict[str, int] | None = None, verbose: bool = False
) -> str:
    """Failing circuits always show; passing and untested ones only with ``verbose``.

    Root-cause marking is a hint: a circuit that depends on a failing subcircuit may
    still have its own bug, so its failures are listed too.
    """
    unchecked = unchecked or {}
    lines = []
    width = max((len(r.scope) for r in report.scopes), default=10)
    roots = {r.scope for r in report.root_causes}
    passed = sum(r.status == "pass" for r in report.scopes)
    failed = sum(r.failing for r in report.scopes)
    untested = sum(r.status == "no-tests" for r in report.scopes)
    for result in report.scopes:
        if not result.failing and not verbose:
            continue
        mark = {"pass": "ok  ", "no-tests": "--  "}.get(result.status, "FAIL")
        cases = f"{result.passed}/{result.total}" if result.total else ""
        note = f"  ({unchecked[result.scope]} unchecked)" if result.scope in unchecked else ""
        lines.append(f"{mark} {result.scope:<{width}}  {result.status:<12} {cases:>11}  "
                     f"{result.ms}ms{note}".rstrip())
        if result.error:
            lines.append(f"       {result.error}")
        if not result.failing:
            continue
        if result.scope in roots:
            downstream = report.downstream_of(result.scope)
            if downstream:
                lines.append(f"       root cause? {len(downstream)} failing circuit(s) use it: "
                             f"{', '.join(downstream)}")
        else:
            causes = ", ".join(sorted(report.failing_dependencies[result.scope]))
            lines.append(f"       uses failing subcircuit(s): {causes}")
        lines.extend(f"       {_describe_failure(f)}" for f in result.failures)
        if result.status == "engine-error":
            lines.append("       simulator flagged an error (cyclic path or contention); "
                         "results for this circuit are not trustworthy")

    total_unchecked = sum(unchecked.values())
    summary = (
        f"{passed} passed, {failed} failed ({len(roots)} likely root cause"
        f"{'s' if len(roots) != 1 else ''}), {untested} without tests"
        + (f"; {total_unchecked} power-on case outputs calibrated, not checked"
           if total_unchecked else "")
    )
    return "\n".join([*lines, summary]) + "\n"
