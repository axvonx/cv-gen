"""Compatibility checks fail closed before expensive native/WASM compilation."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from fastpath.compiler import bindings, check_warnings

from cv_gen.verilog import BuildError


def fixture():
    ports = [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "row_index", "direction": "output", "width": 4},
        {"name": "frame", "direction": "output", "width": 5},
        *[{"name": f"color_{i}", "direction": "output", "width": 24} for i in range(16)],
    ]

    def port(p):
        return {
            "label": p["name"],
            "customData": {
                "constructorParamaters": ["RIGHT", p["width"]],
                "nodes": {"output1": 0, "inp1": 0},
                "values": {"state": 0},
            },
        }

    demo = {
        "id": 1,
        "name": "Demo",
        "Clock": [port(ports[0])],
        "Input": [port(ports[1])],
        "Output": [port(p) for p in ports[2:]],
        "RGBLedMatrix": [
            {
                "label": "screen",
                "customData": {"constructorParamaters": [{"rows": 16, "columns": 16}]},
            }
        ],
    }
    return {"scopes": [{"name": "camera_animation"}, demo]}, ports


def test_binding_rejects_missing_ambiguous_or_wrong_width_ports():
    document, ports = fixture()
    assert (
        bindings(copy.deepcopy(document), copy.deepcopy(ports), "rom-playback", "camera_animation")[
            "scopeId"
        ]
        == 1
    )
    for mutation in ("missing", "ambiguous", "width", "clock"):
        broken = copy.deepcopy(document)
        demo = broken["scopes"][1]
        if mutation == "missing":
            demo["Output"].pop()
        elif mutation == "ambiguous":
            demo["Output"].append(demo["Output"][0])
        elif mutation == "width":
            demo["Input"][0]["customData"]["constructorParamaters"][1] = 32
        else:
            demo["Clock"].append(demo["Clock"][0])
        with pytest.raises(BuildError):
            bindings(broken, copy.deepcopy(ports), "rom-playback", "camera_animation")


def test_unknown_verilator_warning_is_not_silently_suppressed():
    assert check_warnings("%Warning-COMBDLY: async RAM") == ["COMBDLY"]
    with pytest.raises(BuildError, match="unreviewed"):
        check_warnings("%Warning-UNSUPPORTED: new incompatibility")
