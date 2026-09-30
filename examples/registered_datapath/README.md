# Registered datapath acceptance fixture

`top.sv` instantiates `add_offset` from `child.v`, uses a parameter override, an include directory and a command-line define, and has asynchronous reset plus a clocked register. The two manifests differ only in format and output path.

```console
cv-gen verilog check --manifest examples/registered_datapath/cvgen-verilog.toml
cv-gen verilog check --manifest examples/registered_datapath/cvgen-verilog-v1.toml
```

Each run compares five sampled steps with Verilator and writes a connected Demo scope only after the matching CircuitVerse simulator agrees.
