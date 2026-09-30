"""RV32I boundaries and an independently known compiled-C result."""

import os
from dataclasses import replace
from pathlib import Path

import pytest
from test_cpu_examples import require_engine, require_tools

from cv_gen.verilog import BuildSpec, Scenario, Step, check, load_spec
from cv_gen.verilog.compare import _stimulus, _verilator

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/riscv"
OUTPUTS = {
    "pc": 32,
    "instruction": 32,
    "a0": 32,
    "sp": 32,
    "result": 32,
    "retired": 16,
    "state": 2,
    "done": 1,
    "fault": 1,
}


def test_compiled_c_result_and_stack(tmp_path):
    require_tools()
    spec = load_spec(EXAMPLE / "cvgen-verilog.toml")
    cases, samples = _stimulus(spec, {"clk": 1, "rst": 1, "run": 1})
    rows = _verilator(spec, {"clk": 1, "rst": 1, "run": 1}, OUTPUTS, cases, tmp_path)
    final = {k: int(v, 2) for k, v in rows[samples[-1]].items()}
    assert final["done"] == 1 and final["fault"] == 0
    assert final["result"] == final["a0"] == 55
    assert final["sp"] == 0x1000
    assert any(int(rows[i]["sp"], 2) < 0x1000 for i in samples)
    assert all(row["fault"] == "0" for row in rows)
    # A real loop, function calls and RAM traffic executed, rather than a constant result.
    assert final["retired"] > 100


def alu_cases():
    return [
        {"a": a, "b": b, "op": op, "alternate": alternate}
        for a, b in [
            (0, 0),
            (0xFFFFFFFF, 1),
            (0x80000000, 31),
            (0x7FFFFFFF, 0xFFFFFFFF),
            (0x80000000, 0),
            (0xDEADBEEF, 32),
        ]
        for op in range(8)
        for alternate in range(2)
    ]


def test_alu_unsigned_wrap_signed_compare_and_shifts(tmp_path):
    require_tools()
    cases = alu_cases()
    spec = BuildSpec(
        (EXAMPLE / "rv32_shift.v", EXAMPLE / "rv32_alu.v"),
        "rv32_alu",
        tmp_path / "alu.cv",
        "legacy",
    )
    rows = _verilator(
        spec,
        {"a": 32, "b": 32, "op": 3, "alternate": 1},
        {"value": 32, "less_signed": 1, "less_unsigned": 1, "equal": 1},
        cases,
        tmp_path,
    )
    for case, row in zip(cases, rows, strict=True):
        a, b, op, alt = (case[k] for k in ("a", "b", "op", "alternate"))
        sa, sb = (v if v < 0x80000000 else v - (1 << 32) for v in (a, b))
        values = [
            a - b if alt else a + b,
            a << (b & 31),
            int(sa < sb),
            int(a < b),
            a ^ b,
            (sa if alt else a) >> (b & 31),
            a | b,
            a & b,
        ]
        assert int(row["value"], 2) == values[op] & 0xFFFFFFFF
        assert int(row["less_signed"], 2) == int(sa < sb)
        assert int(row["less_unsigned"], 2) == int(a < b)
        assert int(row["equal"], 2) == int(a == b)


@pytest.mark.engine
def test_rv32_alu_in_circuitverse(tmp_path):
    require_engine()
    cases = alu_cases()
    spec = BuildSpec(
        (EXAMPLE / "rv32_shift.v", EXAMPLE / "rv32_alu.v"),
        "rv32_alu",
        tmp_path / "alu.cv",
        "legacy",
        scenarios=(
            Scenario(
                "32-bit boundaries", (Step(cases[0], sample=False),), tuple(Step(c) for c in cases)
            ),
        ),
    )
    assert check(spec).samples == len(cases)


@pytest.mark.engine
@pytest.mark.parametrize("manifest", ["cvgen-verilog.toml", "cvgen-verilog-v1.toml"])
def test_compiled_c_in_circuitverse(tmp_path, manifest):
    if os.environ.get("CVGEN_TEST_CPUS") != "1":
        pytest.skip("set CVGEN_TEST_CPUS=1 to rebuild the RV32 schematics")
    require_engine()
    spec = replace(load_spec(EXAMPLE / manifest), output=tmp_path / "riscv.cv")
    result = check(spec)
    assert result.samples == 800
    assert {"rv32_core", "rv32_decode", "rv32_registers", "Demo"} <= set(result.scopes)


