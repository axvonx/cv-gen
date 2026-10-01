# DOOM on the simulated RISC-V machine

## Resume here

Read this file and `SUPER-TURBO-PLAN.md`, then inspect git status before working.
The next milestone is **the real DOOM engine boots and produces its first gameplay
frame on our RTL in native Verilator**. Do not start with another CircuitVerse
scheduling optimization or assume the existing raycaster is DOOM.

Work directly, without Lavish sessions, agent delegation, or the no-mistakes
workflow. The user explicitly prohibited no-mistakes. Preserve unrelated work.

Progress: the pinned engine, runtime and ISS oracle are done, and DOOM reaches
E1M1 gameplay on the ISS; host-reference frames match. Next: the DOOM machine
RTL (`examples/doom/*.v`), the CircuitVerse representation check, and the native
Verilator testbench. See **DOOM bring-up state** below.

## DOOM bring-up state

User decisions (2026-10-01): CircuitVerse export of the large machine is required,
so its representation is checked early; use the shareware WAD; a small RV32I ISS
is allowed **only as a test oracle** — DOOM instructions must execute on the RTL.

Pinned inputs (fetched into ignored `build/doom` by `examples/doom/build.py`):

- doomgeneric `dcb7a8dbc7a16ce3dda29382ac9aae9d77d21284`.
- LLVM compiler-rt builtins at `llvmorg-23.1.2` (matches Homebrew clang 23.1.2),
  built for rv32i; no prebuilt rv32 compiler-rt or libc exists on this machine.
- Shareware DOOM v1.9 `doom1.wad`, 4,196,020 bytes, MD5
  `f0cefca49926d00903cf57551d901abe`, SHA-1 `5b2e249b9c5133ec987b3ea77596381dc0d6bc1d`,
  SHA-256 `1d7d43be501e67d927e415e0b8f3e29c3bf33075e859721816f652a526cac771`.
  Never commit it.

Runtime (`examples/doom/runtime`): the engine imports only a small libc
(host-compiled `nm -u` inventory: stdio file/printf family, malloc family, string,
`sscanf`, `atoi`/`atof`, `exit`, a few POSIX stubs); `libc.c` implements exactly
that, with a bump allocator and the WAD as the only readable file (read by copying,
never mapped in place, so lump data stays aligned). Build flags: `-march=rv32i`,
`CMAP256`, 320×200, so the engine writes palette indices straight into the fixed
framebuffer. `machine.h` is the single memory-map/MMIO definition shared by the
runtime, the ISS, the testbench and (mirrored) the RTL.

Timing policy: deterministic. The platform sets `singletics` (one game tic per
rendered frame, as `-timedemo` does) and the virtual clock advances only in
`DG_SleepMs`, which only the screen wipe uses. Without `singletics`, every other
frame re-rendered an unchanged tic.

Memory map: 16 MiB RAM (4 banks × 4 byte lanes × 2^20, matching CircuitVerse's
RAM `maxAddressWidth` of 20), program at 0 with data accesses below 0x1000 faulting
(null guard), heap to 0xa00000, stack top 0xb00000, WAD header+file at 0xb00000,
framebuffer 0xf10000, palette 0xf20000, word-only MMIO at 0x10000000 (console,
exit, frame doorbell, key FIFO, 64-bit cycle and instret counters).
Frame handshake: a doorbell write halts the CPU until the host acknowledges, so the
host reads a coherent frame and injects key events at a deterministic point.

Correction to the earlier review: misaligned loads/stores are **not** silent —
`rv32_decode.v` marks them illegal and the core faults. The new bus adds a fault
cause (illegal/fetch/align/access/MMIO) so failures are diagnosable.

Measured on the ISS (`tools/doom/iss.c`, same legality and 2/3-cycle timing as the
RTL), `-warp 1 1`, no input:

| Metric | Value |
|---|---:|
| Instructions / cycles to first frame (start of wipe) | 22.3 M / 49.0 M |
| First gameplay frame (wipe done, tic advancing) | frame 42: 32.1 M instr / 71.2 M cycles |
| Steady gameplay cost per frame (= per tic) | ≈3.18 M instr, ≈6.94 M cycles (CPI ≈2.18) |
| Heap high-water (incl. 6 MiB zone) / stack use | 0x6e7358 / ≈1.2 KiB |
| ISS speed on M4 | ≈250 M instr/s |

At the browser's measured 547 k cycles/s that is ≈13 s per gameplay frame; native
Verilator speed is not yet measured.

Host reference (`build/doom/bin/doom-host`, same engine+platform natively):
frame hashes match the ISS for every frame from the first gameplay frame (42)
through 200. The wipe frames before it differ because the wipe's start screen
samples stale zone memory whose layout depends on pointer size; ISS and RTL share
the 32-bit layout and must match on every frame.

