"""Embed the verified ROM/RAM boot trace for CircuitVerse's Run All button."""

import json
from pathlib import Path

from reference import INPUTS

from cv_gen import project
from cv_gen.testbench import Group, Series, TestData


def tested_project(path, loads, rows, output):
    current = dict.fromkeys(INPUTS, 0)
    cases = []
    expected = []

    def step(values, row=None):
        current.update(values)
        cases.append(current.copy())
        expected.append({name: row[name] if row else 0 for name in ("result", "done", "fault")})

    step({})
    step({"rst": 1})
    step({"rst": 0})
    for item in loads:
        step({"load_address": item["address"], "load_data": item["data"]})
        step({"load_enable": 1})
        step({"load_enable": 0})
    step({"boot_ram": int(bool(loads)), "rst": 1})
    step({"rst": 0})
    step({"run": 1})
    for row in rows:
        step({"clk": 1}, row)
        step({"clk": 0}, row)
    step({"run": 0, "inspect": 1}, rows[-1])
    for i in range(256):
        step({"peek_address": 0xF000 + i}, rows[-1])
    data = TestData(
        "comb",
        "Verified C raycaster: load, execute, inspect",
        (
            Group(
                "complete program",
                tuple(
                    Series(name, width, tuple(format(case[name], f"0{width}b") for case in cases))
                    for name, width in INPUTS.items()
                ),
                tuple(
                    Series(name, width, tuple(format(row[name], f"0{width}b") for row in expected))
                    for name, width in [("result", 32), ("done", 1), ("fault", 1)]
                ),
            ),
        ),
    )
    document = json.loads(Path(path).read_text())
    project.save(project.inject(document, {"rv32_graphics": data}), Path(output))
