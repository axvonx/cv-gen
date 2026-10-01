"""Fetch pinned DOOM inputs and cross-compile doomgeneric for the RV32I DOOM machine.

Inputs live under build/doom (ignored): doomgeneric at a pinned commit, LLVM
compiler-rt builtins at the tag matching our clang, and the shareware WAD checked
against its published hashes. Outputs go to build/doom/out.
"""

import argparse
import hashlib
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from examples.riscv.compile import tool  # noqa: E402

WORK = ROOT / "build" / "doom"
OUT = WORK / "out"
RUNTIME = HERE / "runtime"
ENGINE = WORK / "doomgeneric" / "doomgeneric"
BUILTINS = WORK / "llvm-project" / "compiler-rt" / "lib" / "builtins"

DOOMGENERIC = (
    "https://github.com/ozkl/doomgeneric.git",
    "dcb7a8dbc7a16ce3dda29382ac9aae9d77d21284",
)
LLVM = ("https://github.com/llvm/llvm-project.git", "llvmorg-23.1.2")
WAD_URL = "https://github.com/Akbar30Bill/DOOM_wads/raw/master/doom1.wad"
# Shareware DOOM v1.9 doom1.wad (4,196,020 bytes): MD5 f0cefca49926d00903cf57551d901abe.
WAD_SHA1 = "5b2e249b9c5133ec987b3ea77596381dc0d6bc1d"
WAD_SHA256 = "1d7d43be501e67d927e415e0b8f3e29c3bf33075e859721816f652a526cac771"

TARGET = ["--target=riscv32-unknown-elf", "-march=rv32i", "-mabi=ilp32"]
DEFINES = ["-DCMAP256", "-DDOOMGENERIC_RESX=320", "-DDOOMGENERIC_RESY=200"]
# Builtins that need an OS, long double or atomics are not used by the engine.
SKIP_BUILTINS = (
    "atomic",
    "clear_cache",
    "emutls",
    "enable_execute_stack",
    "eprintf",
    "gcc_personality",
    "os_version_check",
    "trampoline_setup",
    "cpu_model",
)


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def fetch():
    WORK.mkdir(parents=True, exist_ok=True)
    engine = WORK / "doomgeneric"
    if not engine.exists():
        run(["git", "clone", "-q", DOOMGENERIC[0], str(engine)])
    run(["git", "-C", str(engine), "checkout", "-q", DOOMGENERIC[1]])
    llvm = WORK / "llvm-project"
    if not llvm.exists():
        run(
            [
                "git",
                "clone",
                "-q",
                "--depth",
                "1",
                "--branch",
                LLVM[1],
                "--filter=blob:none",
                "--sparse",
                LLVM[0],
                str(llvm),
            ]
        )
        run(["git", "-C", str(llvm), "sparse-checkout", "set", "compiler-rt/lib/builtins"])
    wad = WORK / "doom1.wad"
    if not wad.exists():
        urllib.request.urlretrieve(WAD_URL, wad)
    data = wad.read_bytes()
    if hashlib.sha1(data).hexdigest() != WAD_SHA1 or hashlib.sha256(data).hexdigest() != WAD_SHA256:
        raise SystemExit(f"{wad} is not shareware DOOM v1.9 doom1.wad")


def engine_sources():
    makefile = (ENGINE / "Makefile").read_text()
    line = next(line for line in makefile.splitlines() if line.startswith("SRC_DOOM"))
    objects = line.split("=", 1)[1].split()
    return [ENGINE / o.replace(".o", ".c") for o in objects if o != "doomgeneric_xlib.o"]


