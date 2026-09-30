import random

import pytest

from cv_gen import pipeline, project
from cv_gen.config import load_config
from cv_gen.model import Signal
from cv_gen.oracles import load_oracles
from cv_gen.trace import TraceOracle, generate_trace

INPUTS = (Signal("IN Data", 4), Signal("IN Write Enable", 1), Signal("IN CLK", 1))
OUTPUTS = (Signal("OUT", 4),)


def reg_oracle(workspace):
    return load_oracles(workspace / "oracles.py").trace["reg4"]()


def test_trace_alternates_clock_and_tracks_state(workspace):
    trace = generate_trace(reg_oracle(workspace), "Reg", INPUTS, OUTPUTS, cycles=3)
    group = trace.data.groups[0]
    series = {s.label: s.values for s in (*group.inputs, *group.outputs)}
    assert series["IN CLK"] == ("0", "1") * 3
    # cycle 0: unknown before the edge, 5 after; cycle 1 (enable low) holds 5
    assert series["OUT"][1:4] == ("0101", "0101", "0101")
    assert trace.unknown == (("OUT", 0),)


def test_trace_rejects_unknown_stimulus_inputs():
    class Bad(TraceOracle):
        def stimulus(self, rng: random.Random, cycles):
            yield {"IN Bogus": 1}

        def outputs(self, inputs):
            return {"OUT": 0}

    with pytest.raises(ValueError, match="unknown inputs"):
        generate_trace(Bad(), "Reg", INPUTS, OUTPUTS, cycles=1)


def test_trace_requires_clock_input():
    with pytest.raises(ValueError, match="no clock input"):
        generate_trace(TraceOracle(), "X", INPUTS[:2], OUTPUTS, cycles=1)


def test_build_calibrates_unknown_outputs(workspace):
    config = load_config(workspace / "cvgen-tests.toml")
    document = project.load(workspace / "demo.cv")
    calls = []

    def fake_calibrate(scopes, doc):
        calls.append(scopes)
        n = project.find_scope(doc, "Reg").testbench.case_count
        return {"scopes": [{"scope": "Reg", "status": "fail",
                            "results": [{"OUT": ["1111"] * n}]}]}

    build = pipeline.build(config, document, load_oracles(config.oracles), fake_calibrate)
    assert calls == [["Reg"]]
    assert build.unchecked == {"Reg": 1}
    reg = project.find_scope(build.document, "Reg").testbench.groups[0].outputs[0]
    assert reg.values[0] == "1111"  # calibrated from the engine
    assert reg.values[1] == "0101"  # oracle-specified values untouched


def test_build_without_calibrator_refuses_unknowns(workspace):
    config = load_config(workspace / "cvgen-tests.toml")
    with pytest.raises(project.ProjectError, match="need engine calibration"):
        pipeline.build(config, project.load(workspace / "demo.cv"),
                       load_oracles(config.oracles), None)


def test_int_oracle_needs_single_output(workspace, document):
    config = load_config(workspace / "cvgen-tests.toml")
    document["scopes"][0]["Output"].append(dict(document["scopes"][0]["Output"][0], label="Z"))
    with pytest.raises(ValueError, match="one int but the circuit has 2 outputs"):
        pipeline.build(config, document, load_oracles(config.oracles), lambda s, d: {})


def test_duplicate_oracle_names_rejected(tmp_path):
    (tmp_path / "o.py").write_text(
        "from cv_gen.oracles import comb\n"
        "@comb('x')\ndef a(v): return 0\n@comb('x')\ndef b(v): return 0\n"
    )
    with pytest.raises(ValueError, match="defined twice"):
        load_oracles(tmp_path / "o.py")
