# Teaching CPU

This example is an 8-bit accumulator CPU with a 4-bit program counter. The
CircuitVerse Demo scope exposes `clk`, `rst`, `opcode`, and `immediate` as
controls, plus readouts for the program counter, accumulator, output register,
and halt flag. Set the instruction fields while `clk` is low, then raise `clk`
to execute one instruction.

The generated schematic uses columns based on signal flow, local orthogonal
wires, shared fanout branches, and constants placed beside their consumers.
Register feedback and clock/reset distribution still require longer wires.

The legacy file opens on `teaching_cpu`, which contains the synthesized gates,
adders, and flip-flops. Use the `Demo` tab for the connected CPU block and
controls. This starter takes the instruction fields directly from the controls;
it does not yet include instruction memory or an assembler.

| Opcode | Instruction | Effect |
| --- | --- | --- |
| 0 | NOP | Advance the program counter. |
| 1 | LDI | Load the 8-bit immediate into the accumulator. |
| 2 | ADD | Add the immediate to the accumulator, modulo 256. |
| 3 | OUT | Copy the accumulator to the output register. |
| 4 | HALT | Stop executing and hold the program counter. |

The manifests run `LDI 3`, `ADD 5`, `OUT`, `HALT`, then one more clock to verify
the halt. The sampled accumulator is 3, then 8; the output becomes 8 on `OUT`.
The ordered steps in the manifests are the program source for this starter CPU.

```sh
uv run cv-gen verilog check --manifest examples/teaching_cpu/cvgen-verilog.toml
uv run cv-gen verilog check --manifest examples/teaching_cpu/cvgen-verilog-v1.toml
```

Import `build/teaching-cpu.cv` at
[the default CircuitVerse simulator](https://circuitverse.org/simulator).
Import `build/teaching-cpu-v1.cv` at
[the Vue v1 simulator](https://circuitverse.org/simulatorvue?simver=v1).
The two `.cv` formats are different. The default simulator reports a v1 file
as invalid or corrupt because it expects the legacy `scopes` structure.

For other CPUs to study, [MCPU](https://github.com/cpldcpu/MCPU) is a very
small educational CPU with Verilog, an assembler, and an emulator;
[lightcode's 8-bit computer](https://github.com/lightcode/8bit-computer) has
a broader instruction set and RAM; and [PicoRV32](https://github.com/YosysHQ/picorv32)
is a compact RISC-V core. This starter is original code, and none of those
projects' RTL is included here.

## Inspect the native rendering locally

The legacy adapter can export the actual CircuitVerse canvas drawing as SVG:

```sh
CVGEN_RENDER="$PWD/examples/teaching_cpu/build/teaching-cpu.svg" \
CVGEN_LAYOUT_REPORT="$PWD/examples/teaching_cpu/build/layout.json" \
uv run cv-gen verilog check --manifest examples/teaching_cpu/cvgen-verilog.toml
```

These optional paths must have an existing parent directory. The SVG uses native
CircuitVerse component drawing functions; it is not a separately drawn diagram.
The JSON report records wire length, bends, segment count, and schematic bounds.
