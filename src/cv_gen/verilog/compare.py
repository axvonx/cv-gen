"""Compare sampled Verilator outputs with the pinned CircuitVerse simulator."""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
from pathlib import Path

from cv_gen import engine, project
from cv_gen.testbench import Group, Series, TestData, format_value

from . import BuildError, BuildSpec, _tool

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")


def _stimulus(spec: BuildSpec, inputs: dict[str, int]) -> tuple[list[dict[str, int]], list[int]]:
    cases: list[dict[str, int]] = []
    samples: list[int] = []
    current = dict.fromkeys(inputs, 0)
    for scenario in spec.scenarios:
        current = dict.fromkeys(inputs, 0)
        for step in (*scenario.setup, *scenario.steps):
            if set(step.inputs) - set(inputs):
                raise BuildError(
                    f"{scenario.name}: unknown inputs {sorted(set(step.inputs) - set(inputs))}"
                )
            for name, value in step.inputs.items():
                if type(value) is not int or not 0 <= value < (1 << inputs[name]):
                    raise BuildError(
                        f"{scenario.name}: {name} is outside its {inputs[name]}-bit range"
                    )
            current.update(step.inputs)
            cases.append(current.copy())
            if step.sample:
                samples.append(len(cases) - 1)
    if spec.cases:
        if spec.clocks:
            raise BuildError("generated cases cover combinational designs only")
        rng = random.Random(spec.seed)
        for _ in range(spec.cases):
            cases.append({name: rng.randrange(1 << width) for name, width in inputs.items()})
            samples.append(len(cases) - 1)
    if not samples:
        raise BuildError("check requires at least one sampled step or generated case")
    return cases, samples


