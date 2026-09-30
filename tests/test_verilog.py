"""Verilog manifest, publication, and acceptance checks."""

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from cv_gen import engine as legacy_engine
from cv_gen.config import DEFAULT_ENGINE_REV
from cv_gen.verilog import BuildError, Scenario, Step, _validate_document, build, check, load_spec
from cv_gen.verilog import engine as v1_engine
from cv_gen.verilog.compare import _stimulus, _verilator

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "registered_datapath"
CPU = ROOT / "examples" / "teaching_cpu"


def test_manifest_resolves_ordered_sources_and_options():
    spec = load_spec(FIXTURE / "cvgen-verilog.toml")
    assert [p.name for p in spec.sources] == ["child.v", "top.sv"]
    assert spec.top == "top"
    assert spec.parameters == {"WIDTH": 5}
    assert spec.defines == {"CVGEN_EXAMPLE": "1"}
    assert spec.clocks == ("clk",)
    assert spec.scenarios[0].setup[0].inputs["rst"] == 1


@pytest.mark.parametrize(
    "manifest,diagnostic",
    [
        ('[verilog]\nsources="top.v"\n', "sources must be a list"),
        ('[verilog]\nsources=["top.v"]\ntop="top"\noutput="out.cv"\nformat=[]\n', "top and format"),
        (
            '[verilog]\nsources=["top.v"]\ntop="top"\noutput="out.cv"\nformat="legacy"\n'
            '[[scenario]]\nname="bad"\nsteps=[{sample=true}]\n',
            "step needs an inputs table",
        ),
    ],
)
def test_invalid_manifest_has_clear_error(tmp_path, manifest, diagnostic):
    (tmp_path / "top.v").write_text("module top(input a, output y); assign y=a; endmodule\n")
    path = tmp_path / "cvgen-verilog.toml"
    path.write_text(manifest)
    with pytest.raises(BuildError, match=diagnostic):
        load_spec(path)


@pytest.mark.skipif(shutil.which("yosys") is None, reason="Yosys is not installed")
def test_bad_source_never_replaces_output(tmp_path):
    manifest = tmp_path / "cvgen-verilog.toml"
    (tmp_path / "bad.v").write_text("module top(input a, output y); assign y = ; endmodule\n")
    manifest.write_text(
        '[verilog]\nsources=["bad.v"]\ntop="top"\noutput="result.cv"\nformat="legacy"\n'
    )
    spec = load_spec(manifest)
    spec.output.write_text("previous project")
    with pytest.raises(BuildError, match="Yosys failed"):
        build(spec)
    assert spec.output.read_text() == "previous project"
    with pytest.raises(BuildError, match="Yosys failed"):
        check(spec)
    assert spec.output.read_text() == "previous project"


def test_bad_connection_is_rejected(tmp_path):
    spec = load_spec(FIXTURE / "cvgen-verilog.toml")
    document = {
        "scopes": [
            {"id": 1, "name": "top", "allNodes": [{"bitWidth": 1, "connections": [9]}]},
            {"id": 2, "name": "Demo", "allNodes": []},
        ]
    }
    with pytest.raises(BuildError, match="invalid connection"):
        _validate_document(replace(spec, output=tmp_path / "out.cv"), document)


@pytest.mark.skipif(shutil.which("yosys") is None, reason="Yosys is not installed")
def test_undriven_blackbox_is_rejected(tmp_path):
    source = tmp_path / "blackbox.v"
    source.write_text(
        "(* blackbox *) module mystery(input a, output y); endmodule\n"
        "module top(input a, output y); mystery u(.a(a),.y(y)); endmodule\n"
    )
    spec = replace(
        load_spec(FIXTURE / "cvgen-verilog.toml"),
        sources=(source,),
        output=tmp_path / "out.cv",
        clocks=(),
        scenarios=(),
    )
    with pytest.raises(BuildError, match=r"Undriven net|blackbox"):
        build(spec)
    assert not spec.output.exists()


@pytest.mark.engine
@pytest.mark.parametrize(
    "fmt,manifest",
    [
        ("legacy", "cvgen-verilog.toml"),
        ("canonical-v1", "cvgen-verilog-v1.toml"),
    ],
)
def test_registered_datapath_both_formats(tmp_path, fmt, manifest):
    if fmt == "legacy" and not legacy_engine.status(DEFAULT_ENGINE_REV).ready:
        pytest.skip("legacy engine is not installed")
    if fmt == "canonical-v1" and not v1_engine.ready():
        pytest.skip("Vue v1 engine is not installed")
    spec = replace(load_spec(FIXTURE / manifest), output=tmp_path / f"top-{fmt}.cv")
    result = check(spec)
    assert result.format == fmt
    assert result.samples == 5
    assert set(result.scopes) == {"add_offset_1", "top", "Demo"}
    assert result.output.is_file()


@pytest.mark.engine
@pytest.mark.parametrize("fmt", ["legacy", "canonical-v1"])
def test_clock_named_port_survives_import_and_check(tmp_path, fmt):
    if fmt == "legacy" and not legacy_engine.status(DEFAULT_ENGINE_REV).ready:
        pytest.skip("legacy engine is not installed")
    if fmt == "canonical-v1" and not v1_engine.ready():
        pytest.skip("Vue v1 engine is not installed")
    source = tmp_path / "clocked.v"
    source.write_text(
        "module top(input clock, input data, output reg q);\n"
        "always @(posedge clock) q <= data;\nendmodule\n"
    )
    spec = replace(
        load_spec(FIXTURE / "cvgen-verilog.toml"),
        sources=(source,),
        output=tmp_path / f"clock-{fmt}.cv",
        format=fmt,
        includes=(),
        defines={},
        parameters={},
        clocks=("clock",),
        scenarios=(
            Scenario(
                "clock port",
                (Step({"clock": 0, "data": 0}, False),),
                (
                    Step({"data": 1}, False),
                    Step({"clock": 1}, True),
                    Step({"clock": 0}, False),
                    Step({"data": 0}, False),
                    Step({"clock": 1}, True),
                ),
            ),
        ),
        cases=0,
    )
    result = check(spec)
    assert result.samples == 2


