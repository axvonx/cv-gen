"""Build an automatically clocked ROM animation for the default CircuitVerse simulator."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from compile import tool
from screen import attach

from cv_gen.config import DEFAULT_ENGINE_REV
from cv_gen.engine import status
from cv_gen.verilog import build, load_spec

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, choices=[16, 64], default=16)
    parser.add_argument("--playback-only", action="store_true")
    args = parser.parse_args()
    if args.size == 64 or args.playback_only:
        directory = HERE / f"build/animation-{args.size}"
        directory.mkdir(parents=True, exist_ok=True)
        host = directory / "host-raycaster"
        subprocess.run(
            [
                tool("clang"),
                "-DHOST",
                "-DANIMATE",
                f"-DSCREEN={args.size}",
                "-O2",
                str(HERE / "main.c"),
                "-o",
                str(host),
            ],
            check=True,
        )
        (directory / "expected-frame.bin").write_bytes(subprocess.check_output([str(host)]))
        playback(directory, args.size)
        return
    subprocess.run([sys.executable, str(HERE / "compile.py"), "--animate"], check=True)
    directory = HERE / "build/animation"
    spec = load_spec(directory / "cvgen-verilog.toml")
    build(spec)
    attach(spec.output)
    engine = status(DEFAULT_ENGINE_REV).path
    shutil.copyfile(HERE / "animation.spec.js", engine / "simulator/spec/rv32-animation.spec.js")
    # Publish only after the saved project reloads and completes two distinct frames.
    with tempfile.TemporaryDirectory(prefix="passive-", dir=directory) as temporary:
        candidate = Path(temporary) / "animation.cv"
        report = Path(temporary) / "report.json"
        subprocess.run(
            [
                str(engine / "node_modules/.bin/jest"),
                "simulator/spec/rv32-animation.spec.js",
                "--ci",
                "--silent",
                "--runInBand",
            ],
            cwd=engine,
            env={
                **os.environ,
                "RV_ANIMATION_INPUT": str(spec.output),
                "RV_ANIMATION_OUTPUT": str(candidate),
                "RV_ANIMATION_REPORT": str(report),
                "RV_ANIMATION_EXPECTED": str(directory / "expected-frame.bin"),
            },
            check=True,
        )
        result = json.loads(report.read_text())
        os.replace(candidate, HERE / "build/cpu-animation.cv")
        os.replace(report, directory / "verification.json")
    print(json.dumps(result, indent=2))
    playback(directory)
    print(f"Open {HERE / 'build/animation.cv'} for passive playback.")
    print("cpu-animation.cv runs the CPU renderer continuously.")


def column_profiles(pixels, size):
    """Losslessly encode this renderer's ceiling/wall/floor columns."""
    if len(pixels) != 32 * size * size:
        raise ValueError("expected 32 complete frames")
    profiles = []
    for column in range(size):
        frames = []
        for frame in range(32):
            values = [pixels[frame * size * size + row * size + column] for row in range(size)]
            top = next((i for i, value in enumerate(values) if value != 24), size)
            bottom = next((i for i in range(top, size) if values[i] == 8), size)
            shade = values[top] if top < size else 0
            decoded = [24 if row < top else 8 if row >= bottom else shade for row in range(size)]
            if decoded != values:
                raise ValueError(f"frame {frame}, column {column}: unsupported column profile")
            frames.append((top, bottom, shade))
        profiles.append(frames)
    return profiles


def playback(directory, size=16):
    """A native ROM scanout avoids the public simulator's slow CPU clock ceiling."""
    pixels = (directory / "expected-frame.bin").read_bytes()
    profiles = column_profiles(pixels, size)
    row_bits = (size - 1).bit_length()
    ports = ",".join(f"output [23:0] color_{column}" for column in range(size))
    lines = [
        f"module camera_animation(input clk,rst,output [{row_bits - 1}:0] row_index,"
        f"output [4:0] frame,{ports});",
        f"reg [{row_bits + 4}:0] cursor;always @(posedge clk or posedge rst) "
        "if(rst)cursor<=0;else cursor<=cursor+1;",
        f"assign frame=cursor[{row_bits + 4}:{row_bits}];"
        f"assign row_index=cursor[{row_bits - 1}:0];",
    ]
    for column in range(size):
        lines += [
            f"wire [7:0] gray_{column};",
            f"camera_column_{column} c{column}(frame,row_index,gray_{column});",
            f"assign color_{column}={{gray_{column},gray_{column},gray_{column}}};",
        ]
    lines.append("endmodule")
    for column in range(size):
        lines += [
            f"module camera_column_{column}(input [4:0] frame,"
            f"input [{row_bits - 1}:0] row_index,output [7:0] data);",
        ]
        for field in ("top", "bottom", "shade"):
            lines += [
                f"wire [7:0] {field},{field}_0,{field}_1;",
                f"assign {field}=frame[4]?{field}_1:{field}_0;",
            ]
            for bank in range(2):
                lines += [
                    f"camera_profile_{column}_{field}_{bank} "
                    f"p_{field}_{bank}(frame[3:0],{field}_{bank});"
                ]
        lines += ["assign data=row_index<top?8'd24:row_index>=bottom?8'd8:shade;endmodule"]
        # Each native ROM is sixteen bytes; three fields need six banks per column.
        for field_index, field in enumerate(("top", "bottom", "shade")):
            for bank in range(2):
                lines += [
                    f"module camera_profile_{column}_{field}_{bank}(input [3:0] address,"
                    "output [7:0] data);reg [7:0] cells[0:15];initial begin"
                ]
                lines += [
                    f"cells[{i}]=8'h{profiles[column][bank * 16 + i][field_index]:02x};"
                    for i in range(16)
                ]
                lines += ["end assign data=cells[address];endmodule"]
    source = directory / "camera_animation.v"
    source.write_text("\n".join(lines) + "\n")
    manifest = directory / "playback.toml"
    manifest.write_text(
        '[verilog]\nsources=["camera_animation.v"]\ntop="camera_animation"\n'
        'clocks=["clk"]\nformat="legacy"\noutput="playback.cv"\n'
    )
    spec = load_spec(manifest)
    build(spec)
    engine = status(DEFAULT_ENGINE_REV).path
    shutil.copyfile(HERE / "playback.spec.js", engine / "simulator/spec/rv32-playback.spec.js")
    shutil.copyfile(
        HERE.parents[1] / "src/cv_gen/verilog/node/schematic.cjs",
        engine / "simulator/spec/cv-gen-schematic.cjs",
    )
    with tempfile.TemporaryDirectory(prefix="playback-", dir=directory) as temporary:
        output = Path(temporary) / "animation.cv"
        subprocess.run(
            [
                str(engine / "node_modules/.bin/jest"),
                "simulator/spec/rv32-playback.spec.js",
                "--ci",
                "--silent",
                "--runInBand",
            ],
            cwd=engine,
            env={
                **os.environ,
                "RV_ANIMATION_INPUT": str(spec.output),
                "RV_ANIMATION_OUTPUT": str(output),
                "RV_ANIMATION_EXPECTED": str(directory / "expected-frame.bin"),
                "RV_ANIMATION_SIZE": str(size),
                "RV_ANIMATION_REPORT": str(directory / "playback-verification.json"),
            },
            check=True,
        )
        target = HERE / ("build/animation.cv" if size == 16 else "build/animation-64.cv")
        os.replace(output, target)
    print(f"Built {target}; nominal frame period {size * 0.1:.1f} seconds.")


if __name__ == "__main__":
    main()
