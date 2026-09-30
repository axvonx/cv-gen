"""Known program results supplement differential simulator checks."""

import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from cv_gen import engine as legacy_engine
from cv_gen.config import DEFAULT_ENGINE_REV
from cv_gen.verilog import BuildError, BuildSpec, Scenario, Step, build, check, load_spec
from cv_gen.verilog.compare import _stimulus, _verilator

ROOT = Path(__file__).resolve().parents[1]


def require_tools():
    if any(not shutil.which(tool) for tool in ("yosys", "verilator", "node")):
        pytest.skip("Yosys, Verilator, and Node are required")


def require_engine():
    require_tools()
    if not legacy_engine.status(DEFAULT_ENGINE_REV).ready:
        pytest.skip("legacy engine is not installed")


@pytest.mark.parametrize("name", ["chip8", "lc3"])
def test_demo_has_known_architectural_result(tmp_path, name):
    require_tools()
    spec = load_spec(ROOT / "examples" / name / "cvgen-verilog.toml")
    script = tmp_path / "ports.ys"
    netlist = tmp_path / "ports.json"
    script.write_text(
        "\n".join(f'read_verilog "{source}"' for source in spec.sources)
        + f'\nhierarchy -top {spec.top}\nproc\nwrite_json "{netlist}"\n'
    )
    subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], check=True, capture_output=True)
    ports = json.loads(netlist.read_text())["modules"][spec.top]["ports"]
    inputs = {k: len(v["bits"]) for k, v in ports.items() if v["direction"] == "input"}
    outputs = {k: len(v["bits"]) for k, v in ports.items() if v["direction"] == "output"}
    cases, samples = _stimulus(spec, inputs)
    rows = _verilator(spec, inputs, outputs, cases, tmp_path)
    final = {k: int(v, 2) for k, v in rows[samples[-1]].items()}
    assert final["done"] == 1 and final["fault"] == 0
    if name == "chip8":
        assert final["v0"] == 16 and final["vf"] == 1 and final["pc"] == 0x220
        assert final["view_pixel"] == 0
        assert any(int(row["view_pixel"], 2) == 1 for row in rows)
        assert any(int(row["v0"], 2) == 8 for row in rows)
    else:
        assert final["r1"] == 8 and final["r2"] == 9 and final["r3"] == 0xFFF8
        assert final["r7"] == 0x300B and final["halted"] == 1
        assert final["retired"] == 14


@pytest.mark.engine
@pytest.mark.parametrize("name", ["chip8", "lc3"])
def test_large_cpu_in_circuitverse(tmp_path, name):
    if os.environ.get("CVGEN_TEST_CPUS") != "1":
        pytest.skip("set CVGEN_TEST_CPUS=1 to rebuild the larger CPU schematics")
    require_engine()
    spec = replace(
        load_spec(ROOT / "examples" / name / "cvgen-verilog.toml"),
        output=tmp_path / f"{name}.cv",
    )
    result = check(spec)
    assert result.samples == (120 if name == "chip8" else 50)
    assert f"{name}_core" in result.scopes and "Demo" in result.scopes


@pytest.mark.engine
def test_asynchronous_ram_enable_and_zero_initialization(tmp_path):
    require_engine()
    spec = BuildSpec(
        sources=(ROOT / "examples/common/async_ram.v",),
        top="async_ram",
        output=tmp_path / "memory.cv",
        format="legacy",
        parameters={"DATA": 8, "ADDR": 4},
        scenarios=(
            Scenario(
                "memory",
                (Step({"address": 2, "data": 42, "write_enable": 0}),),
                (
                    Step({"write_enable": 1}),
                    Step({"write_enable": 0, "address": 3}),
                    Step({"address": 2}),
                    Step({"data": 99}),
                    Step({"address": 3}),
                    Step({"write_enable": 1}),
                    Step({"write_enable": 0, "address": 2}),
                    Step({"address": 3}),
                ),
            ),
        ),
    )
    result = check(spec)
    doc = json.loads(result.output.read_text())
    top = next(s for s in doc["scopes"] if s["name"] == "async_ram")
    assert len(top["RAM"]) == 1 and not top.get("verilogRAM")


