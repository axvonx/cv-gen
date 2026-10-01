"""Build the DOOM machine's native tools: the ISS oracle and the Verilator testbench.

uv run python tools/doom/machine.py          # ISS + fast testbench
uv run python tools/doom/machine.py --trace  # also the retire-trace testbench
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from examples.riscv.compile import tool  # noqa: E402

HERE = ROOT / "tools" / "doom"
WORK = ROOT / "build" / "doom"
RUNTIME = ROOT / "examples" / "doom" / "runtime"
RTL = [
    "examples/common/async_ram.v",
    "examples/riscv/rv32_registers.v",
    "examples/riscv/rv32_shift.v",
    "examples/riscv/rv32_alu.v",
    "examples/riscv/rv32_decode.v",
    "examples/riscv/rv32_lanes.v",
    "examples/riscv/rv32_muldiv.v",
    "examples/riscv/rv32_core.v",
    "examples/doom/rv32_doom_memory.v",
    "examples/doom/rv32_doom_bus.v",
    "examples/doom/rv32_doom.v",
]


def build_iss():
    binary = WORK / "bin" / "iss"
    binary.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [tool("clang"), "-O2", "-Wall", "-Wextra", "-Werror", str(HERE / "iss.c"), "-o", binary],
        check=True,
    )
    return binary


def build_testbench(trace=False, structural=False):
    """structural=True keeps the gate-level RV32M bodies CircuitVerse receives."""
    verilator = shutil.which("verilator")
    if not verilator:
        raise SystemExit("Install Verilator 5.052")
    mdir = WORK / ("vtrace" if trace else "vstructural" if structural else "vfast")
    cflags = f"-O3 -I{HERE}" + (" -DTRACE" if trace else "")
    subprocess.run(
        [
            verilator,
            "--cc",
            "--exe",
            "--build",
            "-j",
            "8",
            "-O3",
            "--no-timing",
            "-Wno-fatal",
            "-Wno-COMBDLY",
            "-Wno-LATCH",
            *(["--public-flat-rw"] if trace else []),
            *([] if structural else ["-DRV32_BEHAVIORAL_ARITHMETIC"]),
            "--top-module",
            "rv32_doom",
            "--Mdir",
            str(mdir),
            "-CFLAGS",
            cflags,
            *RTL,
            str(HERE / "tb_doom.cpp"),
            "-o",
            "tb_doom",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return mdir / "tb_doom"


def assemble(source, out, march="rv32im"):
    """Links a directed test program at address 0 with the runtime's linker script."""
    elf = out.with_suffix(".elf")
    subprocess.run(
        [
            tool("clang"),
            "--target=riscv32-unknown-elf",
            f"-march={march}",
            "-mabi=ilp32",
            "-nostdlib",
            "-fuse-ld=lld",
            "-Wl,--no-relax",
            f"-Wl,-T,{RUNTIME / 'link.ld'}",
            "-I",
            str(RUNTIME),
            "-I",
            str(Path(source).parent),
            str(source),
            "-o",
            str(elf),
        ],
        check=True,
    )
    subprocess.run([tool("llvm-objcopy"), "-O", "binary", str(elf), str(out)], check=True)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", action="store_true", help="also build the trace testbench")
    args = parser.parse_args()
    print(build_iss())
    print(build_testbench())
    if args.trace:
        print(build_testbench(trace=True))


if __name__ == "__main__":
    main()
