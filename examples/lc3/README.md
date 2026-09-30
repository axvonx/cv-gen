# LC-3 in CircuitVerse

An original LC-3 datapath with eight 16-bit registers, a 16-bit PC and PSR,
NZP condition codes, a multi-cycle instruction controller, and 65,536 words
of RAM. A connected program ROM supplies a demo and a small HALT trap handler.
Memory is word addressed. Core instructions include ADD/AND (register and immediate),
NOT, BR, JMP/RET, JSR/JSRR, LD/ST, LDR/STR, LDI/STI, LEA, TRAP, and RTI.

```sh
uv run cv-gen verilog check --manifest examples/lc3/cvgen-verilog.toml
uv run cv-gen verilog check --manifest examples/lc3/cvgen-verilog-v1.toml
```

Open `build/lc3.cv` in the [default CircuitVerse simulator](https://circuitverse.org/simulator).
Use `Demo` for controls, `lc3_demo` for the connected blocks, and `lc3_core`
and `lc3_registers` to inspect the gates. The v1 artifact belongs in the
[Vue v1 simulator](https://circuitverse.org/simulatorvue?simver=v1).
Run the commands from the repository root: the 64K-word zero initialization
image is `examples/common/zero.hex`.

## Run the supplied program

Set `run=0`, `load_enable=0`, `demo_enable=1`. Pulse `rst` from 1 to 0,
then set `run=1` and clock. After 50 rising edges:

- `r1=8`, `r2=9`, `r3=0xFFF8` (-8).
- `halted=1`, `done=1`, `fault=0`.

The program adds 3+5, stores and loads the result, forms -8, takes a negative
branch, calls a routine to increment R2, returns through R7, and executes TRAP x25.
TRAP reads vector word x0025 and jumps to x3100. Its handler uses STI to write
zero to the machine control register at xFFFE, halting the CPU. The CPU does
not treat xF025 as a special instruction; it follows the actual trap vector.
`demo.asm` is the readable listing; `demo.hex` contains the main program words.
The ROM module also supplies the vector and handler words.

## Load a program

Pause `run=0`, hold `clk=0`, and set `demo_enable=0`. Keep `load_enable=0`
while setting `load_address` and `load_data`, then pulse `load_enable=1`
to write a word and return it to 0. Load code at x3000 and any data/trap vectors
it needs. Pulse CPU reset, then enable `run`. Reset preserves RAM; opening the
project initializes it to zero. The supplied demo ROM is an overlay: writes to
its addresses are visible only with `demo_enable=0`.

## System boundaries

Reset enters user mode (`PSR=x8002`) at x3000. RTI faults in user mode; in
supervisor mode it restores PC and PSR from the stack at R6 and increments R6
by two. The core parameters `RESET_PC` and `RESET_PSR` select another boot state.
Opcode xD faults. This is an instruction-level teaching machine, not the book's
microcode implementation. Interrupt delivery, automatic user/supervisor stack
switching, memory protection, and the full LC-3 operating system are not included.
The demo implements the machine-control halt register; keyboard/display device
registers and the GETC/OUT/PUTS/IN/PUTSP OS routines are not attached.

Instruction reference: [LC-3 ISA overview, Colorado State University](https://www.cs.colostate.edu/~cs270/.Fall20/resources/LC3Overview.pdf).
The RTL here is original code.
