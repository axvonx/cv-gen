"""Reproducible opt-in packages for the two generated graphics profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from cv_gen.verilog import BuildError, load_spec

from .model import native_runner, wrapper

ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).parent
SDK = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "cv-gen/emsdk-6.0.10"
ABI = 1
WARNINGS = {"WIDTH", "WIDTHEXPAND", "WIDTHTRUNC", "LATCH", "COMBDLY", "UNOPTFLAT"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise BuildError(f"{args[0]} failed:\n{result.stderr[-12000:]}\n{result.stdout[-2000:]}")
    return result


def check_warnings(text):
    codes = set(re.findall(r"%Warning-([A-Z0-9_]+):", text))
    if unknown := codes - WARNINGS:
        raise BuildError(f"unreviewed Verilator warnings: {sorted(unknown)}\n{text[-6000:]}")
    return sorted(codes)


def toolchain():
    verilator = shutil.which("verilator")
    emcc = shutil.which("emcc") or str(SDK / "upstream/emscripten/emcc")
    emxx = shutil.which("em++") or str(SDK / "upstream/emscripten/em++")
    if not verilator or not Path(emcc).is_file():
        raise BuildError("install Verilator 5.052 and activate Emscripten SDK 6.0.10")
    versions = {
        "verilator": run([verilator, "--version"]).stdout.strip(),
        "emscripten": run([emcc, "--version"]).stdout.splitlines()[0],
    }
    if "5.052" not in versions["verilator"] or "6.0.10" not in versions["emscripten"]:
        raise BuildError(f"toolchain version mismatch: {versions}")
    return verilator, emxx, versions


def arguments(spec):
    return [
        *[f"-I{p}" for p in spec.includes],
        *[f"-D{k}={v}" for k, v in spec.defines.items()],
        *[f"-G{k}={v}" for k, v in spec.parameters.items()],
        *map(str, spec.sources),
    ]


def inspect_hdl(spec, directory, verilator):
    preprocessed = run([verilator, "-E", *arguments(spec)], cwd=ROOT).stdout
    dependencies = set(spec.sources)
    dependencies.update(Path(p).resolve() for p in re.findall(r'`line \d+ "([^"]+)"', preprocessed))
    clean = re.sub(r"/\*.*?\*/|//[^\n]*", "", preprocessed, flags=re.S)
    if re.search(r"\$random|\$urandom|\b(inout|real|realtime)\b|#\s*\d", clean):
        raise BuildError("unsupported random/four-state/inout/real/delay-dependent hardware")
    if re.search(r"\b(casex|casez|tri)\b|\d*'[sS]?[bBhHdD][0-9a-fA-F_]*[xXzZ]", clean):
        raise BuildError("four-state/tri-state HDL is unsupported")
    memories = []
    for name in re.findall(r'\$readmem[hb]\s*\(\s*"([^"]+)"', clean):
        target = Path(name)
        if target.is_absolute() or ".." in target.parts:
            raise BuildError("memory initialization paths must be relative without '..'")
        source = ROOT / target
        if not source.is_file():
            raise BuildError(f"missing memory initialization file: {name}")
        dependencies.add(source)
        memories.append((source, name))
    if len(re.findall(r"\$readmem[hb]\s*\(", clean)) != len(memories):
        raise BuildError("dynamic memory initialization filenames are unsupported")
    script = []
    for source in spec.sources:
        options = " ".join(
            [*[f'-I"{p}"' for p in spec.includes], *[f"-D{k}={v}" for k, v in spec.defines.items()]]
        )
        script.append(
            f'read_verilog {"-sv" if source.suffix == ".sv" else ""} {options} "{source}"'
        )
    params = " ".join(f"-chparam {k} {v}" for k, v in spec.parameters.items())
    script.extend(
        [
            f"hierarchy -top {spec.top} {params}",
            "proc",
            "opt",
            "memory -nomap",
            f'write_json "{directory / "netlist.json"}"',
        ]
    )
    (directory / "netlist.ys").write_text("\n".join(script))
    run(["yosys", "-Q", "-q", "-s", str(directory / "netlist.ys")], cwd=ROOT)
    netlist = json.loads((directory / "netlist.json").read_text())
    ports = []
    for name, port in netlist["modules"][spec.top]["ports"].items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise BuildError(f"unsupported port name: {name}")
        if port["direction"] not in {"input", "output"} or not 1 <= len(port["bits"]) <= 32:
            raise BuildError(f"unsupported port: {name}")
        ports.append({"name": name, "direction": port["direction"], "width": len(port["bits"])})
    return ports, sorted(dependencies), sorted(set(memories))


def bindings(document, ports, profile, top):
    demos = [s for s in document["scopes"] if s["name"] == "Demo"]
    tops = [s for s in document["scopes"] if s["name"] == top]
    if len(demos) != 1 or len(tops) != 1:
        raise BuildError("package requires unique Demo and RTL top scopes")
    demo = demos[0]
    clock = demo.get("Clock", [])
    if len(clock) != 1 or clock[0]["label"] != "clk":
        raise BuildError("Demo must have exactly one clock named clk")
    if len(demo.get("RGBLedMatrix", [])) != 1:
        raise BuildError("Demo must have exactly one RGBLedMatrix")
    matrix = demo["RGBLedMatrix"][0]
    options = matrix["customData"]["constructorParamaters"][0]
    size = options["rows"]
    if options["columns"] != size or size not in {16, 64}:
        raise BuildError("only square 16/64 displays are supported")
    if profile == "rv32-graphics" and (top != "rv32_graphics" or size != 16):
        raise BuildError("rv32-graphics requires the 16x16 rv32_graphics project")
    if profile == "rom-playback" and top != "camera_animation":
        raise BuildError("rom-playback requires camera_animation RTL")
    required = {"screen_write", "screen_address", "screen_data", "screen_mask", "result", "fault"}
    if profile == "rom-playback":
        required = {"row_index", "frame", *[f"color_{i}" for i in range(size)]}
    if not required <= {p["name"] for p in ports if p["direction"] == "output"}:
        raise BuildError("missing profile outputs")
    for port in ports:
        if port["name"] == "clk":
            if port != {"name": "clk", "width": 1, "direction": "input"}:
                raise BuildError("invalid clock port")
            port.update(
                initial=0,
                binding={
                    "kind": "Clock",
                    "index": 0,
                    "label": "clk",
                    "node": clock[0]["customData"]["nodes"]["output1"],
                },
            )
            continue
        kind = "Input" if port["direction"] == "input" else "Output"
        matches = [(i, p) for i, p in enumerate(demo.get(kind, [])) if p["label"] == port["name"]]
        if len(matches) != 1:
            raise BuildError(f"missing/ambiguous {kind} binding {port['name']}")
        index, component = matches[0]
        data = component["customData"]
        if data["constructorParamaters"][1] != port["width"]:
            raise BuildError(f"binding width mismatch: {port['name']}")
        port["binding"] = {
            "kind": kind,
            "index": index,
            "label": port["name"],
            "node": data["nodes"]["output1" if kind == "Input" else "inp1"],
        }
        if kind == "Input":
            port["initial"] = data.get("values", {}).get("state", 0)
            if type(port["initial"]) is not int or not 0 <= port["initial"] < 1 << port["width"]:
                raise BuildError(f"invalid initial input value: {port['name']}")
    return {
        "scopeId": demo["id"],
        "scopeName": "Demo",
        "matrixIndex": 0,
        "matrixLabel": matrix["label"],
        "size": size,
    }


def build(spec_path, project_path, profile, output):
    spec = load_spec(spec_path)
    project_path, output = Path(project_path).resolve(), Path(output).resolve()
    if spec.format != "legacy" or spec.clocks != ("clk",):
        raise BuildError("fastpath requires legacy format and a single clk")
    if output.exists() and any(output.iterdir()):
        raise BuildError("output directory must be empty (use a new build directory)")
    verilator, emxx, versions = toolchain()
    with tempfile.TemporaryDirectory(
        prefix="fastpath-", dir=output.parent if output.parent.exists() else None
    ) as temporary:
        scratch = Path(temporary)
        ports, dependencies, memories = inspect_hdl(spec, scratch, verilator)
        project_bytes = project_path.read_bytes()
        display = bindings(json.loads(project_bytes), ports, profile, spec.top)
        manifest = {
            "abi": ABI,
            "profile": profile,
            "top": spec.top,
            "clock": "clk",
            "ports": ports,
            "display": display,
            "projectSha256": digest(project_bytes),
            "toolchain": versions,
            "defines": spec.defines,
            "parameters": spec.parameters,
            "dependencies": [
                {
                    "path": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else p.name,
                    "sha256": digest(p.read_bytes()),
                }
                for p in dependencies
            ],
            "boot": "reset-low-high-low-run"
            if profile == "rv32-graphics"
            else "initialized-clock-low",
            "validation": {"status": "unverified"},
        }
        obj = scratch / "obj"
        result = run(
            [
                verilator,
                "--cc",
                "--no-timing",
                "--threads",
                "1",
                "-O3",
                "-Wno-fatal",
                "--top-module",
                spec.top,
                "--prefix",
                "Vmodel",
                "--Mdir",
                str(obj),
                *arguments(spec),
            ],
            cwd=ROOT,
        )
        manifest["warnings"] = check_warnings(result.stderr)
        (scratch / "wrapper.cpp").write_text(wrapper(manifest))
        manifest["wrapperSha256"] = digest((scratch / "wrapper.cpp").read_bytes())
        (scratch / "native.cpp").write_text(native_runner(manifest))
        vroot = Path(run([verilator, "--getenv", "VERILATOR_ROOT"]).stdout.strip())
        sources = [
            *map(str, sorted(obj.glob("Vmodel*.cpp"))),
            str(scratch / "wrapper.cpp"),
            str(vroot / "include/verilated.cpp"),
            str(vroot / "include/verilated_threads.cpp"),
        ]
        common = [
            "-O3",
            "-std=c++17",
            "-DVL_TIME_CONTEXT",
            f"-I{obj}",
            f"-I{vroot / 'include'}",
            f"-I{vroot / 'include/vltstd'}",
            *sources,
        ]
        run(["clang++", *common, str(scratch / "native.cpp"), "-o", str(scratch / "native-model")])
        exports = [
            "_fp_" + n
            for n in [
                "create",
                "reset",
                "apply_inputs",
                "advance",
                "snapshot",
                "outputs",
                "pixels",
                "frames",
                "frame_times",
                "error",
                "destroy",
            ]
        ] + ["_malloc", "_free"]
        flags = [
            "-sMODULARIZE=1",
            "-sEXPORT_ES6=1",
            "-sENVIRONMENT=worker,node",
            "-sALLOW_MEMORY_GROWTH=1",
            "-sINITIAL_MEMORY=33554432",
            "-sSTACK_SIZE=1048576",
            "-sDISABLE_EXCEPTION_CATCHING=0",
            "-sEXPORTED_FUNCTIONS=" + json.dumps(exports),
            '-sEXPORTED_RUNTIME_METHODS=["UTF8ToString","HEAPU32","HEAPF64"]',
        ]
        for source, name in memories:
            flags.extend(["--preload-file", f"{source}@/{name}"])
        run(
            [
                emxx,
                "-include",
                str(ASSETS / "wasm-host.h"),
                *common,
                *flags,
                "-o",
                str(scratch / "model.mjs"),
            ],
            cwd=ROOT,
        )
        manifest["flags"] = {
            "verilator": ["--cc", "--no-timing", "--threads", "1", "-O3"],
            "emscripten": flags,
        }
        manifest["modelId"] = digest(json.dumps(manifest, sort_keys=True).encode())
        output.mkdir(parents=True, exist_ok=True)
        for name in ["model.mjs", "model.wasm", "model.data", "native-model"]:
            if (scratch / name).exists():
                shutil.copy2(scratch / name, output / name)
        for name in ["worker.mjs", "runtime.mjs", "controller.mjs"]:
            shutil.copyfile(ASSETS / name, output / name)
        (output / "project.cv").write_bytes(project_bytes)
        manifest["assets"] = {
            p.name: digest(p.read_bytes())
            for p in output.iterdir()
            if p.is_file() and p.name != "native-model"
        }
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--profile", choices=["rv32-graphics", "rom-playback"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build(args.spec, args.project, args.profile, args.out)
    except (BuildError, OSError, KeyError) as error:
        parser.exit(1, f"fastpath: {error}\n")
    print(
        json.dumps(
            {
                "package": str(args.out),
                "modelId": manifest["modelId"],
                "validation": manifest["validation"],
            }
        )
    )
