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
    wad = work / "empty.wad"
    wad.write_bytes(b"")
    return machine, machine.build_iss(), machine.build_testbench(), wad, work


def run_both(tools, name, keys=None):
    machine, iss, testbench, wad, work = tools
    image = machine.assemble(PROGRAMS / f"{name}.S", work / f"{name}.bin")
    results = {}
    for label, binary in (("iss", iss), ("rtl", testbench)):
        out = work / f"{name}-{label}"
        command = [str(binary), "--image", str(image), "--wad", str(wad), "--out", str(out)]
        command += ["--quiet", "--max-instret", "1000000"]
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
    assert results["rtl"] == results["iss"]
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


@pytest.mark.engine
def test_native_circuitverse_runs_a_loaded_program_like_verilator():
    """The exported machine in native CircuitVerse gates: loader, banks, lanes, MMIO exit."""
    from test_cpu_examples import require_engine

    require_engine()
    import cv_scenario

    from cv_gen.verilog import check, load_spec

    path, _, cycles = cv_scenario.manifest("banks")
    assert check(load_spec(path)).samples == cycles + 2
