# Local CircuitVerse Super Turbo

Super Turbo executes the original generated hardware as a Verilator model compiled
to WebAssembly. A dedicated Worker evaluates every clock half-edge; CircuitVerse
only draws output and framebuffer snapshots. This is not a RISC-V instruction
emulator, a ROM replacement for the CPU, or a patch that discards clock edges.

The first release supports the generated **live 16×16 RV32 renderer** and the
**16×16 / 64×64 ROM playback circuits**, in the pinned local v0 simulator and
Firefox. Public CircuitVerse/Tampermonkey installation is not part of this release.

## Build and run

Prerequisites: `uv`, Node, Yosys, `clang++`, git, and **Verilator 5.052** on PATH.
Install the isolated **Emscripten 6.0.10** SDK:

```sh
sh tools/setup-circuitverse-fastpath.sh
```

The setup script does not edit shell profiles. The compiler automatically finds
the SDK under `~/.cache/cv-gen/emsdk-6.0.10`, or uses an activated SDK on PATH.

Generate fixtures if their ignored build directories are missing:

```sh
uv run python examples/riscv_graphics/animate.py
uv run python examples/riscv_graphics/animate.py --size 16 --playback-only
uv run python examples/riscv_graphics/animate.py --size 64 --playback-only
```

Build the live CPU package, then validate it against the reference:

```sh
uv run python tools/build-circuitverse-fastpath.py \
  --spec examples/riscv_graphics/build/animation/cvgen-verilog.toml \
  --project examples/riscv_graphics/build/cpu-animation.cv \
  --profile rv32-graphics --out build/fastpath/cpu
node tools/fastpath/verify.mjs build/fastpath/cpu \
  examples/riscv_graphics/build/animation/expected-frame.bin
```

The output directory must be empty. For a rebuild, choose a new directory rather
than overwriting a package that may be running.

The playback packages use their matching manifests. The older manifest under
`build/animation/playback.toml` uses a different interface; use `animation-16`:

```sh
uv run python tools/build-circuitverse-fastpath.py \
  --spec examples/riscv_graphics/build/animation-16/playback.toml \
  --project examples/riscv_graphics/build/animation.cv \
  --profile rom-playback --out build/fastpath/playback16
node tools/fastpath/verify.mjs build/fastpath/playback16 \
  examples/riscv_graphics/build/animation-16/expected-frame.bin

uv run python tools/build-circuitverse-fastpath.py \
  --spec examples/riscv_graphics/build/animation-64/playback.toml \
  --project examples/riscv_graphics/build/animation-64.cv \
  --profile rom-playback --out build/fastpath/playback64
node tools/fastpath/verify.mjs build/fastpath/playback64 \
  examples/riscv_graphics/build/animation-64/expected-frame.bin
```

Start the local simulator:

```sh
uv run python tools/serve-circuitverse-fastpath.py
```

Open **http://127.0.0.1:8765/simulator?fastpath=/packages/cpu/** in Firefox.
Use `/packages/playback16/` or `/packages/playback64/` for playback. The first
launch clones the pinned frontend and installs its locked npm dependencies into
the ignored `build/fastpath/frontend` directory. It does not modify the shared
CircuitVerse reference-engine cache. Subsequent launches can use `--no-build`.

## Controls and behavior

- Super Turbo starts off. **Enable** boots a fresh compiled model and starts it.
- **Run / Pause**, **Reset**, **Step**, and the expandable hardware input controls
  operate the compiled model. Step advances exactly one half-edge.
- The ordinary clock-enable control also pauses/resumes Super Turbo. Period changes
  preserve the native period but do not start a native runner while Super Turbo is active.
- Hiding the tab stops new batches; returning resumes without catching up. Layout
  mode or selecting another circuit pauses and requires an explicit resume.
- Drag the canvas to pan; native wheel zoom remains available.
- **Disable** discards compiled state, reloads the original project, and leaves native
  execution paused. Resume it explicitly with the clock-enable control.
- Imports dispose the Worker and invalidate the binding. Editing, saving, and
  internal signal/timing inspection require exiting Super Turbo first.
- Worker/model errors stop execution. They do not automatically run stale native state.

Internal wires are gray and their values are unavailable. Top-level outputs and
the framebuffer remain live. Hardware evaluation processes every phase and write;
the viewer coalesces presentation to at most 30 updates/second. A completed hardware
frame can therefore finish sooner than its next canvas presentation.