Reproduce: `uv run python examples/doom/build.py`, then
`clang -O2 -o build/doom/bin/iss tools/doom/iss.c` and
`build/doom/bin/iss --frames 200 --dump-every 50 --out build/doom/run-iss`; compare
`frames.tsv` with `build/doom/bin/doom-host --frames 200 --out build/doom/run-host`.

## Current foundation

Repository: `/Users/axvon/cv-test`, GitHub `axvonx/cv-gen`.
Branch: `feat/circuitverse-super-turbo`, pushed through `f2c2cac`.
Implementation commit: `1e7533e`.

Super Turbo executes original RTL through Verilator C++ compiled to WebAssembly
in a Worker. CircuitVerse draws outputs and framebuffer snapshots; native gate
propagation is bypassed. This is hardware simulation, not an instruction emulator.
Mode changes restart hardware; there is no native/compiled state transfer.

The release supports the pinned local CircuitVerse v0 frontend in Firefox, the
live 16×16 RV32 renderer, and 16×16/64×64 ROM playback. The 64×64 circuit is
precomputed playback, not live rendering or interactive walking. The live renderer
is a simple raycaster with an automatic camera sweep, not the DOOM engine.

Final visible Firefox 157 benchmark on Apple M4, rendering enabled, three
alternating trials per mode, first-frame warmup and second-frame timing:

| Metric | Result |
|---|---:|
| Insertion-pass Turbo median CPU frame | 14,271 ms |
| Super Turbo median CPU frame | 33 ms |
| Median frame-latency speedup | 432× |
| Super median half-edges/second | 1,095,455 |
| Approximate full clock cycles/second | 547,727 |
| Pause acknowledgment p95, 20 samples | 6 ms |
| Sustained browser animation-frame maximum gap, 118 samples | 17.68 ms |

**This is not a 16 MHz measurement.** The core takes two or three clock cycles per
instruction, so retired instructions/second are lower. The simple raycaster's
33 ms frame does not predict DOOM performance. Hardware completion and canvas
presentation are different; presentation is capped at 30 Hz.

All 32 frames plus wrap matched reference pixels for CPU and playback. The native
CircuitVerse first-two-CPU-frame settled transcript matched WASM across 72,791
half-edges and 15 outputs. Lifecycle checks passed with zero native propagation.
117 Python tests passed (6 skipped), 33 Node tests and 67 frontend tests passed;
lint passed. See `tools/circuitverse-fastpath-results.json` for measured evidence.

## Hardware constraints to address

- RV32I teaching core; no multiply/divide extension, interrupts, CSR support, or OS.
- FETCH and EXECUTE states, plus MEMORY for loads/stores: two or three cycles per
  instruction. The exposed 16-bit retired counter wraps; account for wrap or add
  a wider measurement counter when measuring long workloads.
- Four byte RAM lanes cover 64 KiB. A 16 KiB ROM overlays the bottom window,
  leaving 48 KiB writable by the CPU. ROM code is currently limited to 16 KiB.
- Framebuffer is 256 grayscale bytes at `0xf000`; result/done MMIO is at
  `0x10000` and `0x10004`. These addresses must be redesigned for a larger machine.
- Loader/inspection addresses are 16 bits, screen addresses are 8 bits, and the
  build/linker/display bindings assume the small machine. Expand these together.
- No keyboard interface currently exists.

Relevant files:

- `examples/riscv/rv32_core.v`, `rv32_decode.v`, `rv32_alu.v`, `rv32_lanes.v`.
- `examples/riscv_graphics/rv32_graphics.v`, `rv32_graphics_bus.v`, `rv32_memory.v`.
- `examples/riscv_graphics/compile.py`, `start.S`, `main.c`, `README.md`.
- `tools/fastpath/compiler.py`, `model.py`, `runtime.mjs`, `controller.mjs`,
  `frontend.js`, and the verification tools in that directory.
- `tools/CIRCUITVERSE-SUPER-TURBO.md` for reproduction and controls.

## Proposed implementation sequence

### 1. Boot the actual game in native RTL simulation

