"""Known-answer and fault-isolation tests using a generated, self-contained circuit."""

import json
import shutil

import pytest

from cv_gen import engine, pipeline, project, report
from cv_gen.config import DEFAULT_ENGINE_REV, load_config
from cv_gen.oracles import load_oracles
from cv_gen.verilog import BuildSpec, build

pytestmark = [
    pytest.mark.engine,
    pytest.mark.skipif(
        not engine.status(DEFAULT_ENGINE_REV).ready
        or not all(shutil.which(tool) for tool in ("yosys", "node")),
        reason="Yosys, Node and the legacy test engine are required",
    ),
]


def check(config, document, tmp_path):
    built = pipeline.build(
        config,
        document,
        load_oracles(config.oracles),
        pipeline.engine_calibrator(config.engine_rev),
    )
    path = tmp_path / "tested.cv"
    project.save(built.document, path)
    raw = engine.run(config.engine_rev, path)
    return report.build_report(raw, project.dependency_names(built.document))


@pytest.fixture(scope="module")
def circuit(tmp_path_factory):
    root = tmp_path_factory.mktemp("engine-fixture")
    source = root / "and.v"
    source.write_text("""module AND(input A,B,output Y);assign Y=A&B;endmodule
        module AND4(input [3:0] A,B,output [3:0] Y);
        genvar i;generate for(i=0;i<4;i=i+1)begin:g
        AND gate(A[i],B[i],Y[i]);end endgenerate endmodule""")
    path = root / "and.cv"
    build(BuildSpec((source,), "AND4", path, "legacy"))
    (root / "oracles.py").write_text(
        'from cv_gen.oracles import comb\n@comb("and")\n'
        'def and_gate(v):return {"Y": v["A"] & v["B"]}\n'
    )
    manifest = root / "cvgen-tests.toml"
    manifest.write_text(
        '[project]\nfile="and.cv"\n[generate]\noracles="oracles.py"\nmax_cases=256\n'
        '[[suite]]\nscope="AND"\noracle="and"\n'
        '[[suite]]\nscope="AND4"\noracle="and"\n'
    )
    return load_config(manifest), project.load(path)


def test_generated_circuit_known_answer(circuit, tmp_path):
    config, document = circuit
    result = check(config, document, tmp_path)
    failing = {r.scope for r in result.scopes if r.failing}
    assert failing == set()
    assert result.root_causes == []
    assert not any(r.status == "engine-error" for r in result.scopes)


def test_broken_gate_has_one_root_cause(circuit, tmp_path):
    config, document = circuit
    mutant = json.loads(json.dumps(document))
    scope = next(s for s in mutant["scopes"] if s["name"] == "AND")
    gates = scope.pop("AndGate")
    for gate in gates:
        gate["objectType"] = "OrGate"
    scope["OrGate"] = gates

    result = check(config, mutant, tmp_path)
    roots = {r.scope for r in result.root_causes}
    assert roots == {"AND"}
    assert "AND4" in result.downstream_of("AND")
