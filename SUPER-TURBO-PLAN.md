# CircuitVerse Super Turbo implementation handoff

Read this file first after a context reset. Inspect git status, preserve unrelated work,
and resume the first incomplete milestone. Update each milestone with commands and
evidence, using TODO → IN PROGRESS → DONE. DONE means its verification passed.

## Contract

Original RTL → Verilator C++ → WebAssembly Worker → outputs/framebuffer → local
CircuitVerse v0 drawing. Execute hardware, not a CPU instruction emulator. Bypass
all native propagation, queues and subcircuit dispatch while Super Turbo is active.
Preserve settled functional behavior at both clock phases and input changes;
propagation delays, glitches and internal waveforms are outside this contract.

Local Firefox first. Single external clock, generated legacy projects, top-level
digital ports ≤32 bits, explicit validated boot. Profiles: RV32 graphics and ROM
playback. Do not change default cv-gen commands or the .cv schema. Internal signals
are unavailable. Restart on mode changes; no state transfer. Start off each load.
Public Tampermonkey delivery, arbitrary circuits, live 64×64 CPU rendering and
interactive hallway navigation remain later work.

## Existing evidence — DONE

Baseline commit: 2191e17950facafb4c99a511aca1872c806565b0. Live CPU median frame time
22.463 s native Turbo versus 13.970 s insertion-pass Turbo (1.61×). Reprofile:
approximately 96% native propagation. Existing queue/profile reports are in tools/.
Live fixture: examples/riscv_graphics/build/cpu-animation.cv; generated manifest:
examples/riscv_graphics/build/animation/cvgen-verilog.toml. 64×64 animation is ROM
playback. C reference images and native first-two-CPU-frame checks already exist.

## Implementation decisions

Compiler: opt-in tools/build-circuitverse-fastpath.py with --spec, --project,
--profile rv32-graphics|rom-playback, --out. Package exact final project.cv,
manifest.json, model.mjs/model.wasm, worker/runtime and initialization assets.
Manifest ABI, port order/widths, clock/boot/display bindings, source and final-project
SHA256, compiler versions/flags and validation results bind the model to its project.
Reject missing/ambiguous bindings and unsupported HDL; hash includes and memory
initialization files. Missing runtime dependencies fail compilation.

Pin Verilator 5.052 and Emscripten 6.0.10 in an isolated cache. Standard MODULARIZE
ES-module Worker output, no threads/shared memory/tracing/VPI. Allowlist reviewed
Verilator warnings, not blanket suppression. Prove async RAM convergence first.

C++ bulk API: create/reset/applyInputs/advance/snapshot/destroy. Ordered Uint32
buffers, masked input widths. All per-edge execution stays in WASM. Boot clock low,
evaluate every reset/input transition and both clock phases. RAM writes occur low;
never skip falling evaluations. Recreate model/context to reset initial memory.

One Worker, one outstanding advance request: ≤65,536 half-edges, 8 ms budget,
time check at least every 128 edges. Main thread grants batches only while allowed.
Pause acknowledgment follows the outstanding batch; no execution afterward.
Hidden tabs stop grants with no catch-up. Epoch/sequence reject stale responses.
Faults and traps stop execution, never resume stale native state automatically.

RV32 display observes settled screen_write/address/data/mask, including loader
writes, mirrors byte lanes, identifies completed frames through result changes,
and validates against RAM inspection. Playback observes row/frame/RGB columns,
including initial row and wraparound. Observe every phase/write; presentation ≤30Hz,
statistics ≤4Hz. No simulation edges may be dropped by presentation throttling.

Isolated frontend checkout: 774003e5b14fb583b2c558d04f455b54031f40cc, v0 only,
serve /simulator with history fallback. Never patch shared reference-engine cache.
Source-level exclusive backend seam: setMode(native|super), pause/resume/reset,
stepHalfEdge/applyInputs/snapshot/dispose. Stop native clock/Turbo; guard native
clock/input/update/subcircuit execution; direct snapshot output and matrix assignment
with drawing-only path. Instrument queue/node/component execution: zero when active.