Use a pinned revision of [doomgeneric](https://github.com/ozkl/doomgeneric).
Its platform interface provides initialization, drawing, sleep/time, keyboard
events, and an optional window title. It also needs WAD game data and the C runtime
facilities used by the chosen build. Inspect these dependencies before selecting
the toolchain/runtime approach; do not assume the display hooks are the whole port.

Cross-compile the engine to RISC-V and supply the required runtime, arithmetic
helpers, WAD access, framebuffer, and timing interfaces. Start without sound.
Use a user-provided or appropriately sourced shareware WAD, record its hash, and
avoid committing game data casually. Keep game instructions executing on the RTL;
do not substitute a host-side DOOM renderer or CPU emulator.

Build and run natively with Verilator first. Bring-up should expose serial/log
output, faults, PC and progress counters so a failed boot is diagnosable.

### 2. Expand memory and loading

Derive the memory budget from the linked image and measured allocations: executable
code/data, heap, stack, framebuffer, and WAD storage. Do not promise a particular
RAM size before inspecting the actual port. Design a non-overlapping memory map
and update address widths, bounds checks, initialization/loading and linker layout.

Keep large memories as arrays in compiled hardware. Flattening megabytes into
CircuitVerse gates would create a new generation and simulation bottleneck.
Determine the corresponding CircuitVerse representation before exporting the
larger machine; be explicit if that requires a supported atomic memory component
or a new backend binding. Preserve the original small fixtures as regression cases.

### 3. Establish correctness and workload cost

Use a deterministic demo or scripted inputs. Produce a host reference using the
same engine, game data, resolution, inputs and timing policy, then compare gameplay
frame hashes/pixels with RTL execution. Check that progress is genuine gameplay,
not only a title screen. Report faults and unsupported instructions explicitly.

Measure retired instructions/second, cycles/instruction, cycles per game tick and
completed frame, native simulation throughput, and allocation high-water marks.
Distinguish engine simulation ticks from rendered frames. These measurements,
rather than the raycaster benchmark, determine the DOOM speed estimate.

### 4. Optimize the measured CPU workload

RV32M multiply/divide is a strong candidate because the current core lacks it;
measure software-helper cost first. Implement and verify signed/unsigned variants
and architectural edge cases if adding the extension. Fetch/execute overhead and
memory access are other candidates. Change RTL and revalidate the same deterministic
workload, continuing to simulate the hardware faithfully.

Profile the compiled model separately if simulation overhead dominates. Avoid
reintroducing per-edge JS calls or native CircuitVerse propagation. Report each
improvement against the same workload and configuration.

### 5. Integrate the working machine with Super Turbo

Extend the package/display profile for the larger framebuffer and palette, keyboard
events, timing interface, and explicit completed-frame signaling. Start at a low
resolution validated against the reference; increase it based on measured cost.
Reducing only the displayed image after full-resolution rendering does not reduce
the CPU rendering workload.

Keep the single-Worker/one-outstanding-batch invariant, processed pause semantics,
hidden-tab suspension without catch-up, fault handling, and fresh boot on mode changes.
Input events must reach the simulated machine; choose and document whether game
time follows simulated cycles or paced external ticks so speed changes remain coherent.

## Milestones and acceptance

| Milestone | Status | Acceptance |
|---|---|---|
| Existing Super Turbo foundation | DONE | Evidence above and committed reports |
| Inspect/pin engine and design runtime/memory map | DONE | Reproducible toolchain, dependency inventory, estimated memory budget |
| ISS oracle boot + host reference | DONE | E1M1 gameplay on ISS; host frames match from first gameplay frame |
| Native RTL DOOM boot | TODO | Actual engine reaches first gameplay frame, no CPU/bus faults |
| Deterministic correctness and baseline | TODO | Matching reference frames plus instruction/cycle/memory measurements |
| CPU/model optimization | TODO | Measured improvement with unchanged reference results |
| Browser integration and controls | TODO | Correct frames, keyboard movement, lifecycle tests, zero native propagation |
| Interactive speed assessment | TODO | Published measured game-tick/frame rates and bottlenecks |

The first goal is **real DOOM boots and renders gameplay on our RTL**. Then make
it interactive, then pursue playable speed. No playable-frame-rate guarantee yet.
Keyboard-controlled walking in the existing raycaster is a useful optional input
test, but it is not a substitute for DOOM bring-up.

## Reproduction of the existing foundation

Ignored packages/checkouts are under `build/fastpath`. If present:

```sh
uv run python tools/serve-circuitverse-fastpath.py --no-build
# Open http://127.0.0.1:8765/simulator?fastpath=/packages/cpu/ in Firefox.
```

For a fresh checkout, follow `tools/CIRCUITVERSE-SUPER-TURBO.md` to regenerate
fixtures, install the isolated Emscripten SDK, build and verify packages, and build
the pinned frontend. Current toolchain pins are Verilator 5.052, Emscripten 6.0.10,
and CircuitVerse frontend revision `774003e5b14fb583b2c558d04f455b54031f40cc`.

Update this file as decisions and measurements become concrete. Re-read relevant
source rather than relying solely on this handoff. The user requested this file so
the DOOM work can begin in a fresh context.
