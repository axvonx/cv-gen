import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .generator import (
    MASK64,
    MAX_GENERATED_CASES,
    GenerationOptions,
    GenerationSummary,
    emit_csv,
)
from .model import TestCase
from .tests_catalog import TESTS, find_test


def _unsigned(value: str) -> int:
    if not value or value.startswith("-"):
        raise argparse.ArgumentTypeError("expected an unsigned integer")
    try:
        parsed = int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an unsigned integer") from error
    if not 0 <= parsed <= MASK64:
        raise argparse.ArgumentTypeError("integer is outside the unsigned 64-bit range")
    return parsed


def _intensity(value: str) -> int:
    parsed = _unsigned(value)
    if parsed > 100:
        raise argparse.ArgumentTypeError("intensity must be between 0 and 100")
    return parsed


def _positive(value: str) -> int:
    parsed = _unsigned(value)
    if parsed == 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cv-gen tests csv",
        description="Generate deterministic CircuitVerse testbench CSV files.",
    )
    parser.add_argument("output", nargs="?", type=Path, help="output CSV path")
    parser.add_argument("-n", "--name", help="test name or alias")
    parser.add_argument("-i", "--intensity", type=_intensity, help="sampling intensity (0..100)")
    parser.add_argument("-m", "--max-cases", type=_positive, default=0, help="per-run case cap")
    parser.add_argument("-s", "--seed", type=_unsigned, default=0, help="unsigned 64-bit seed")
    parser.add_argument("--list", action="store_true", help="list available tests")
    return parser


def _print_summary(
    test: TestCase,
    options: GenerationOptions,
    summary: GenerationSummary,
    output_path: Path,
) -> None:
    suffix = "" if summary.generated_cases == 1 else "s"
    print(f"generated {summary.generated_cases} case{suffix} for '{test.name}' -> {output_path}")
    if summary.input_space_exact:
        print(f"input space: {summary.input_space} combinations ({summary.input_bits} bits)")
    else:
        print(f"input space: 2^{summary.input_bits} combinations")
    test_limit = test.max_cases or "derived"
    run_limit = options.max_cases or "none"
    print(
        f"case limits: test={test_limit}, run={run_limit}, global={MAX_GENERATED_CASES}, "
        f"effective={summary.effective_max_cases}"
    )
    print(
        f"sampling: intensity={options.intensity}%, seed={summary.seed}, "
        f"duplicate candidates resolved={summary.duplicate_candidates}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.list:
        generation_arguments = (
            args.name is not None,
            args.intensity is not None,
            bool(args.max_cases),
            bool(args.seed),
            args.output is not None,
        )
        if any(generation_arguments):
            parser.error("--list cannot be combined with generation options")
        for test in TESTS:
            print(test.name)
        return 0

    if args.name is None or args.intensity is None or args.output is None:
        parser.error("--name, --intensity, and output are required")

    test = find_test(args.name)
    if test is None:
        print(f"unknown test case: {args.name}", file=sys.stderr)
        print("available tests:", file=sys.stderr)
        for available in TESTS:
            print(f"  {available.name}", file=sys.stderr)
        return 1

    options = GenerationOptions(
        intensity=args.intensity,
        max_cases=args.max_cases,
        seed=args.seed,
    )
    summary = emit_csv(test, options, args.output)
    _print_summary(test, options, summary, args.output)
    return 0