@pytest.mark.engine
def test_demo_with_twelve_ports_routes_dense_block_outputs(tmp_path):
    require_engine()
    from cv_gen.verilog import build

    source = tmp_path / "dense.v"
    source.write_text(
        "module dense(input clk,rst,run,output [31:0] a,b,c,d,e,f,g,h,i);"
        "assign a={31'b0,clk};assign b={31'b0,rst};assign c={31'b0,run};"
        "assign d=a;assign e=b;assign f=c;assign g=a;assign h=b;assign i=c;endmodule"
    )
    assert build(
        BuildSpec((source,), "dense", tmp_path / "dense.cv", "legacy", clocks=("clk",))
    ).output.exists()


def decoder_cases():
    # Raw encodings exercise instructions outside the compiler's chosen demo subset.
    def instruction(opcode, f3=0, f7=0, immediate=0):
        if opcode in (0x13, 0x03, 0x67):
            return ((immediate & 0xFFF) << 20) | (f3 << 12) | opcode
        return (f7 << 25) | (f3 << 12) | opcode

    entries = [
        # instruction, a, b, pc, observed output, expected value
        (0xFFFFF037, 0, 0, 0x100, "value", 0xFFFFF000),  # LUI
        (0x00001017, 0, 0, 0x100, "value", 0x1100),  # AUIPC
        (0x0080006F, 0, 0, 0x100, "next_pc", 0x108),  # JAL +8
        (instruction(0x67, immediate=1), 0x108, 0, 0x100, "next_pc", 0x108),
        (instruction(0x13, immediate=-1), 0, 0, 0x100, "value", 0xFFFFFFFF),
        (instruction(0x33, f7=0x20), 0, 1, 0x100, "value", 0xFFFFFFFF),
        (instruction(0x13, f3=2, immediate=-1), 0x80000000, 0, 0x100, "value", 1),
        (instruction(0x13, f3=3, immediate=-1), 0x80000000, 0, 0x100, "value", 1),
        (instruction(0x13, f3=5, immediate=31), 0x80000000, 0, 0x100, "value", 1),
        (instruction(0x13, f3=5, immediate=0x41F), 0x80000000, 0, 0x100, "value", 0xFFFFFFFF),
        (0x00000463, 3, 3, 0x100, "next_pc", 0x108),  # BEQ +8
        (0x00001463, 3, 4, 0x100, "next_pc", 0x108),  # BNE +8
        (0x00004463, 0xFFFFFFFF, 1, 0x100, "next_pc", 0x108),  # BLT
        (0x00005463, 1, 0xFFFFFFFF, 0x100, "next_pc", 0x108),  # BGE
        (0x00006463, 1, 0xFFFFFFFF, 0x100, "next_pc", 0x108),  # BLTU
        (0x00007463, 0xFFFFFFFF, 1, 0x100, "next_pc", 0x108),  # BGEU
        (0x00004463, 1, 0xFFFFFFFF, 0x100, "next_pc", 0x104),  # untaken BLT
        (0x00000163, 1, 2, 0x100, "illegal", 0),  # untaken misaligned BEQ
        (0x00000163, 1, 1, 0x100, "illegal", 1),  # taken misaligned BEQ
        (0x0020006F, 0, 0, 0x100, "illegal", 1),  # misaligned JAL
        (instruction(0x03, f3=0), 0x901, 0, 0x100, "illegal", 0),
        (instruction(0x03, f3=1), 0x901, 0, 0x100, "illegal", 1),
        (instruction(0x03, f3=2), 0x902, 0, 0x100, "illegal", 1),
        (instruction(0x03, f3=4), 0x1A8, 0, 0x20, "illegal", 0),
        (instruction(0x03, f3=5), 0x900, 0, 0x100, "load", 1),
        (instruction(0x03, f3=3), 0x900, 0, 0x100, "illegal", 1),
        (0x01C30023, 0x800, 7, 0x24, "illegal", 0),
        (instruction(0x23, f3=0), 0x800, 7, 0x24, "illegal", 0),
        (instruction(0x23, f3=2), 0x900, 7, 0x100, "store", 1),
        (instruction(0x33, f7=1), 0, 0, 0x100, "illegal", 1),  # M extension
        (instruction(0x13, f3=1, immediate=0x400), 0, 0, 0x100, "illegal", 1),
        (0x0000000F, 0, 0, 0x100, "illegal", 0),  # FENCE
        (0x0000100F, 0, 0, 0x100, "illegal", 1),  # FENCE.I extension
        (0x00000073, 0, 0, 0x100, "illegal", 1),  # ECALL stops
        (0x00100073, 0, 0, 0x100, "illegal", 1),  # EBREAK stops
        (0, 0, 0, 0x100, "illegal", 1),
    ]
    cases = [
        dict(zip(("instruction", "a", "b", "pc"), entry[:4], strict=True)) for entry in entries
    ]
    return entries, cases


