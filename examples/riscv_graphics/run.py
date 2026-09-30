"""Compare complete C execution and framebuffer with Verilator, and time CircuitVerse."""

import argparse
import json
import os
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from package import tested_project
from reference import FIELDS, reference
from screen import attach

from cv_gen.config import DEFAULT_ENGINE_REV
from cv_gen.engine import status
from cv_gen.verilog import engine as v1_engine
from cv_gen.verilog import load_spec

HERE = Path(__file__).resolve().parent


def png(path, pixels, scale=1):
    def chunk(kind, body):
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    scan = b"".join(
        b"\0"
        + b"".join(
            bytes([value]) * scale
            for value in pixels[(row // scale) * 16 : (row // scale) * 16 + 16]
        )
        for row in range(16 * scale)
    )
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 16 * scale, 16 * scale, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scan))
        + chunk(b"IEND", b"")
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boot", choices=["rom", "ram"], default="rom")
    parser.add_argument("--format", choices=["legacy", "canonical-v1"], default="legacy")
    parser.add_argument("--limit", type=int, default=50000)
    args = parser.parse_args()
    spec = load_spec(
        HERE / ("cvgen-verilog.toml" if args.format == "legacy" else "cvgen-verilog-v1.toml")
    )
    engine = status(DEFAULT_ENGINE_REV)
    if args.format == "legacy" and not engine.ready:
        raise SystemExit("install the legacy CircuitVerse engine first")
    if args.format == "canonical-v1" and not v1_engine.ready():
        raise SystemExit("install the Vue v1 engine first")
    if not 1 <= args.limit <= 250000:
        raise SystemExit("--limit must be in 1..250000")
    if not spec.output.is_file():
        raise SystemExit(f"build {spec.output.name} first")
    attach(spec.output, args.format)
    loads = json.loads((HERE / "build/ram-load.json").read_text()) if args.boot == "ram" else []
    with tempfile.TemporaryDirectory(prefix="rv32-execution-") as tmp:
        scratch = Path(tmp)
        expected = reference(spec, scratch / "reference", loads, args.limit)
        request = scratch / "request.json"
        report = scratch / "report.json"
        request.write_text(
            json.dumps(
                {"project": str(spec.output), "loads": loads, "limit": args.limit, "fields": FIELDS}
            )
        )
        if args.format == "legacy":
            spec_dir = engine.path / "simulator/spec"
            shutil.copyfile(HERE / "run.spec.js", spec_dir / "rv32-execution.spec.js")
            command = [
                str(engine.path / "node_modules/.bin/jest"),
                "simulator/spec/rv32-execution.spec.js",
                "--ci",
                "--silent",
                "--runInBand",
            ]
            cwd = engine.path
        else:
            cwd = v1_engine.directory()
            spec_dir = cwd / "v1/src/simulator/spec"
            shutil.copyfile(HERE / "run-v1.spec.js", spec_dir / "rv32-execution.spec.js")
            command = [
                str(cwd / "node_modules/.bin/vitest"),
                "run",
                "--project",
                "v1",
                "v1/src/simulator/spec/rv32-execution.spec.js",
                "--reporter=dot",
            ]
        shutil.copyfile(HERE / "runtime.cjs", spec_dir / "rv32-runtime.cjs")
        env = {**os.environ, "RV_REQUEST": str(request), "RV_REPORT": str(report)}
        if args.format == "canonical-v1":
            env["NODE_OPTIONS"] = (
                env.get("NODE_OPTIONS", "")
                + f" --localstorage-file={scratch / 'localstorage.json'}"
            )
        subprocess.run(command, cwd=cwd, env=env, check=True)
        actual = json.loads(report.read_text())
    if actual["rows"] != expected["rows"]:
        for ref, cv in zip(expected["rows"], actual["rows"], strict=False):
            for name in ("cycle", *FIELDS):
                if ref[name] != cv[name]:
                    raise SystemExit(
                        f"cycle {ref['cycle']}, {name}: Verilator {ref[name]}, "
                        f"CircuitVerse {cv[name]}"
                    )
        raise SystemExit("execution trace lengths differ")
    golden = list((HERE / "build/expected-frame.bin").read_bytes())
    colors = [v * 0x010101 for v in golden]
    if actual["screen_colors"] != colors:
        raise SystemExit("live screen differs from framebuffer before inspection")
    if expected["pixels"] != golden or actual["pixels"] != golden:
        raise SystemExit("framebuffer differs from native C reference")
    if actual["far_word"] != 0xDEADBEEF or actual["last_word"] != 0x12345678:
        raise SystemExit("high memory or final RAM word is wrong")
    if actual["rows"][-1]["result"] != sum(golden):
        raise SystemExit("wrong framebuffer checksum")
    instructions = 0
    previous = 0
    for row in actual["rows"]:
        instructions += (row["retired"] - previous) & 0xFFFF
        previous = row["retired"]
    seconds = actual["execution_ms"] / 1000
    summary = {
        "format": args.format,
        "boot": args.boot,
        "cycles": len(actual["rows"]),
        "instructions": instructions,
        "execution_seconds": seconds,
        "cycles_per_second": len(actual["rows"]) / seconds,
        "instructions_per_second": instructions / seconds,
        "frame_checksum": sum(golden),
        "load_ms": actual["load_ms"],
        "trace_verified": True,
        "pixels_verified": 256,
        "screen_pixels_verified": 256,
        "timing_scope": (
            "headless native engine; CPU loop plus output sampling, excludes project/loader/export"
        ),
    }
    (HERE / f"build/{args.boot}-{args.format}-benchmark.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    png(HERE / f"build/{args.boot}-frame.png", actual["pixels"])
    png(HERE / f"build/{args.boot}-frame-preview.png", actual["pixels"], 16)
    if args.format == "legacy":
        tested_project(spec.output, loads, actual["rows"], HERE / f"build/{args.boot}-tested.cv")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
