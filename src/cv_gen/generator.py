from dataclasses import dataclass
from pathlib import Path
from struct import calcsize

from .model import Signal, TestCase, Values
from .testbench import Group, Series, TestData, format_value

MASK64 = (1 << 64) - 1
SIZE_BITS = calcsize("P") * 8
SIZE_MAX = (1 << SIZE_BITS) - 1
MAX_GENERATED_CASES = 65_536


@dataclass(frozen=True, slots=True)
class GenerationOptions:
    intensity: int
    max_cases: int = 0
    seed: int = 0


@dataclass(frozen=True, slots=True)
class GenerationSummary:
    generated_cases: int
    effective_max_cases: int
    input_bits: int
    input_space: int
    duplicate_candidates: int
    input_space_exact: bool
    seed: int


def _u64(value: int) -> int:
    return value & MASK64


def _mix64(value: int) -> int:
    value = _u64(value + 0x9E3779B97F4A7C15)
    value = _u64((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9)
    value = _u64((value ^ (value >> 27)) * 0x94D049BB133111EB)
    return _u64(value ^ (value >> 31))


def _input_layout_seed(inputs: tuple[Signal, ...]) -> int:
    value = 14_695_981_039_346_656_037
    for signal in inputs:
        value = _u64((value ^ signal.width) * 1_099_511_628_211)
        for byte in signal.name.encode():
            value = _u64((value ^ byte) * 1_099_511_628_211)
        value = _u64((value ^ 0xFF) * 1_099_511_628_211)
    return _mix64(value)


def _input_space_size(total_bits: int) -> int:
    return SIZE_MAX if total_bits >= SIZE_BITS else 1 << total_bits


def _case_limit(test: TestCase) -> int:
    input_space = _input_space_size(test.input_bits)
    available = test.max_cases or input_space
    return max(1, min(available, input_space, MAX_GENERATED_CASES))


def _case_budget(available: int, intensity: int) -> int:
    if intensity == 0:
        return 1
    if intensity >= 100:
        return available
    scaled = (available // 100) * intensity + ((available % 100) * intensity + 99) // 100
    return max(1, scaled)


def _small_space_value(
    inputs: tuple[Signal, ...], case_index: int, total_bits: int, seed: int
) -> int:
    mask = (1 << total_bits) - 1
    stride = _mix64(_input_layout_seed(inputs) ^ seed ^ 0x535452494445) & mask
    stride |= 1
    return case_index * stride & mask


def _large_space_value(case_index: int, total_bits: int, seed: int) -> int:
    if case_index == 0:
        return 0
    if case_index == 1:
        return (1 << total_bits) - 1
    if case_index in (2, 3):
        return sum(1 << bit for bit in range(total_bits) if (bit + case_index) & 1)
    if 4 <= case_index < 68:
        slot = case_index - 4
        slots = min(total_bits, 64)
        if slot < slots:
            bit = 0 if slots == 1 else slot * (total_bits - 1) // (slots - 1)
            return 1 << bit

    random_seed = _mix64(case_index ^ seed ^ 0x4356525345545354)
    value = 0
    for bit in range(total_bits):
        if bit & 63 == 0:
            word = _mix64(random_seed ^ (bit >> 6))
        if word >> (bit & 63) & 1:
            value |= 1 << bit
    return value


def _unique_value(candidate: int, seen: set[int], total_bits: int) -> tuple[int, int]:
    probes = 0
    mask = (1 << total_bits) - 1
    while candidate in seen:
        if probes >= len(seen):
            raise RuntimeError("unable to find a unique input vector")
        probes += 1
        candidate = candidate + 1 & mask
    seen.add(candidate)
    return candidate, probes


def _split_inputs(value: int, inputs: tuple[Signal, ...]) -> Values:
    result: Values = {}
    offset = 0
    for signal in inputs:
        result[signal.name] = value >> offset & ((1 << signal.width) - 1)
        offset += signal.width
    return result


def _validate(test: TestCase, options: GenerationOptions) -> None:
    if not 0 <= options.intensity <= 100:
        raise ValueError("intensity must be between 0 and 100")
    if options.max_cases < 0:
        raise ValueError("max_cases cannot be negative")
    if not 0 <= options.seed <= MASK64:
        raise ValueError("seed must fit in an unsigned 64-bit integer")
    if not test.inputs or not test.outputs:
        raise ValueError("tests require at least one input and output")

    for signals in (test.inputs, test.outputs):
        names = [signal.name for signal in signals]
        if len(names) != len(set(names)):
            raise ValueError("signal names must be unique")
        for signal in signals:
            if signal.width <= 0 or any(character in signal.name for character in ",\r\n:"):
                raise ValueError(f"invalid signal: {signal.name!r}")


def generate_testbench(
    test: TestCase, options: GenerationOptions
) -> tuple[TestData, GenerationSummary]:
    _validate(test, options)
    configured_limit = _case_limit(test)
    effective_limit = min(configured_limit, options.max_cases or configured_limit)
    budget = min(_case_budget(configured_limit, options.intensity), effective_limit)

    input_series: dict[str, list[str]] = {signal.name: [] for signal in test.inputs}
    output_series: dict[str, list[str]] = {signal.name: [] for signal in test.outputs}
    seen: set[int] = set()
    duplicate_candidates = 0

    for case_index in range(budget):
        if test.input_bits <= 16:
            candidate = _small_space_value(
                test.inputs, case_index, test.input_bits, options.seed
            )
        else:
            candidate = _large_space_value(case_index, test.input_bits, options.seed)
        candidate, probes = _unique_value(candidate, seen, test.input_bits)
        duplicate_candidates += probes

        inputs = _split_inputs(candidate, test.inputs)
        outputs = test.generate(inputs)
        for signal in test.inputs:
            input_series[signal.name].append(format_value(inputs[signal.name], signal.width))
        for signal in test.outputs:
            output_series[signal.name].append(format_value(outputs[signal.name], signal.width))

    group = Group(
        label="Group 1",
        inputs=tuple(
            Series(s.name, s.width, tuple(input_series[s.name])) for s in test.inputs
        ),
        outputs=tuple(
            Series(s.name, s.width, tuple(output_series[s.name])) for s in test.outputs
        ),
    )
    summary = GenerationSummary(
        generated_cases=budget,
        effective_max_cases=effective_limit,
        input_bits=test.input_bits,
        input_space=_input_space_size(test.input_bits),
        duplicate_candidates=duplicate_candidates,
        input_space_exact=test.input_bits < SIZE_BITS,
        seed=options.seed,
    )
    return TestData("comb", test.name, (group,)), summary


def generate_csv(test: TestCase, options: GenerationOptions) -> tuple[str, GenerationSummary]:
    data, summary = generate_testbench(test, options)
    return data.to_csv(), summary


def emit_csv(
    test: TestCase, options: GenerationOptions, output_path: str | Path
) -> GenerationSummary:
    csv, summary = generate_csv(test, options)
    Path(output_path).write_text(csv, encoding="utf-8", newline="")
    return summary
