"""Build persistent-ROM and RAM-loadable copies of the grayscale C raycaster."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from examples.riscv.compile import mux, tool  # noqa: E402


def linker(base):
    return f"""ENTRY(_start)
MEMORY {{ CODE (rx) : ORIGIN = {base}, LENGTH = 16K
          DATA (rw) : ORIGIN = 0x8000, LENGTH = 24K }}
SECTIONS {{
 .text : {{ KEEP(*(.text.start)) *(.text*) *(.rodata*) }} > CODE
 .data : ALIGN(4) {{ __data_start = .; *(.data*) *(.sdata*) __data_end = .; }} > DATA AT> CODE
 __data_load = LOADADDR(.data);
 .bss (NOLOAD) : ALIGN(4) {{ __bss_start = .; *(.bss*) *(.sbss*) *(COMMON) __bss_end = .; }} > DATA
 /DISCARD/ : {{ *(.comment) *(.riscv.attributes) *(.eh_frame*) }}
}}
ASSERT(__bss_end<=0xd000,"reserve stack space below 0xe000")
"""


def generate_rom(image, destination=None):
    banks = (len(image) + 63) // 64
    padded = image.ljust(banks * 64, b"\0")
    lines = ["// Generated from main.c by compile.py."]
    for bank in range(banks):
        for lane in range(4):
            lines += [
                f"module graphics_rom_{bank}_{lane}(input [3:0] address,output [7:0] data);",
                "reg [7:0] cells[0:15];initial begin",
            ]
            lines += [f"cells[{n}]=8'h{padded[bank * 64 + n * 4 + lane]:02x};" for n in range(16)]
            lines += ["end assign data=cells[address];endmodule"]
    lines += ["module rv32_graphics_rom(input [11:0] address,output [31:0] data);"]
    for bank in range(banks):
        lines += [f"wire [31:0] bank_{bank};"]
        for lane in range(4):
            lines += [
                f"graphics_rom_{bank}_{lane} r_{bank}_{lane}(address[3:0],"
                f"bank_{bank}[{lane * 8}+:8]);"
            ]
    count = 1 << (banks - 1).bit_length()
    values = [f"bank_{i}" if i < banks else "32'b0" for i in range(count)]
    lines += [
        "wire [7:0] selector=address[11:4];",
        f"assign data=selector<{banks} ? {mux(values, 'selector')} : 32'b0;endmodule",
    ]
    (destination or HERE / "rv32_graphics_rom.v").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--animate", action="store_true", help="build the continuous camera sweep")
    args = parser.parse_args()
    out = HERE / "build"
    if args.animate:
        out /= "animation"
    out.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for name, base in [("rom", 0), ("ram", 0x4000)]:
        ld = out / f"{name}.ld"
        ld.write_text(linker(base))
        subprocess.run(
            [
                tool("clang"),
                "--target=riscv32-unknown-elf",
                "-march=rv32i",
                "-mabi=ilp32",
                "-Os",
                *(["-DANIMATE"] if args.animate else []),
                "-msmall-data-limit=0",
                "-ffreestanding",
                "-fno-builtin",
                "-fno-stack-protector",
                "-nostdlib",
                "-fuse-ld=lld",
                "-Wl,--no-relax",
                f"-Wl,-T,{ld}",
                str(HERE / "start.S"),
                str(HERE / "main.c"),
                "-o",
                str(out / f"{name}.elf"),
            ],
            check=True,
        )
        subprocess.run(
            [
                tool("llvm-objcopy"),
                "-O",
                "binary",
                str(out / f"{name}.elf"),
                str(out / f"{name}.bin"),
            ],
            check=True,
        )
        image = (out / f"{name}.bin").read_bytes()
        if not image or len(image) > 16384:
            raise SystemExit("program exceeds its 16 KiB code window")
        sizes[name] = len(image)
        (out / f"{name}.disasm").write_text(
            subprocess.check_output(
                [tool("llvm-objdump"), "-d", str(out / f"{name}.elf")], text=True
            )
        )
        if name == "rom":
            generate_rom(image, out / "rv32_graphics_rom.v" if args.animate else None)
        else:
            padded = image.ljust((len(image) + 3) // 4 * 4, b"\0")
            (out / "ram-load.json").write_text(
                json.dumps(
                    [
                        {"address": base + i, "data": int.from_bytes(padded[i : i + 4], "little")}
                        for i in range(0, len(padded), 4)
                    ],
                    indent=2,
                )
                + "\n"
            )
    host = out / "host-raycaster"
    subprocess.run(
        [
            tool("clang"),
            "-DHOST",
            *(["-DANIMATE"] if args.animate else []),
            "-O2",
            str(HERE / "main.c"),
            "-o",
            str(host),
        ],
        check=True,
    )
    pixels = subprocess.check_output([str(host)])
    assert len(pixels) == (8192 if args.animate else 256)
    (out / "expected-frame.bin").write_bytes(pixels)
    sources = ["../common/async_ram.v"] + [
        f"../riscv/{n}.v"
        for n in (
            "rv32_registers",
            "rv32_shift",
            "rv32_alu",
            "rv32_decode",
            "rv32_lanes",
            "rv32_core",
        )
    ]
    sources += [
        f"{n}.v" for n in ("rv32_memory", "rv32_graphics_rom", "rv32_graphics_bus", "rv32_graphics")
    ]
    if args.animate:
        sources = [str((HERE / s).resolve()) for s in sources]
        sources[sources.index(str(HERE / "rv32_graphics_rom.v"))] = str(out / "rv32_graphics_rom.v")
    for fmt, suffix in [("legacy", ""), ("canonical-v1", "-v1")]:
        # A short structural/behavioral smoke trace; run.py verifies complete boots and frames.
        text = "[verilog]\nsources=[" + ",".join(f'"{s}"' for s in sources) + "]\n"
        text += (
            f'top="rv32_graphics"\nclocks=["clk"]\nformat="{fmt}"\n'
            f'output="{("graphics" if args.animate else "build/graphics")}{suffix}.cv"\n'
        )
        text += (
            '\n[[scenario]]\nname="boot smoke"\n'
            "setup=[{inputs={clk=0,rst=1,run=1},sample=false},"
            "{inputs={rst=0},sample=false}]\nsteps=[\n"
        )
        text += (
            "".join(
                " {inputs={clk=1},sample=true},\n {inputs={clk=0},sample=false},\n"
                for _ in range(64)
            )
            + "]\n"
        )
        ((out if args.animate else HERE) / f"cvgen-verilog{suffix}.toml").write_text(text)
    print(f"Built ROM {sizes['rom']} bytes, RAM {sizes['ram']} bytes; frame checksum {sum(pixels)}")


if __name__ == "__main__":
    main()
