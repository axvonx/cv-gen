# RISC-V running compiled C

An original, multicycle RV32I teaching core running a freestanding C program.
The generated project contains native CircuitVerse gates, registers, RAM and ROM,
with separate tabs for the decoder, ALU, barrel shifter and register file.

## Run it

Import `build/riscv.cv` in the default CircuitVerse simulator. Open `Demo` for the
CPU block and controls. `rv32_demo` shows the CPU and memory/peripheral bus;
open `rv32_core` or `rv32_bus` to inspect their gates.

1. Set `run=0` and stop the clock with `clk=0`.
2. Pulse `rst=1`, then `rst=0` while the clock remains low.
3. Set `run=1` and start the clock.
4. Wait for `done=1`. The expected `result` and `a0` are **55**, with `fault=0`
   and `sp=4096`. Completion pauses the CPU automatically. Reduce the simulator clock period
   if the default clock feels slow.

The project initially contains zero RAM; the program is persistent ROM.
Reset restarts the CPU and clears result/done. C startup copies initialized globals
and zeros BSS on every boot; it does not erase all RAM.

`build/riscv-v1.cv` is for the Vue v1 simulator, not the default simulator.

## Recompile and verify

Install LLVM with its RISC-V backend (`clang`, `ld.lld`, `llvm-objcopy`,
`llvm-objdump`), plus the usual cv-gen dependencies, Yosys and Verilator.
On macOS, Homebrew's `llvm` package provides these tools.
Run from the repository root:

```sh
uv run python examples/riscv/compile.py
uv run cv-gen verilog check --manifest examples/riscv/cvgen-verilog.toml
uv run cv-gen verilog check --manifest examples/riscv/cvgen-verilog-v1.toml
```

Edit `main.c` to try another program. `compile.py` builds an ELF and binary,
produces `build/program.disasm`, generates small persistent native ROM banks,
and refreshes both manifests. Each manifest samples 800 rising edges; extend
this count in `compile.py` if your program needs more time.

`check` compares every sampled output with Verilator before publishing the `.cv`.
The independent architectural test also requires result 55, successful completion,
and restored stack pointer. A successful differential check alone does not require
an arbitrary replacement program to finish within the trace.

```sh
uv run pytest -o addopts='' tests/test_riscv.py
CVGEN_TEST_CPUS=1 uv run pytest -o addopts='' tests/test_riscv.py
uv run python tools/render_cv.py examples/riscv/build/riscv.cv \
  --scope rv32_demo --output examples/riscv/build/riscv.svg
```

## What the C demo checks

- Initialized and zero-initialized global variables through startup code.
- A loop summing squares 1 through 5, yielding 55.
- Calls, returns, local variables on the stack, and saved registers.
- Word, byte and halfword stores; unrelated byte lanes stay intact.
- Signed and unsigned byte/halfword loads, including negative values.
- Result publication through memory-mapped registers.

The `square` function deliberately uses a volatile accumulation loop so LLVM
keeps additions rather than emitting a multiplication helper.

## Machine

| Address | Device |
| --- | --- |
| `0x000–0x7ff` | 2 KiB read-only program/data image; entry PC is zero |
| `0x800–0xfff` | 2 KiB writable RAM for globals, scratch space and stack |
| `0x1000` | 32-bit result register, readable and writable |
| `0x1004` | Done register; a nonzero word store stops execution |

The underlying four 1 KiB byte RAMs cover the 4 KiB address window, with ROM
reads overlaying its lower half. Stores to ROM fault. The stack grows downward
from `0x1000`; the linker reserves at least 256 bytes between static data and
stack top, but there is no dynamic stack-overflow detector.

Registers x0–x31 are 32 bits; x0 is fixed at zero. The core implements RV32I
integer register/immediate operations, all six conditional branches, LUI/AUIPC,
JAL/JALR, signed/unsigned byte and halfword loads, word loads, and byte/halfword/
word stores. FENCE is a NOP on this single-port in-order machine.
Arithmetic instructions take two clocks, memory instructions three.
RAM writes occur in the low phase and commit before the following rising edge.

Misaligned accesses, instruction targets and unsupported encodings stop with
`fault=1`. ECALL/EBREAK also stop with a fault. This is a bare-metal educational
machine: no privileged mode, CSRs, interrupts, compressed instructions, multiply/
divide extension, operating system, libc, display, or keyboard. C operations
needing compiler runtime helpers must supply those helpers when linking.
It has not undergone an official RISC-V compliance suite.

A mux/concatenation barrel shifter avoids the upstream native 32-bit logical
right-shift defect caught by the ALU boundary regression.

ISA reference: [RISC-V RV32I specification](https://docs.riscv.org/reference/isa/v20260120/unpriv/rv32.html).
