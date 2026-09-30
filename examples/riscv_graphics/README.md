# RISC-V rendering a C raycaster

A larger machine using the existing RV32I teaching core. A freestanding C program
raycasts a fixed view of an 8×8 room into a **16×16 grayscale framebuffer**.
The project contains native gates, registers, ROM and RAM, with visible circuit
hierarchy. A native **RGB LED matrix labeled SCREEN — 16 × 16** displays the
framebuffer directly on the circuit canvas. Pixels update as the CPU writes them.
The `pixel` output remains available for inspection, and the runner also exports
a PNG of the actual simulated framebuffer.

## Open and execute

Import `build/rom-tested.cv` or `build/ram-tested.cv` at
<https://circuitverse.org/simulator>. Open **rv32_graphics**, then its Testbench
panel and **Run All**. The embedded testbench resets, loads the RAM image when
needed, executes the entire program, and visits every pixel. The RAM package
passes all 39,034 cases through the native Run All engine. Allow about a minute
or longer; browser speed can differ. Find the labeled screen on the right side
of the circuit (zoom or pan if necessary). It begins black and keeps the completed
picture visible after Run All. This modifies the RAM of this scope;
the CPU instance in Demo has its own RAM.

Expected completion: `done=1`, `fault=0`, `result=a0=15384`, `sp=57344` (`0xe000`).
`build/rom-frame-preview.png` and `build/ram-frame-preview.png` show the verified
image enlarged without interpolation.
`build/live-screen.svg` is a capture drawn by the native CircuitVerse matrix after
the packaged RAM demo finishes; it confirms the actual canvas display.

For manual ROM boot, import `build/graphics.cv` and open Demo. Stop the clock
low, set `run=0`, `boot_ram=0`, `load_enable=0`, `inspect=0`, pulse `rst=1` then
`rst=0`, and set `run=1`. Start the clock. Completion automatically pauses the CPU.
The default slow clock requires many minutes: this program needs 19,175 cycles.
Demo has its own screen, which displays the CPU instance running in Demo.

`build/graphics-v1.cv` must be opened in
<https://circuitverse.org/simulatorvue?simver=v1>. It has the same machine and
manual controls. Embedded Run All projects above use the legacy format.

## Memory and loader

| Address | Purpose |
| --- | --- |
| `0x0000–0x3fff` | Persistent ROM code window; writes fault |
| `0x4000–0x7fff` | RAM-loaded code window |
| `0x8000` upward | Initialized globals and BSS |
| `0xd000–0xdfff` | Reserved stack space; initial SP `0xe000` |
| `0xe100` | High-memory test word `0xdeadbeef` |
| `0xf000–0xf0ff` | Framebuffer, row-major, one grayscale byte per pixel |
| `0xfffc–0xffff` | Last-word test `0x12345678` |
| `0x10000`, `0x10004` | Result and done MMIO, word access only |

Four native byte RAM lanes cover 64 KiB; ROM overlays the first 16 KiB, leaving
48 KiB writable by the CPU. The loader can address the underlying RAM, but loading
under the ROM overlay does not replace the ROM. Programs are little-endian.

For RAM boot, pause the CPU and hold `clk=0`, `rst=0`. With `load_enable=0`, set
an aligned `load_address` and `load_data`; pulse `load_enable=1`, then `0` for
each word in `build/ram-load.json`. Change address/data only with enable low.
Set `boot_ram=1`, pulse reset, and run. PC zero executes a jump to `0x4000`.
Reset preserves RAM. Loading and inspection pause the CPU.

To inspect pixels, set `inspect=1` and `peek_address=0xf000 + row*16 + column`.
`pixel` is that byte; `peek_word` is its containing aligned 32-bit word.
The screen observes accepted writes to `0xf000–0xf0ff`. Its controller maps each
of the four byte lanes to the matching columns, so byte, halfword, word and loader
writes preserve unrelated pixels. Grayscale values drive equal red, green and
blue intensities. Reset preserves RAM and the displayed pixels; a new render
overwrites the frame. Opening the project starts with a black screen and empty RAM.
Sixteen small native RAMs in the display controller mirror the framebuffer's
columns, keeping every connected color bus defined even when no write is active.

## Recompile, verify and measure

Requires LLVM with the RISC-V backend and LLD, Yosys, Verilator, Node, and the
installed cv-gen legacy/v1 engines. Homebrew `llvm` provides the LLVM tools.
Run from the repository root:

```sh
uv run python examples/riscv_graphics/compile.py
uv run cv-gen verilog check --manifest examples/riscv_graphics/cvgen-verilog.toml
uv run cv-gen verilog check --manifest examples/riscv_graphics/cvgen-verilog-v1.toml
uv run python examples/riscv_graphics/run.py --boot rom
uv run python examples/riscv_graphics/run.py --boot ram
uv run python examples/riscv_graphics/run.py --format canonical-v1 --boot rom
uv run python examples/riscv_graphics/run.py --format canonical-v1 --boot ram
uv run pytest -o addopts='' tests/test_riscv_graphics.py
```

`compile.py` builds ROM/RAM ELFs, binaries, disassemblies, the word loader JSON,
and persistent ROM banks. Both images are currently 556 bytes; each code window
permits 16 KiB. It also runs the C renderer on the host to produce an independent
256-byte expected image. Edit `main.c` to change the renderer and recompile.
The supplied program needs no multiplication/division runtime helpers.

The manifests perform only a **64-cycle smoke check**. `run.py` verifies complete
execution against a loop-based Verilator testbench: every rising-edge output,
all 256 pixels, high memory, and the last RAM word. It attaches the native screen
after building, validates save/load and masked writes, and compares all screen
colors to host C **before** the inspection scan. Pixels must also match host C.
Failure prevents publishing a successful benchmark or tested project. Legacy runs
embed the verified input trace in the corresponding `*-tested.cv`.
To attach the screen without running the full program, use
`uv run python examples/riscv_graphics/screen.py examples/riscv_graphics/build/graphics.cv`
(add `--format canonical-v1` for `graphics-v1.cv`). A fresh manifest build replaces
the generated project, so run `run.py` or `screen.py` again after rebuilding.
To check Run All and capture the native screen, run:

```sh
uv run python examples/riscv_graphics/screen.py examples/riscv_graphics/build/ram-tested.cv \
  --verify-demo examples/riscv_graphics/build/live-screen.svg
```

Benchmark JSON files distinguish project loading from execution. The timed region
is the native headless CPU clock loop including output sampling, excluding program
loading, project import, compilation and PNG export. An initial legacy RAM run
retired **9,444 instructions in 59.72 seconds**, about **158 instructions/second**.
A real-clock Vue v1 ROM run retired 9,443 instructions in 26.21 seconds, about
360 instructions/second; RAM boot measured 357. A repeat legacy ROM run measured
146 instructions/second (64.82 seconds), demonstrating run-to-run variation.
These are one complete boot plus one frame, not a
steady-state frame rate or a
measurement of maximum browser throughput. Timings vary by machine and load.

## Boundary toward Doom

This is a CPU-produced scene and a reusable program loader. It currently has a
fixed camera, no keyboard controls and no animation.
The core still has the original RV32I example's limitations: no multiply/divide
extension, interrupts, CSR support or operating system.

A Doom port would require substantially more RAM, a C runtime and arithmetic
helpers, WAD access, drawing/input/timing hooks, and much faster execution.
The measured instruction rate makes performance the largest obstacle. The next
useful experiment is a faster native execution path and an animated scene with
input; increasing resolution alone will make this
implementation slower.
