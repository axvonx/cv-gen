from pathlib import Path

import pytest


def make_scope(scope_id, name, inputs, outputs, uses=(), testbench=None):
    """A minimal CircuitVerse scope: ``inputs``/``outputs`` are [(label, width)]."""

    def port(label, width):
        return {"label": label, "customData": {"constructorParamaters": ["RIGHT", width, None]}}

    scope = {
        "id": scope_id,
        "name": name,
        "Input": [port(label, width) for label, width in inputs],
        "Output": [port(label, width) for label, width in outputs],
        "SubCircuit": [{"id": str(dep)} for dep in uses],
        "allNodes": [],
        "layout": {"width": 100},
    }
    if testbench is not None:
        scope["testbenchData"] = testbench
    return scope


@pytest.fixture
def document():
    return {
        "name": "Demo",
        "timePeriod": 500,
        "scopes": [
            make_scope(1, "AND", [("A", 1), ("B", 1)], [("Y", 1)]),
            make_scope(2, "AND4", [("A", 4), ("B", 4)], [("Y", 4)], uses=[1]),
            make_scope(3, "Reg", [("IN Data", 4), ("IN Write Enable", 1), ("IN CLK", 1)],
                       [("OUT", 4)], uses=[2]),
        ],
    }


ORACLES = '''
from cv_gen.oracles import TraceOracle, comb, trace

@comb("and")
def and_(v):
    return v["A"] & v["B"]

@trace("reg4")
class Reg4(TraceOracle):
    def reset(self):
        self.q = None
    def stimulus(self, rng, cycles):
        yield {"IN Data": 5, "IN Write Enable": 1}
        yield {"IN Data": 9, "IN Write Enable": 0}
        while True:
            yield {"IN Data": rng.getrandbits(4), "IN Write Enable": 1}
    def edge(self, inputs):
        if inputs["IN Write Enable"]:
            self.q = inputs["IN Data"]
    def outputs(self, inputs):
        return {"OUT": self.q}
'''


@pytest.fixture
def workspace(tmp_path: Path, document):
    import json

    (tmp_path / "demo.cv").write_text(json.dumps(document))
    (tmp_path / "oracles.py").write_text(ORACLES)
    (tmp_path / "cvgen-tests.toml").write_text(
        '[project]\nfile = "demo.cv"\nid = "demo-slug"\nserver = "https://cv.example"\n\n'
        '[generate]\noracles = "oracles.py"\nmax_cases = 16\n\n'
        '[[suite]]\nscope = "AND"\noracle = "and"\n\n'
        '[[suite]]\nscope = "AND4"\noracle = "and"\n\n'
        '[[suite]]\nscope = "Reg"\noracle = "reg4"\nmax_cases = 8\n'
    )
    return tmp_path
