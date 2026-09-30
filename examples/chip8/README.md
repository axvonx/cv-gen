# CHIP-8 in CircuitVerse

An original synthesizable hardware interpreter with sixteen 8-bit registers,
a 12-bit PC and index register, a sixteen-entry call stack, 4 KiB of byte RAM,
a font/program ROM, and a 64×32 one-bit framebuffer. The drawing engine reads
sprite bytes and performs pixel XORs over multiple cycles; it records collisions
in VF. Keypad, random-byte, and timer-tick inputs are exposed on the Demo scope.

```sh
uv run cv-gen verilog check --manifest examples/chip8/cvgen-verilog.toml
uv run cv-gen verilog check --manifest examples/chip8/cvgen-verilog-v1.toml
```

Open `build/chip8.cv` in the [default CircuitVerse simulator](https://circuitverse.org/simulator).
The `chip8_demo` tab shows the connected CPU, memory, display memory, and ROM;
`chip8_core`, `chip8_alu`, `chip8_registers`, and `chip8_stack` expose their gates.
The `Demo` tab contains controls and readouts. The v1 artifact belongs in the
[Vue v1 simulator](https://circuitverse.org/simulatorvue?simver=v1).

## Run the supplied program

1. Set `run=0`, `load_enable=0`, `demo_enable=1`, and `timer_tick=0`.
2. Pulse `rst` from 1 to 0. Set `run=1`, then clock the machine.
3. After 120 rising edges, `done=1`, `fault=0`, `pc=0x220`, `v0=16`, and `vf=1`.

The program adds 3+5, stores and reloads registers, draws a one-pixel sprite twice,
calls a subroutine to add 8, checks the result with a skip, and ends in a jump loop.
The second draw erases the pixel and sets VF. `demo.hex` lists the 16-bit instructions
in order from byte address 0x200; the return routine starts at 0x222.

`view_address = y*64+x` selects a framebuffer pixel when the drawing engine is
idle; `view_pixel` shows its value. Address 129 is the demo sprite at (1,2).
While drawing, that port shows the drawing engine's active pixel. There is no
bitmap UI in this first hardware example: framebuffer inspection uses this port.
`keys` is a 16-bit mask (bit k means key k is down). `random_byte` is supplied
externally. Drive `timer_tick=1` for one rising CPU edge per 60 Hz tick, then
return it to 0. Sound output is the `sound_timer` readout; no audio device is attached.

## Load another program

Pause with `run=0`, keep `clk=0`, and set `demo_enable=0`. For each byte, keep
`load_enable=0` while changing `load_address` and `load_data`, pulse
`load_enable` to 1 to write, then back to 0. Load the image at 0x200; include
font bytes at addresses 0–79 if it uses FX29. Pulse CPU reset and set `run=1`.
Reset clears the CPU registers, stack, and timers; it preserves RAM and the
framebuffer. Opening the project initializes RAM/framebuffer to zero.

## Instruction profile and boundaries

Implements the standard arithmetic, branches, calls, skips, timers, keypad,
random, BCD, register transfers, and sprite operations. Shifts use VY, FX55/65
advance I, sprites wrap at screen boundaries, and logic operations preserve VF.
Arithmetic flags are written after VX, including when X=F. Equal operands in
subtraction set the no-borrow flag. FX0A accepts the lowest currently pressed
key; it does not wait for release. Timer ticks are independent of `run`.
Unsupported encodings and stack under/overflow raise `fault` and stop execution.
0NNN requires a COSMAC host and faults; DXY0 and Super-CHIP/XO-CHIP extensions
are not implemented. Font ROMs are native 16-byte ROM banks, retained on save/load.

Instruction reference: [Matthew Mikolay's CHIP-8 instruction set](https://github.com/mattmikolay/chip-8/wiki/CHIP%E2%80%908-Instruction-Set).
The RTL here is original code; the reference is used for opcode semantics.