Enter fresh boot. Exit reload pristine native project paused. Import disposes and
invalidates. Unbound scope/layout pauses; scope return needs resume. Hidden resume
only if previously running. Editing disabled; top inputs, controls, pan/zoom remain.
Save/export requires exiting/resetting. Neutral internal wires and unavailable
tooltips/waveforms. Native period is unchanged and applies only to native mode.
Show status, half-edges/s, completed-frame latency and batch duration.

## Acceptance

Native C++ versus WASM lockstep at both phases/non-clock stimuli. Compare native CV
first two live CPU frames: CPU ports/state, accepted writes, pixels and no faults.
Check all 32 live CPU frames plus wrap against fresh C images; playback 16/64 all32
plus wrap. Cover RAM masks/load/inspect/bounds, ROM init, reset/run hold, signed loads,
shifts and overflow. Reject framebuffer/RAM discrepancies.

Visible Firefox: zero native propagation, exclusive runner, pause/step/reset,
hidden/layout/scope/import/error/stale reply tests, normal restoration. Benchmark
three alternating trials/mode, warm frame1 and measure frame2, rendering enabled,
fresh insertion-pass baseline in same frontend. Record frame latency, edges/s,
batch/message time, pause acknowledgments and RAF gaps. Require ≥10× median speedup,
pause acknowledgment p95 <50ms, correct frames/no faults/no catch-up. 1.397s from
historical baseline is a target, not forecast. If missed, profile WASM/copy/messages/
drawing separately. Run backend/frontend and existing JS/Python tests plus lint.

## Milestones

| Milestone | Status | Evidence |
|---|---|---|
| Baseline and architecture | DONE | Committed reports; decisions above |
| Persist plan | DONE | This file |
| Isolated toolchain and smoke build | DONE | Verilator 5.052 / isolated Emscripten 6.0.10; CPU WASM build |
| Package compiler and hardware wrapper | DONE | CPU 2,435 differential checkpoints; loader/inspect/RAM checks |
| Worker and display observers | DONE | Fresh C 32-frame references; CPU 33, playback16 64, playback64 40 frames checked |
| Local frontend controller | DONE | Visible Firefox lifecycle and zero-native-propagation acceptance; 67 frontend tests |
| Correctness and 10× acceptance | DONE | Final visible Firefox median 14,271 → 33 ms (432×); pause p95 6 ms; all lifecycle/reference checks passed; 117 Python tests / 6 skipped |
| Documentation, commit and push | IN PROGRESS | Guide and tools/circuitverse-fastpath-results.json complete; delivery commit/push next |

Keep build outputs/checkouts ignored; commit source, tests, integration patch,
documentation and compact measured results. Publish actual limits and reproduction
commands. Do not use the no-mistakes workflow (explicit user instruction). Run
tests, lint, browser acceptance and review directly.

## Current reproduction and evidence

Start: `uv run python tools/serve-circuitverse-fastpath.py --no-build`, then open
`http://127.0.0.1:8765/simulator?fastpath=/packages/cpu/` in Firefox. Stable ignored
packages are build/fastpath/{cpu,playback16,playback64}; each manifest's validation
is passed. Browser harness: `uv run --with selenium python tools/circuitverse-fastpath-firefox.py`.
All input/control operations and mode changes serialize; old pump failures cannot
poison replacement sessions. Unexpected presentation failures stop the Worker.

First-two-CPU-frame native settled transcript: 72,791 half-edges × 15 outputs,
SHA256 ddab43261153edbc704e42b237a81561e99f893533aa3896bc5fec3e0fdd7ee8.
Verify using `node tools/fastpath/verify-native-trace.mjs build/fastpath/cpu
build/fastpath/native-port-trace.json`. Trace capture is excluded from benchmarks.
Final frontend source anchors additionally preserve native pause/period controls,
gray internal wires, and disable the upstream tutorial for packaged URLs.
