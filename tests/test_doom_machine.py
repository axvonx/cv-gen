"""DOOM machine RTL against the ISS oracle on directed programs.

Every program runs on both the Verilator testbench and the ISS; their console,
exit code, fault cause, retired instructions, cycles and frame logs must agree,
and each program's architecturally expected result is checked as well.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ROOT / "examples" / "doom" / "tests"
sys.path.insert(0, str(ROOT / "tools" / "doom"))


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    for name in ("verilator", "clang"):
        if not shutil.which(name):
            pytest.skip(f"{name} required")
    import machine

    work = tmp_path_factory.mktemp("doom")
    machine.build_testbench(structural=True)
    wad = work / "empty.wad"
    wad.write_bytes(b"")
    return machine, machine.build_iss(), machine.build_testbench(), wad, work


def run_both(tools, name, keys=None):
    machine, iss, testbench, wad, work = tools
    image = machine.assemble(PROGRAMS / f"{name}.S", work / f"{name}.bin")
    results = {}
    structural = testbench.parent.parent / "vstructural" / "tb_doom"
    for label, binary in (("iss", iss), ("rtl", testbench), ("structural", structural)):
        out = work / f"{name}-{label}"
        command = [str(binary), "--image", str(image), "--wad", str(wad), "--out", str(out)]
        command += ["--quiet", "--max-instret", "2000000"]
        if keys:
            command += ["--keys", str(PROGRAMS / keys)]
        subprocess.run(command, capture_output=True, check=False)
        summary = json.loads((out / "summary.json").read_text())
        summary.pop("host_seconds")
        # Retirement hashing and store high-water marks are ISS-only measurements.
        for key in ("final_hash", "heap_high_water", "stack_low_water"):
            summary.pop(key)
        results[label] = (
            summary,
            (out / "console.txt").read_text(),
            (out / "frames.tsv").read_text(),
        )
    # The fast testbench uses behavioral RV32M bodies; the structural one the
    # gate-level bodies CircuitVerse receives. Both must equal the ISS.
    assert results["rtl"] == results["iss"]
    assert results["structural"] == results["iss"]
    return results["rtl"]


@pytest.mark.parametrize(
    ("program", "cause"),
    [
        ("fault_align", "align"),
        ("fault_null", "access"),
        ("fault_store_null", "access"),
        ("fault_outside", "access"),
        ("fault_mmio_half", "mmio"),
        ("fault_mmio_reserved", "mmio"),
        ("fault_illegal", "illegal"),
        ("fault_fetch", "fetch"),
    ],
)
def test_fault_causes(tools, program, cause):
    summary, _, _ = run_both(tools, program)
    assert summary["fault"] == cause
    assert summary["exit_code"] == -1


def test_counters_time_mmio_reads_and_survive_the_16_bit_wrap(tools):
    summary, _, _ = run_both(tools, "counters")
    assert summary["fault"] == "none"
    assert summary["exit_code"] == 0x1803
    assert summary["instret"] > 80000


def test_bank_boundaries_and_byte_lanes(tools):
    summary, _, _ = run_both(tools, "banks")
    assert (summary["fault"], summary["exit_code"]) == ("none", 0)


def test_key_fifo_and_frame_handshake(tools):
    summary, console, frames = run_both(tools, "keys", keys="keys.keys")
    assert (summary["fault"], summary["exit_code"]) == ("none", 0)
    assert console == "3ad 1ad 320 |301 102 303 104 305 106 307 108 |3ff |"
    assert [line.split("\t")[0] for line in frames.splitlines()[1:]] == ["1", "2"]


def rv32m_reference(a, b, op):
    mask = 0xFFFFFFFF

    def signed(x):
        return x - (1 << 32) if x >> 31 else x

    def truncated(n, d):  # C-style division and remainder
        q = abs(n) // abs(d)
        q = -q if (n < 0) != (d < 0) else q
        return q, n - q * d

    sa, sb = signed(a), signed(b)
    if op == 0:
        return (a * b) & mask
    if op == 1:
        return ((sa * sb) >> 32) & mask
    if op == 2:
        return ((sa * b) >> 32) & mask
    if op == 3:
        return ((a * b) >> 32) & mask
    if b == 0:
        return mask if op in (4, 5) else a
    if op in (4, 6):
        if sa == -(1 << 31) and sb == -1:
            return a if op == 4 else 0
        q, r = truncated(sa, sb)
        return (q if op == 4 else r) & mask
    return a // b if op == 5 else a % b


def test_rv32m_edge_cases(tools):
    operands = [0, 1, 0xFFFFFFFF, 2, 0xFFFFFFFE, 0x7FFFFFFF, 0x80000000, 0x80000001]
    operands += [0xFFFF, 0x10000, 0x12345678, 0xDEADBEEF, 3, 0xFFFFFFFD, 0x0001FFFF, 0xFFFE0001]
    summary, console, _ = run_both(tools, "muldiv")
    assert (summary["fault"], summary["exit_code"]) == ("none", 0)
    expected = "".join(
        "".join(f"{rv32m_reference(a, b, op):08x} " for op in range(8)) + "\n"
        for a in operands
        for b in operands
    )
    assert console == expected


def xorshift32(state):
    while True:
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        yield state


def test_rv32m_random_operands(tools):
    numbers = xorshift32(0x2545F491)
    lines = []
    for _ in range(2048):
        a, b = next(numbers), next(numbers)
        b >>= next(numbers) & 31
        lines.append("".join(f"{rv32m_reference(a, b, op):08x} " for op in range(8)) + "\n")
    summary, console, _ = run_both(tools, "muldiv_random")
    assert (summary["fault"], summary["exit_code"]) == ("none", 0)
    assert console == "".join(lines)


@pytest.mark.engine
def test_native_circuitverse_runs_a_loaded_program_like_verilator():
    """The exported machine in native CircuitVerse gates: loader, banks, lanes, MMIO exit."""
    from test_cpu_examples import require_engine

    require_engine()
    import cv_scenario

    from cv_gen.verilog import check, load_spec

    path, _, cycles = cv_scenario.manifest("banks")
    assert check(load_spec(path)).samples == cycles + 2


@pytest.mark.engine
def test_native_circuitverse_rv32m_modules_match_verilator():
    """The structural RV32M bodies, as exported, on edge pairs and random operands."""
    from test_cpu_examples import require_engine

    require_engine()
    import cv_scenario

    from cv_gen.verilog import check, load_spec

    path, samples = cv_scenario.muldiv_manifest()
    assert check(load_spec(path)).samples == samples