def _verilator(
    spec: BuildSpec,
    inputs: dict[str, int],
    outputs: dict[str, int],
    cases: list[dict[str, int]],
    scratch: Path,
) -> list[dict[str, str]]:
    _tool("verilator")
    for name in (*inputs, *outputs):
        if not _IDENTIFIER.fullmatch(name):
            raise BuildError(f"Verilator testbench cannot address port {name!r}")
    lines = ["module cvgen_tb;"]
    for name, width in {**inputs, **outputs}.items():
        lines.append(f"  logic [{width - 1}:0] {name};")
    params = (
        " #(" + ", ".join(f".{name}({value})" for name, value in spec.parameters.items()) + ")"
        if spec.parameters
        else ""
    )
    ports = ", ".join(f".{name}({name})" for name in (*inputs, *outputs))
    lines.append(f"  {spec.top}{params} dut ({ports});")
    lines.append("  initial begin")
    for case in cases:
        for name, value in case.items():
            lines.append(f"    {name} = {inputs[name]}'d{value};")
        lines.append("    #1;")
        lines.append(
            '    $display("@CV '
            + " ".join("%b" for _ in outputs)
            + '", '
            + ", ".join(outputs)
            + ");"
        )
    lines.extend(["    $finish;", "  end", "endmodule"])
    tb = scratch / "cvgen_tb.sv"
    tb.write_text("\n".join(lines) + "\n")
    obj = scratch / "obj"
    cmd = [
        "verilator",
        "--binary",
        "--timing",
        "-Wno-fatal",
        "--top-module",
        "cvgen_tb",
        "--Mdir",
        str(obj),
    ]
    cmd += [f"-I{p}" for p in spec.includes]
    cmd += [f"-D{k}={v}" for k, v in spec.defines.items()]
    cmd += [str(p) for p in spec.sources] + [str(tb)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode:
        raise BuildError("Verilator compile failed:\n" + (result.stderr or result.stdout)[-4000:])
    run = subprocess.run([str(obj / "Vcvgen_tb")], capture_output=True, text=True)
    if run.returncode:
        raise BuildError("Verilator run failed:\n" + (run.stderr or run.stdout)[-4000:])
    rows = [line.split()[1:] for line in run.stdout.splitlines() if line.startswith("@CV ")]
    if len(rows) != len(cases):
        raise BuildError(f"Verilator emitted {len(rows)} rows for {len(cases)} input steps")
    return [dict(zip(outputs, row, strict=True)) for row in rows]


def compare(spec: BuildSpec, document: dict, scratch: Path) -> int:
    if spec.format == "legacy":
        top = project.find_scope(document, spec.top)
        inputs = {p.label: p.width for p in top.inputs}
        outputs = {p.label: p.width for p in top.outputs}
    else:
        top = next(
            (c for c in document["circuits"].values() if c["projectMetadata"]["name"] == spec.top),
            None,
        )
        if top is None:
            raise BuildError(f"canonical project lost top {spec.top}")

        def ports(kind: str) -> dict[str, int]:
            return {
                c["label"]: c["properties"]["constructorParamaters"][1]
                for c in top["netlist"]["components"]
                if c["type"] == kind
            }

        inputs, outputs = ports("Input"), ports("Output")
    if not inputs or not outputs:
        raise BuildError("top must have inputs and outputs for behavioral checking")
    cases, sampled = _stimulus(spec, inputs)
    reference = _verilator(spec, inputs, outputs, cases, scratch)
    if spec.format == "canonical-v1":
        actual = _canonical_results(spec, document, cases, scratch)
    else:
        actual = _legacy_results(spec, document, cases, scratch, inputs, outputs)
    for i in sampled:
        for name, width in outputs.items():
            got = actual[name][i]
            expected = reference[i][name].lower().zfill(width)
            if not re.fullmatch(r"[01]+", got) or len(got) != width:
                raise BuildError(f"step {i}, {name}: CircuitVerse returned invalid value {got!r}")
            if not re.fullmatch(r"[01]+", expected) or len(expected) != width:
                raise BuildError(f"step {i}, {name}: Verilator returned invalid value {expected!r}")
            if got != expected:
                raise BuildError(f"step {i}, {name}: Verilator {expected}, CircuitVerse {got}")
    return len(sampled)


def _legacy_results(spec, document, cases, scratch, inputs, outputs):
    data = TestData(
        "comb",
        "Verilator comparison",
        (
            Group(
                "steps",
                tuple(
                    Series(name, width, tuple(format_value(case[name], width) for case in cases))
                    for name, width in inputs.items()
                ),
                tuple(
                    Series(name, width, tuple("0" * width for _ in cases))
                    for name, width in outputs.items()
                ),
            ),
        ),
    )
    checked = project.inject(document, {spec.top: data})
    path = scratch / "check.cv"
    project.save(checked, path)
    raw = engine.run(
        "6f725c5a924dc0b73527215eb5aa0618e45330e1", path, only=[spec.top], results_for=[spec.top]
    )
    found = next((s for s in raw["scopes"] if s["scope"] == spec.top), None)
    if not found or found["status"] in {"crash", "engine-error"}:
        raise BuildError(f"CircuitVerse simulation failed: {found}")
    return found["results"][0]


def smoke_legacy(spec: BuildSpec, document: dict, scratch: Path) -> None:
    """Exercise imported devices once so native width errors block publication."""
    top = project.find_scope(document, spec.top)
    inputs = {p.label: p.width for p in top.inputs}
    outputs = {p.label: p.width for p in top.outputs}
    if outputs:
        cases = [
            dict.fromkeys(inputs, 0),
            {name: (1 << width) - 1 for name, width in inputs.items()},
        ]
        _legacy_results(spec, document, cases, scratch, inputs, outputs)


def _canonical_results(spec, document, cases, scratch):
    from . import V1_REV

    engine = Path(os.environ.get("CVGEN_V1_DIR", Path.home() / ".cache" / "cv-gen" / "v1" / V1_REV))
    vitest = engine / "node_modules" / ".bin" / "vitest"
    if not vitest.is_file():
        raise BuildError(f"Vue v1 engine missing at {engine}; run cv-gen engine install")
    runner = engine / "v1" / "src" / "simulator" / "spec" / "cv-gen-run.spec.js"
    shutil.copyfile(Path(__file__).parent / "node" / "canonical-run.spec.js", runner)
    cv = scratch / "canonical.cv"
    cv.write_text(json.dumps(document))
    request = scratch / "cases.json"
    request.write_text(json.dumps({"top": spec.top, "cases": cases}))
    report = scratch / "report.json"
    env = {
        **os.environ,
        "CVGEN_PROJECT": str(cv),
        "CVGEN_CASES": str(request),
        "CVGEN_REPORT": str(report),
    }
    node_version = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout
    if int(node_version.strip().lstrip("v").split(".")[0]) >= 25:
        env["NODE_OPTIONS"] = (
            env.get("NODE_OPTIONS", "") + f" --localstorage-file={scratch / 'localstorage.json'}"
        ).strip()
    result = subprocess.run(
        [
            str(vitest),
            "run",
            "--project",
            "v1",
            "v1/src/simulator/spec/cv-gen-run.spec.js",
            "--reporter=dot",
        ],
        cwd=engine,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode or not report.is_file():
        raise BuildError(
            "canonical simulator failed:\n"
            + "\n".join((result.stderr + result.stdout).splitlines()[-35:])
        )
    data = json.loads(report.read_text())
    if data["error"]:
        raise BuildError("canonical simulator reported an engine error")
    return data["outputs"]
