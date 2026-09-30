"""Attach a native live framebuffer matrix and validate its save/load round trip."""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from cv_gen.config import DEFAULT_ENGINE_REV
from cv_gen.engine import status
from cv_gen.verilog import engine as v1_engine

HERE = Path(__file__).resolve().parent


def attach(path, format_="legacy"):
    path = Path(path).resolve()
    root = Path(__file__).resolve().parents[2]
    if format_ == "legacy":
        cwd = status(DEFAULT_ENGINE_REV).path
        directory = cwd / "simulator/spec"
        runner = "screen.spec.js"
        command = [
            str(cwd / "node_modules/.bin/jest"),
            "simulator/spec/rv32-screen.spec.js",
            "--ci",
            "--silent",
            "--runInBand",
        ]
    else:
        cwd = v1_engine.directory()
        directory = cwd / "v1/src/simulator/spec"
        runner = "screen-v1.spec.js"
        command = [
            str(cwd / "node_modules/.bin/vitest"),
            "run",
            "--project",
            "v1",
            "v1/src/simulator/spec/rv32-screen.spec.js",
            "--reporter=dot",
        ]
    shutil.copyfile(HERE / runner, directory / "rv32-screen.spec.js")
    shutil.copyfile(HERE / "screen.cjs", directory / "rv32-screen.cjs")
    shutil.copyfile(
        root / "src/cv_gen/verilog/node/schematic.cjs", directory / "cv-gen-schematic.cjs"
    )
    with tempfile.TemporaryDirectory(prefix="rv32-screen-", dir=path.parent) as tmp:
        output = Path(tmp) / "screen.cv"
        env = {**os.environ, "RV_SCREEN_INPUT": str(path), "RV_SCREEN_OUTPUT": str(output)}
        if format_ != "legacy":
            env["NODE_OPTIONS"] = (
                env.get("NODE_OPTIONS", "") + f" --localstorage-file={tmp}/localstorage"
            )
        subprocess.run(command, cwd=cwd, env=env, check=True)
        os.replace(output, path)
    print(f"Added live screen: {path}")


def verify_demo(path, svg):
    """Run the published testbench and draw its actual native matrix."""
    cwd = status(DEFAULT_ENGINE_REV).path
    shutil.copyfile(
        HERE / "screen-runall.spec.js", cwd / "simulator/spec/rv32-screen-runall.spec.js"
    )
    report = Path(svg).with_suffix(".json").resolve()
    subprocess.run(
        [
            str(cwd / "node_modules/.bin/jest"),
            "simulator/spec/rv32-screen-runall.spec.js",
            "--ci",
            "--silent",
            "--runInBand",
        ],
        cwd=cwd,
        env={
            **os.environ,
            "RV_SCREEN_INPUT": str(Path(path).resolve()),
            "RV_SCREEN_EXPECTED": str(HERE / "build/expected-frame.bin"),
            "RV_SCREEN_SVG": str(Path(svg).resolve()),
            "RV_SCREEN_REPORT": str(report),
        },
        check=True,
    )
    print(report.read_text())
    return json.loads(report.read_text())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--format", choices=["legacy", "canonical-v1"], default="legacy")
    parser.add_argument("--verify-demo", type=Path, metavar="SVG")
    args = parser.parse_args()
    if args.verify_demo:
        if args.format != "legacy":
            parser.error("--verify-demo requires a legacy project with an embedded testbench")
        verify_demo(args.project, args.verify_demo)
    else:
        attach(args.project, args.format)