def compile_all(jobs, flags, objdir):
    objdir.mkdir(parents=True, exist_ok=True)

    def one(source):
        target = objdir / (source.stem + ".o")
        if target.exists() and target.stat().st_mtime > source.stat().st_mtime:
            return target
        result = subprocess.run(
            [tool("clang"), *flags, "-c", str(source), "-o", str(target)],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise SystemExit(f"{source.name}:\n{result.stderr}")
        return target

    with ThreadPoolExecutor() as pool:
        return list(pool.map(one, jobs))


def builtins_archive():
    archive = OUT / "libbuiltins.a"
    if archive.exists():
        return archive
    sources = [
        s
        for s in sorted(BUILTINS.glob("*.c"))
        if not any(s.stem.startswith(skip) for skip in SKIP_BUILTINS)
        and "tf" not in s.stem
        and "xf" not in s.stem
    ] + [BUILTINS / "riscv" / "mulsi3.S"]
    objdir = OUT / "builtins"
    objdir.mkdir(parents=True, exist_ok=True)
    flags = [*TARGET, "-O2", "-ffreestanding", "-fno-builtin", "-w", "-c"]

    def one(source):
        target = objdir / (source.name + ".o")
        ok = (
            subprocess.run(
                [tool("clang"), *flags, str(source), "-o", str(target)], capture_output=True
            ).returncode
            == 0
        )
        return target if ok else None

    with ThreadPoolExecutor() as pool:
        objects = [o for o in pool.map(one, sources) if o]
    run([tool("llvm-ar"), "rcs", str(archive), *map(str, objects)])
    return archive


def build(optimize):
    OUT.mkdir(parents=True, exist_ok=True)
    resource = run(
        [tool("clang"), "-print-resource-dir"], capture_output=True, text=True
    ).stdout.strip()
    common = [
        *TARGET,
        optimize,
        "-g",
        "-nostdinc",
        "-isystem",
        f"{resource}/include",
        "-isystem",
        str(RUNTIME / "include"),
        "-I",
        str(RUNTIME),
        "-I",
        str(ENGINE),
        "-msmall-data-limit=0",
        "-fno-stack-protector",
        "-ffunction-sections",
        "-fdata-sections",
        *DEFINES,
    ]
    engine = compile_all(engine_sources(), [*common, "-w"], OUT / "engine")
    runtime = compile_all([RUNTIME / "platform.c"], [*common, "-Wall"], OUT / "runtime")
    runtime += compile_all(
        [RUNTIME / "libc.c"], [*common, "-Wall", "-ffreestanding"], OUT / "runtime"
    )
    start = OUT / "runtime" / "start.o"
    run([tool("clang"), *common, "-c", str(RUNTIME / "start.S"), "-o", str(start)])
    elf = OUT / "doom.elf"
    run(
        [
            tool("clang"),
            *TARGET,
            "-nostdlib",
            "-fuse-ld=lld",
            "-Wl,--no-relax",
            "-Wl,--gc-sections",
            f"-Wl,-T,{RUNTIME / 'link.ld'}",
            f"-Wl,-Map,{OUT / 'doom.map'}",
            str(start),
            *map(str, runtime),
            *map(str, engine),
            str(builtins_archive()),
            "-o",
            str(elf),
        ]
    )
    run([tool("llvm-objcopy"), "-O", "binary", str(elf), str(OUT / "doom.bin")])
    with open(OUT / "doom.syms", "w") as out:
        run([tool("llvm-nm"), "-n", "-S", str(elf)], stdout=out)
    size = run([tool("llvm-size"), "-A", str(elf)], capture_output=True, text=True).stdout
    print(size)
    return elf


def build_host():
    """The same engine and platform code built natively: the frame-hash reference."""
    flags = ["-O2", "-g", "-w", "-DDOOM_HOST", "-I", str(RUNTIME), "-I", str(ENGINE), *DEFINES]
    objects = compile_all([*engine_sources(), RUNTIME / "platform.c"], flags, OUT / "host")
    binary = WORK / "bin" / "doom-host"
    binary.parent.mkdir(parents=True, exist_ok=True)
    run([tool("clang"), *map(str, objects), "-o", str(binary)])
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-O", dest="optimize", default="2", help="optimization level")
    args = parser.parse_args()
    fetch()
    build(f"-O{args.optimize}")
    build_host()


if __name__ == "__main__":
    main()
