"""Render and validate a legacy .cv through the pinned CircuitVerse engine."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from cv_gen.config import DEFAULT_ENGINE_REV
from cv_gen.engine import status

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("project", type=Path)
parser.add_argument("--scope", required=True)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
project = args.project.resolve()
document = json.loads(project.read_text())
if "scopes" not in document:
    parser.error("this renderer requires a legacy .cv file")
engine = status(DEFAULT_ENGINE_REV)
if not engine.ready:
    parser.error("run cv-gen engine install --format legacy first")
root = Path(__file__).resolve().parents[1]
spec_dir = engine.path / "simulator/spec"
shutil.copyfile(root / "tools/render_cv.spec.js", spec_dir / "cv-gen-render.spec.js")
shutil.copyfile(root / "src/cv_gen/verilog/node/schematic.cjs", spec_dir / "cv-gen-schematic.cjs")
output = args.output.resolve()
output.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(
    [
        str(engine.path / "node_modules/.bin/jest"),
        "simulator/spec/cv-gen-render.spec.js",
        "--ci",
        "--silent",
        "--runInBand",
    ],
    cwd=engine.path,
    env={
        **os.environ,
        "CVGEN_PROJECT": str(project),
        "CVGEN_RENDER_SCOPE": args.scope,
        "CVGEN_RENDER": str(output),
    },
    check=True,
)
print(f"Validated native wire reflow; rendered {output}")