@pytest.mark.engine
@pytest.mark.parametrize("fmt", ["legacy", "canonical-v1"])
def test_seeded_combinational_mixed_widths(tmp_path, fmt):
    if fmt == "legacy" and not legacy_engine.status(DEFAULT_ENGINE_REV).ready:
        pytest.skip("legacy engine is not installed")
    if fmt == "canonical-v1" and not v1_engine.ready():
        pytest.skip("Vue v1 engine is not installed")
    source = tmp_path / "mixed.v"
    source.write_text(
        "module top(input [3:0] a, input b, output [3:0] y);\n"
        "assign y = b ? a : 4'b0101;\nendmodule\n"
    )
    spec = replace(
        load_spec(FIXTURE / "cvgen-verilog.toml"),
        sources=(source,),
        output=tmp_path / f"mixed-{fmt}.cv",
        format=fmt,
        includes=(),
        defines={},
        parameters={},
        clocks=(),
        scenarios=(),
        seed=123,
        cases=12,
    )
    result = check(spec)
    assert result.samples == 12


@pytest.mark.engine
def test_legacy_concat_routing_preserves_mixed_widths(tmp_path):
    if not legacy_engine.status(DEFAULT_ENGINE_REV).ready:
        pytest.skip("legacy engine is not installed")
    source = tmp_path / "concat.v"
    source.write_text(
        "module top(input [2:0] a, input b, output [3:0] y);\n"
        "assign y = {a, b} ^ 4'b0101;\nendmodule\n"
    )
    spec = replace(
        load_spec(FIXTURE / "cvgen-verilog.toml"),
        sources=(source,),
        output=tmp_path / "result.cv",
        includes=(),
        defines={},
        parameters={},
        clocks=(),
        scenarios=(),
        cases=12,
        seed=123,
    )
    result = check(spec)
    assert result.samples == 12
    assert result.output.is_file()


@pytest.mark.engine
@pytest.mark.parametrize(
    "fmt,manifest",
    [
        ("legacy", "cvgen-verilog.toml"),
        ("canonical-v1", "cvgen-verilog-v1.toml"),
    ],
)
def test_teaching_cpu_runs_in_matching_simulator(tmp_path, fmt, manifest):
    if fmt == "legacy" and not legacy_engine.status(DEFAULT_ENGINE_REV).ready:
        pytest.skip("legacy engine is not installed")
    if fmt == "canonical-v1" and not v1_engine.ready():
        pytest.skip("Vue v1 engine is not installed")
    spec = replace(load_spec(CPU / manifest), output=tmp_path / f"teaching-{fmt}.cv")
    result = check(spec)
    assert result.format == fmt
    assert result.samples == 5
    assert set(result.scopes) == {"teaching_cpu", "Demo"}
    assert result.output.is_file()
    if fmt == "legacy":
        document = json.loads(result.output.read_text())
        top = next(scope for scope in document["scopes"] if scope["name"] == "teaching_cpu")
        assert all(not scope["verilogMetadata"]["isVerilogCircuit"] for scope in document["scopes"])
        assert document["focussedCircuit"] == top["id"]
        assert len(top["DflipFlop"]) == 4
        assert len(top["Adder"]) == 2  # PC increment and accumulator; muxes need no adder
        lanes = [node for node in top["allNodes"] if node["type"] == 2]
        assert max(node["x"] for node in lanes) < 5000
        assert max(node["y"] for node in lanes) < 2000
        nodes = top["allNodes"]
        length = 0
        for i, node in enumerate(nodes):
            # Native components retain relative pin coordinates; wire bend
            # coordinates are absolute and provide a stable layout bound.
            assert node["x"] % 10 == 0 and node["y"] % 10 == 0
            if node["type"] == 2:
                for peer in node["connections"]:
                    if peer > i and nodes[peer]["type"] == 2:
                        other = nodes[peer]
                        assert node["x"] == other["x"] or node["y"] == other["y"]
                        length += abs(node["x"]-other["x"]) + abs(node["y"]-other["y"])
        assert length < 100000  # old perimeter routing exceeded 190000
        for constant in top["ConstantVal"]:
            _, width, value = constant["customData"]["constructorParamaters"]
            assert len(value) == width
        report = legacy_engine.run(DEFAULT_ENGINE_REV, result.output)
        assert report["project"] is not None
    else:
        document = json.loads(result.output.read_text())
        assert all(
            not circuit["verilogMetadata"]["isVerilogCircuit"]
            for circuit in document["circuits"].values()
        )


@pytest.mark.skipif(shutil.which("verilator") is None, reason="Verilator is not installed")
def test_teaching_cpu_program_has_expected_register_trace(tmp_path):
    spec = load_spec(CPU / "cvgen-verilog.toml")
    inputs = {"clk": 1, "rst": 1, "opcode": 3, "immediate": 8}
    outputs = {"pc": 4, "accumulator": 8, "out_value": 8, "halted": 1}
    cases, sampled = _stimulus(spec, inputs)
    rows = _verilator(spec, inputs, outputs, cases, tmp_path)
    actual = [
        tuple(int(row[name], 2) for name in outputs)
        for i, row in enumerate(rows)
        if i in sampled
    ]
    assert actual == [
        (1, 3, 0, 0),
        (2, 8, 0, 0),
        (3, 8, 8, 0),
        (3, 8, 8, 1),
        (3, 8, 8, 1),
    ]