@pytest.mark.engine
def test_clocked_memory_is_rejected_without_replacing_output(tmp_path):
    require_engine()
    source = tmp_path / "clocked.v"
    source.write_text(
        "module clocked(input clk,we,input [3:0] addr,input [7:0] data,output [7:0] q);"
        "reg [7:0] mem[0:15];always @(posedge clk)if(we)mem[addr]<=data;"
        "assign q=mem[addr];endmodule"
    )
    output = tmp_path / "existing.cv"
    output.write_text("preserve this")
    with pytest.raises(BuildError, match="shared-address asynchronous"):
        build(BuildSpec((source,), "clocked", output, "legacy", clocks=("clk",)))
    assert output.read_text() == "preserve this"


@pytest.mark.engine
def test_all_bcd_byte_values(tmp_path):
    require_engine()
    spec = BuildSpec(
        (ROOT / "examples/chip8/chip8_bcd.v",),
        "chip8_bcd",
        tmp_path / "bcd.cv",
        "legacy",
        scenarios=(
            Scenario(
                "all bytes", (Step({"value": 0}),), tuple(Step({"value": n}) for n in range(1, 256))
            ),
        ),
    )
    cases, _ = _stimulus(spec, {"value": 8})
    rows = _verilator(spec, {"value": 8}, {"hundreds": 8, "tens": 8, "ones": 8}, cases, tmp_path)
    for n, row in enumerate(rows):
        assert [int(row[k], 2) for k in ("hundreds", "tens", "ones")] == [
            n // 100,
            n // 10 % 10,
            n % 10,
        ]
    assert check(spec).samples == 256


@pytest.mark.engine
def test_chip8_alu_edge_cases(tmp_path):
    require_engine()
    pairs = [(0, 0), (255, 1), (1, 255), (255, 255), (128, 1), (1, 128), (10, 10)]
    cases = [{"op": op, "a": a, "b": b} for op in (0, 1, 2, 3, 4, 5, 6, 7, 14, 8) for a, b in pairs]
    spec = BuildSpec(
        (ROOT / "examples/chip8/chip8_alu.v",),
        "chip8_alu",
        tmp_path / "alu.cv",
        "legacy",
        scenarios=(
            Scenario("ALU boundaries", (Step(cases[0]),), tuple(Step(case) for case in cases[1:])),
        ),
    )
    widths = {"value": 8, "flag": 1, "flag_write": 1, "valid": 1}
    rows = _verilator(spec, {"op": 4, "a": 8, "b": 8}, widths, cases, tmp_path)
    for case, row in zip(cases, rows, strict=True):
        op, a, b = case["op"], case["a"], case["b"]
        values = {
            0: b,
            1: a | b,
            2: a & b,
            3: a ^ b,
            4: (a + b) & 255,
            5: (a - b) & 255,
            6: b >> 1,
            7: (b - a) & 255,
            14: (b << 1) & 255,
        }
        flags = {4: int(a + b > 255), 5: int(a >= b), 6: b & 1, 7: int(b >= a), 14: b >> 7}
        assert int(row["value"], 2) == values.get(op, a)
        assert int(row["flag"], 2) == flags.get(op, 0)
        assert int(row["flag_write"], 2) == int(op in flags)
        assert int(row["valid"], 2) == int(op in values)
    assert check(spec).samples == len(cases)


@pytest.mark.engine
def test_font_rom_keeps_initialized_bytes(tmp_path):
    require_engine()
    spec = BuildSpec(
        (ROOT / "examples/chip8/chip8_rom.v",),
        "chip8_rom_bank_0",
        tmp_path / "font.cv",
        "legacy",
        scenarios=(
            Scenario(
                "font", (Step({"address": 0}),), tuple(Step({"address": n}) for n in range(1, 16))
            ),
        ),
    )
    result = check(spec)
    doc = json.loads(result.output.read_text())
    top = next(s for s in doc["scopes"] if s["name"] == "chip8_rom_bank_0")
    assert len(top["Rom"]) == 1
    assert top["Rom"][0]["customData"]["constructorParamaters"][0][0] != 0