The CPU circuit computes frames from scratch at 16×16. The 64×64 circuit plays
precomputed ROM frames. Its current camera follows the existing automatic sweep;
this release does not add interactive walking or a live 64×64 renderer.

## Implementation and package contract

`tools/fastpath/compiler.py` validates the generated project bindings and produces
the WASM package. The package records the exact project/source/dependency hashes,
port widths/order, boot and display profile, compiler flags, ABI and tool versions.
The browser verifies assets and project identity and refuses unverified packages.
Missing or ambiguous bindings, unknown compiler warnings, unsupported port widths,
four-state interfaces, timing constructs and dynamic initialization filenames fail closed.

The C++ wrapper holds the full Verilated model, not a substituted high-level CPU.
It evaluates high/low phases and non-clock input changes, including low-phase
asynchronous RAM writes. Reset recreates the model and restores initialized memory.
The reviewed warning allowlist includes asynchronous memory latch/COMBDLY diagnostics;
the Emscripten shim disables only host CPU-affinity detection, using Verilator's
portable fallback. No threading, VPI, gate callbacks into JS, or tracing runs in the hot loop.

The main thread grants one Worker batch at a time, up to 65,536 half-edges or an
8 ms budget checked every 128 phases. One outstanding batch can finish after a
pause/hide request; a pause acknowledgment means it has finished and no further
edges will run. A single evaluation cannot be preempted. Worker traps, convergence
failures and timeouts stop the backend. Epochs discard replies from old sessions.

The frontend integration uses exact source anchors at revision
`774003e5b14fb583b2c558d04f455b54031f40cc`. Native clock/play/update paths are guarded;
queue/node/component/scope-clock methods are instrumented to reject accidental
native execution. Snapshot drawing uses `renderCanvas` directly and leaves native
propagation untouched for normal mode. No `.cv` schema or default CLI changes.

## Verification

```sh
uv run pytest
uv run ruff check .
node --test tests/*.test.cjs tests/*fastpath*.test.mjs
NODE_OPTIONS=--no-experimental-webstorage npm --prefix build/fastpath/frontend run test:src
uv run --with selenium python tools/circuitverse-fastpath-firefox.py
uv run --with selenium python tools/circuitverse-fastpath-firefox.py --trace-only
node tools/fastpath/verify-native-trace.mjs build/fastpath/cpu \
  build/fastpath/native-port-trace.json
```

The Node web-storage option avoids an upstream test-environment conflict with Node 26;
it does not change browser execution. Browser tests launch actual visible Firefox,
inject the existing Turbo userscript early for the comparison, and keep drawing enabled.
No no-mistakes workflow is used.

The package verifier checks native C++ versus WASM at both phases and input changes,
reset/run hold, loader/inspection/bounds, and framebuffer versus actual RAM. It checks
all 32 frames plus wrap against C reference pixels. The native trace compares the full
settled 15-output transcript through the first two CPU frames using SHA-256.
Browser acceptance covers controls, hidden tabs, layout/scope/imports/errors, native
restoration and zero native propagation. Three alternating benchmark trials warm
through frame one and measure frame two on the same machine/frontend.

Measured results are in `tools/circuitverse-fastpath-results.json`; raw acceptance
and trace results remain under `build/fastpath`. Timing describes completed hardware
frames, with Firefox timestamp quantization, rather than guaranteed video frame rate.

On an Apple M4 in visible Firefox 157, the live 16×16 CPU renderer measured:

| Mode | Median completed-frame time | Median half-edges/second |
|---|---:|---:|
| Insertion-pass Turbo | 14,271 ms | 2,533 |
| Super Turbo | 33 ms | 1,095,455 |

That is a **432× reduction in frame latency**, across three alternating trials per
mode after a first-frame warmup. Pause acknowledgment p95 was 6 ms over 20 samples.
A separate two-second sustained run recorded 118 animation-frame gaps, with a
maximum of 17.68 ms and none above 100 ms. The short Super benchmark intervals
contained no animation-frame samples, so responsiveness uses that separate run.
All 32 frames plus wrap matched the reference for the CPU and both playback sizes.

Speedup is specific to these circuits and this machine. Maximum throughput increases
CPU use. Multi-clock, arbitrary edited circuits, native propagation delays/glitches,
four-state simulation and internal waveforms are not supported by this backend.
