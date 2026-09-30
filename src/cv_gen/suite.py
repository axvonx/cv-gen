"""Turn ``cvgen-tests.toml`` suites into testbenches for a specific project document."""

from dataclasses import dataclass

from .config import Config
from .generator import GenerationOptions, generate_testbench
from .model import Signal, TestCase, Values
from .oracles import CombOracle, Registry
from .project import Document, ProjectError, ScopeInfo, find_scope
from .testbench import TestData
from .trace import generate_trace


@dataclass(frozen=True, slots=True)
class Generated:
    scope: str
    kind: str
    oracle: str
    data: TestData
    unknown: tuple[tuple[str, int], ...] = ()  # (output, case) awaiting calibration


def _signals(scope: ScopeInfo) -> tuple[tuple[Signal, ...], tuple[Signal, ...]]:
    unlabelled = [p for p in (*scope.inputs, *scope.outputs) if not p.label]
    if unlabelled:
        raise ProjectError(
            f"{scope.name}: {len(unlabelled)} port(s) have no label; label every input "
            "and output in CircuitVerse before generating tests"
        )
    return (
        tuple(Signal(p.label, p.width) for p in scope.inputs),
        tuple(Signal(p.label, p.width) for p in scope.outputs),
    )


def _adapt(function: CombOracle, scope: str, outputs: tuple[Signal, ...]):
    names = {signal.name for signal in outputs}

    def generate(values: Values) -> Values:
        result = function(dict(values))
        if isinstance(result, int):
            if len(outputs) != 1:
                raise ValueError(f"{scope}: oracle returned one int but the circuit has "
                                 f"{len(outputs)} outputs")
            return {outputs[0].name: result}
        if set(result) != names:
            raise ValueError(f"{scope}: oracle returned outputs {sorted(result)}, "
                             f"circuit has {sorted(names)}")
        return result

    return generate


def generate_suites(config: Config, document: Document, registry: Registry) -> list[Generated]:
    generated = []
    for suite in config.suites:
        scope = find_scope(document, suite.scope)
        inputs, outputs = _signals(scope)
        seed = config.seed if suite.seed is None else suite.seed
        max_cases = suite.max_cases or config.max_cases
        kind = registry.kind_of(suite.oracle)
        if kind == "comb":
            test = TestCase(
                name=scope.name,
                alias=None,
                inputs=inputs,
                outputs=outputs,
                generate=_adapt(registry.comb[suite.oracle], scope.name, outputs),
            )
            intensity = config.intensity if suite.intensity is None else suite.intensity
            data, _ = generate_testbench(test, GenerationOptions(intensity, max_cases, seed))
            unknown: tuple[tuple[str, int], ...] = ()
        elif kind == "trace":
            oracle = registry.trace[suite.oracle]()
            result = generate_trace(
                oracle, scope.name, inputs, outputs, max(1, max_cases // 2), seed
            )
            data, unknown = result.data, result.unknown
        else:
            raise ProjectError(f"{suite.scope}: no oracle named {suite.oracle!r}")
        generated.append(Generated(scope.name, kind, suite.oracle, data, unknown))
    return generated
