"""Ordered traces for sequential circuits.

CircuitVerse's own ``seq`` testbench needs an ``RST`` input and a ``Clock`` element.
Circuits clocked by an ordinary input instead get a ``comb`` testbench whose cases run
in order. The simulator keeps state between cases, so an explicit 0 -> 1 on the clock
input is a clock edge.

Every case checks every output; CircuitVerse has no "don't care". Power-on state is an
engine artifact (it differs between otherwise similar circuits), so an oracle returns
``None`` for any output it cannot know yet. Those positions are recorded in
``Trace.unknown`` and later filled from what the engine actually shows ("calibration"),
which keeps the test runnable in the browser while the report counts them as unchecked.
"""

import itertools
import random
from collections.abc import Iterable
from dataclasses import dataclass

from .model import Signal, Values
from .testbench import Group, Series, TestData, format_value


class TraceOracle:
    """Model of a clocked circuit. Subclass, then register it with ``@trace(name)``."""

    clock: str = "IN CLK"

    def reset(self) -> None:
        """Return to the power-on state. Called once before each trace."""

    def stimulus(self, rng: random.Random, cycles: int) -> Iterable[Values]:
        """Yield one input assignment per clock cycle, without the clock.

        Inputs left out default to 0. At most ``cycles`` items are used.
        """
        raise NotImplementedError

    def edge(self, inputs: Values) -> None:
        """Apply a rising clock edge with ``inputs`` held."""

    def outputs(self, inputs: Values) -> dict[str, int | None]:
        """Outputs visible now, given the current inputs (clock included).

        Use ``None`` for an output that depends on never-written state.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class Trace:
    data: TestData
    unknown: tuple[tuple[str, int], ...]  # (output label, case index) to calibrate


def generate_trace(
    oracle: TraceOracle,
    title: str,
    inputs: tuple[Signal, ...],
    outputs: tuple[Signal, ...],
    cycles: int,
    seed: int = 0,
) -> Trace:
    """Two cases per cycle: clock low, then clock high (the rising edge)."""
    input_names = [signal.name for signal in inputs]
    if oracle.clock not in input_names:
        raise ValueError(f"circuit has no clock input {oracle.clock!r}")
    output_names = {signal.name for signal in outputs}

    in_values: dict[str, list[str]] = {name: [] for name in input_names}
    out_values: dict[str, list[str]] = {signal.name: [] for signal in outputs}
    unknown: list[tuple[str, int]] = []
    case_index = 0
    oracle.reset()
    stimulus = oracle.stimulus(random.Random(seed), cycles)
    for cycle, assignment in enumerate(itertools.islice(stimulus, cycles)):
        extra = set(assignment) - set(input_names)
        if extra:
            raise ValueError(f"cycle {cycle}: stimulus sets unknown inputs {sorted(extra)}")
        for clock in (0, 1):
            case = {name: assignment.get(name, 0) for name in input_names}
            case[oracle.clock] = clock
            if clock:
                oracle.edge(case)
            expected = oracle.outputs(case)
            if set(expected) != output_names:
                raise ValueError(
                    f"cycle {cycle}: oracle returned outputs {sorted(expected)}, "
                    f"circuit has {sorted(output_names)}"
                )
            for signal in inputs:
                in_values[signal.name].append(format_value(case[signal.name], signal.width))
            for signal in outputs:
                value = expected[signal.name]
                if value is None:
                    unknown.append((signal.name, case_index))
                    value = 0
                out_values[signal.name].append(format_value(value, signal.width))
            case_index += 1

    if not in_values[input_names[0]]:
        raise ValueError(f"oracle for {title!r} produced no cycles")
    group = Group(
        "Trace",
        tuple(Series(s.name, s.width, tuple(in_values[s.name])) for s in inputs),
        tuple(Series(s.name, s.width, tuple(out_values[s.name])) for s in outputs),
    )
    return Trace(TestData("comb", title, (group,)), tuple(unknown))