@pytest.mark.engine
def test_decode_branch_alignment_and_illegal_instructions(tmp_path):
    require_engine()
    entries, cases = decoder_cases()
    spec = BuildSpec(
        tuple(EXAMPLE / name for name in ("rv32_shift.v", "rv32_alu.v", "rv32_decode.v")),
        "rv32_decode",
        tmp_path / "decode.cv",
        "legacy",
        scenarios=(
            Scenario(
                "ISA boundaries",
                (Step(cases[0], sample=False),),
                tuple(Step(case) for case in cases),
            ),
        ),
    )
    rows = _verilator(
        spec,
        {"instruction": 32, "a": 32, "b": 32, "pc": 32},
        {
            "value": 32,
            "next_pc": 32,
            "address": 32,
            "write_register": 1,
            "load": 1,
            "store": 1,
            "illegal": 1,
            "size": 3,
        },
        cases,
        tmp_path,
    )
    for entry, row in zip(entries, rows, strict=True):
        assert int(row[entry[4]], 2) == entry[5], entry
    assert check(spec).samples == len(cases)


@pytest.mark.engine
def test_state_transition_does_not_capture_transient_enabled_fault(tmp_path):
    require_engine()
    source = tmp_path / "transition.v"
    source.write_text("""module transition(input clk,rst,output reg [1:0] state,
        output reg [31:0] address,output reg store,output reg fault);
        wire bad=state==2 && store && address<32'h800;
        always @(posedge clk or posedge rst)begin
          if(rst)begin state<=0;address<=32'h100;store<=0;fault<=0;end
          else begin
            if(bad)fault<=1;
            case(state)
              0:state<=1;
              1:begin state<=2;address<=32'h800;store<=1;end
              2:state<=3;
            endcase
          end
        end
        endmodule""")
    steps = tuple(Step({"clk": value}, sample=value == 1) for _ in range(4) for value in (1, 0))
    spec = BuildSpec(
        (source,),
        "transition",
        tmp_path / "transition.cv",
        "legacy",
        clocks=("clk",),
        scenarios=(
            Scenario(
                "simultaneous state and address",
                (Step({"clk": 0, "rst": 1}, False), Step({"rst": 0}, False)),
                steps,
            ),
        ),
    )
    assert check(spec).samples == 4


@pytest.mark.engine
@pytest.mark.parametrize("format_", ["legacy", "canonical-v1"])
def test_mixed_width_greater_and_less_equal_mapping(tmp_path, format_):
    require_engine()
    from cv_gen.verilog import V1_REV

    if format_ == "canonical-v1":
        engine = Path(os.environ.get("CVGEN_V1_DIR", Path.home() / ".cache/cv-gen/v1" / V1_REV))
        if not (engine / "node_modules/.bin/vitest").is_file():
            pytest.skip("Vue v1 engine is not installed")
    source = tmp_path / "compare.v"
    source.write_text(
        "module compare(input [2:0] a,input [1:0] b,output gt,le,lt,ge);"
        "assign gt=a>b;assign le=a<=b;assign lt=a<b;assign ge=a>=b;endmodule"
    )
    cases = tuple(Step({"a": a, "b": b}) for a in range(8) for b in range(4))
    spec = BuildSpec(
        (source,),
        "compare",
        tmp_path / "compare.cv",
        format_,
        scenarios=(Scenario("all mixed-width pairs", (Step({"a": 0, "b": 0}, False),), cases),),
    )
    assert check(spec).samples == 32


@pytest.mark.engine
@pytest.mark.parametrize("format_", ["legacy", "canonical-v1"])
def test_nested_parameterized_module_import_order(tmp_path, format_):
    require_engine()
    from cv_gen.verilog import engine as v1_engine

    if format_ == "canonical-v1" and not v1_engine.ready():
        pytest.skip("Vue v1 engine is not installed")
    source = tmp_path / "nested.v"
    source.write_text("""module leaf #(parameter W=8)(input clk,rst,
        input [W-1:0] data,output reg [W-1:0] q);
        always @(posedge clk or posedge rst)if(rst)q<=0;else q<=data;
        endmodule
        module middle(input clk,rst,input [15:0] data,output [15:0] q);
        leaf #(.W(16)) child(clk,rst,data,q);endmodule
        module nested(input clk,rst,input [15:0] data,output [15:0] q);
        middle child(clk,rst,data,q);endmodule""")
    spec = BuildSpec(
        (source,),
        "nested",
        tmp_path / "nested.cv",
        format_,
        clocks=("clk",),
        scenarios=(
            Scenario(
                "nested parameter",
                (
                    Step({"clk": 0, "rst": 1, "data": 0}, False),
                    Step({"rst": 0, "data": 0xCAFE}, False),
                ),
                (Step({"clk": 1}), Step({"clk": 0, "data": 2}, False), Step({"clk": 1})),
            ),
        ),
    )
    assert check(spec).samples == 2
