"""Full-RAM boundaries, RAM boot and the C-generated framebuffer."""

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from test_cpu_examples import require_engine, require_tools

from cv_gen.verilog import BuildSpec, Scenario, Step, build, check, load_spec
from cv_gen.verilog.compare import _stimulus, _verilator

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/riscv_graphics"


@pytest.fixture(scope="module")
def compiled_graphics():
    """Ignored binary artifacts are rebuilt when testing a fresh checkout."""
    required = [EXAMPLE / "build/ram-load.json", EXAMPLE / "build/expected-frame.bin"]
    if not all(p.is_file() for p in required):
        for name in ("clang", "ld.lld", "llvm-objcopy", "llvm-objdump"):
            if not (shutil.which(name) or shutil.which(name, path="/opt/homebrew/opt/llvm/bin")):
                pytest.skip(f"LLVM toolchain required: {name}")
        subprocess.run(["uv", "run", "python", str(EXAMPLE / "compile.py")], cwd=ROOT, check=True)


def load_reference():
    spec = importlib.util.spec_from_file_location("graphics_reference", EXAMPLE / "reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("boot", ["rom", "ram"])
def test_complete_frame_and_high_memory_in_verilator(tmp_path, boot, compiled_graphics):
    require_tools()
    reference = load_reference()
    spec = load_spec(EXAMPLE / "cvgen-verilog.toml")
    loads = json.loads((EXAMPLE / "build/ram-load.json").read_text()) if boot == "ram" else []
    result = reference.reference(spec, tmp_path, loads, 50000)
    assert result["rows"][-1]["result"] == 15384
    assert result["rows"][-1]["sp"] == 0xE000
    assert result["far_word"] == 0xDEADBEEF and result["last_word"] == 0x12345678
    assert sum(result["pixels"]) == 15384 and len(result["pixels"]) == 256
    assert result["pixels"] == list((EXAMPLE / "build/expected-frame.bin").read_bytes())
    assert result["rows"][0]["pc"] == 0
    if boot == "ram":
        assert result["rows"][1]["pc"] == 0x4000


@pytest.mark.engine
def test_loader_and_inspection_at_distant_ram_words(tmp_path):
    require_engine()
    inputs = {
        "clk": 1,
        "rst": 1,
        "load_enable": 1,
        "inspect": 1,
        "load_address": 16,
        "peek_address": 16,
        "load_data": 32,
        "address": 32,
        "data": 32,
        "size": 3,
        "write": 1,
    }
    changes = [
        {"load_address": 0x4000, "load_data": 0x11223344},
        {"load_enable": 1},
        {"load_enable": 0},
        {"load_address": 0xFFFC, "load_data": 0xCAFEBEEF},
        {"load_enable": 1},
        {"load_enable": 0, "peek_address": 0x4000},
        {"peek_address": 0x4001},
        {"peek_address": 0xFFFC},
        {"peek_address": 0xFFFF},
        {"peek_address": 0x4000},
        {"peek_address": 0},
    ]
    spec = BuildSpec(
        (
            ROOT / "examples/common/async_ram.v",
            ROOT / "examples/riscv/rv32_lanes.v",
            EXAMPLE / "rv32_memory.v",
        ),
        "rv32_memory",
        tmp_path / "ram.cv",
        "legacy",
        clocks=("clk",),
        scenarios=(
            Scenario(
                "64 KiB loader",
                (
                    Step(dict.fromkeys(inputs, 0) | {"rst": 1, "inspect": 1}, False),
                    Step({"rst": 0}, False),
                ),
                tuple(Step(c) for c in changes),
            ),
        ),
    )
    cases, samples = _stimulus(spec, inputs)
    rows = _verilator(spec, inputs, {"word": 32, "pixel": 8}, cases, tmp_path)
    actual = [(int(rows[i]["word"], 2), int(rows[i]["pixel"], 2)) for i in samples]
    assert actual[5:] == [
        (0x11223344, 0x44),
        (0x11223344, 0x33),
        (0xCAFEBEEF, 0xEF),
        (0xCAFEBEEF, 0xCA),
        (0x11223344, 0x44),
        (0, 0),
    ]
    assert check(spec).samples == len(changes)


@pytest.mark.engine
@pytest.mark.parametrize("format_", ["legacy", "canonical-v1"])
def test_native_screen_masked_writes_and_round_trip(tmp_path, format_):
    require_engine()
    from cv_gen.verilog import engine as v1_engine

    if format_ == "canonical-v1" and not v1_engine.ready():
        pytest.skip("Vue v1 engine is not installed")
    source = tmp_path / "display_bus.v"
    source.write_text("""module rv32_graphics(input [7:0] address,input [31:0] data,
        input [3:0] mask,input write,output [7:0] screen_address,
        output [31:0] screen_data,output [3:0] screen_mask,output screen_write);
        assign screen_address=address;assign screen_data=data;
        assign screen_mask=mask;assign screen_write=write;endmodule""")
    output = tmp_path / "screen.cv"
    build(BuildSpec((source,), "rv32_graphics", output, format_))
    subprocess.run(
        ["uv", "run", "python", str(EXAMPLE / "screen.py"), str(output), "--format", format_],
        cwd=ROOT,
        check=True,
    )
    document = json.loads(output.read_text())
    assert "Framebuffer driver" in json.dumps(document)
    assert "RGBLedMatrix" in json.dumps(document)


@pytest.mark.engine
@pytest.mark.parametrize("boot", ["rom", "ram"])
def test_full_frame_in_circuitverse(boot, compiled_graphics):
    if os.environ.get("CVGEN_TEST_GRAPHICS") != "1":
        pytest.skip("set CVGEN_TEST_GRAPHICS=1 for full framebuffer comparisons")
    require_engine()
    spec = load_spec(EXAMPLE / "cvgen-verilog.toml")
    if not spec.output.exists():
        build(spec)
    subprocess.run(
        ["uv", "run", "python", str(EXAMPLE / "run.py"), "--boot", boot], cwd=ROOT, check=True
    )
