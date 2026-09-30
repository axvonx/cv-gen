# cv-gen

`cv-gen` generates CircuitVerse testbenches and builds `.cv` projects from Verilog. The two workflows have separate manifests and never upload as part of a Verilog build or check.

## Install

```console
uv sync --extra dev
uv run cv-gen engine install
```

Verilog builds require Node, local Yosys, and the pinned CircuitVerse engine for the selected format. `verilog check` also requires Verilator. Node 22 LTS or newer is recommended. `engine install` fetches the legacy CircuitVerse commit `6f725c5a924dc0b73527215eb5aa0618e45330e1` and Vue v1 commit `efadf7a9fda9ff3bf93002e0020bd4a9ba53e920` into `~/.cache/cv-gen/`. Use `--format legacy` or `--format canonical-v1` to install one. `CVGEN_CACHE`, `CVGEN_ENGINE_DIR`, and `CVGEN_V1_DIR` select another cache or prepared checkout. Existing `.cvt` state is never read or migrated.

## Verilog

Create `cvgen-verilog.toml`:

```toml
[verilog]
sources = ["rtl/child.v", "rtl/top.sv"]
top = "top"
includes = ["rtl/include"]
defines = { FEATURE = "1" }
parameters = { WIDTH = 5 }
clocks = ["clk"]
format = "legacy"
output = "build/top.cv"

[[scenario]]
name = "reset then sample"
setup = [{ inputs = { clk = 0, rst = 1 }, sample = false }]
steps = [{ inputs = { clk = 1 }, sample = true }]
```

Run `cv-gen verilog build` for structural validation and an atomic write, or `cv-gen verilog check` to compare sampled behavior with Verilator before the write. Both accept `--manifest PATH`. `check` requires explicit setup steps for each scenario; `[check] cases = 32` and `seed = 42` add deterministic cases for combinational designs. The public Python API is `cv_gen.verilog.BuildSpec`, `build(spec)`, and `check(spec)`.

In clocked scenarios, set data and control inputs while the clock is low, then raise the clock in a separate step. Changing data on the edge can give different sampling order in Verilator and CircuitVerse. Legacy builds also run a short native simulator smoke check, so an imported device with a bit width error cannot replace the output file.

The adapters preserve module hierarchy, a top block, and a connected Demo scope. `canonical-v1` runs the pinned Vue v1 importer, serializer, loader, and simulator. The legacy adapter uses the pinned engine's device classes, serializer, loader, and simulator. Both adapters lay out native components by signal flow, with registers breaking feedback for placement. Barycenter ordering reduces crossing wires; constants sit beside consumers and outputs occupy the final column. A grid router avoids component bodies, shares fanout branches, and protects pins and bends from accidental junctions. Straight crossings remain electrically separate. The legacy adapter also checks connectivity after native wire reflow and a save/load round trip. The [registered datapath](examples/registered_datapath/) passes five sampled steps in both formats. A compatibility patch keeps `clk` and `clock` as module inputs. Structural or behavioral failures leave any existing output untouched.

The [teaching CPU](examples/teaching_cpu/) includes working manifests for both formats. Import legacy `.cv` files at `https://circuitverse.org/simulator` and canonical-v1 files at `https://circuitverse.org/simulatorvue?simver=v1`; the default simulator cannot read the v1 schema.

## More complete CPU examples

- [RISC-V running C](examples/riscv/): an RV32I core, LLVM build script, startup
  code, persistent program ROM, byte RAM lanes, and a checked C demo returning 55.
- [RISC-V C raycaster](examples/riscv_graphics/): a 64 KiB memory window, RAM
  program loader, live 16×16 grayscale screen, and measured native execution.
- [CHIP-8](examples/chip8/): 4 KiB RAM, sixteen registers, call stack, timers,
  keypad, sprite XOR/collision engine, and 64×32 framebuffer with a pixel viewer.
- [LC-3](examples/lc3/): eight 16-bit registers, NZP/PSR, 64K-word RAM,
  branches, indirect loads/stores, calls, trap vectors, and a HALT handler.

These examples include legacy/v1 manifests, readable program listings, and loaders
for their RAM. Their README files explain boot controls and system boundaries.
Run their commands from the repository root. The local renderer can inspect an existing legacy project and verify native
wire reflow without synthesizing again:

```sh
uv run python tools/render_cv.py examples/chip8/build/chip8.cv \
  --scope chip8_demo --output examples/chip8/build/chip8.svg
```

Known expected program results are
checked separately from CircuitVerse/Verilator comparison. Optional larger CPU
integration tests can be run with `CVGEN_TEST_CPUS=1 uv run pytest tests/test_cpu_examples.py`.

Yosys's `pmuxtree` pass lowers one-hot selections into ordinary mux trees before
import, avoiding an upstream importer that exponentially sizes the mux. Scalar
reduction mapping also keeps internal selector buses within native element widths.
Both pinned importers map `>` and `<=` with the wrong operand order; the build pipeline
normalizes those comparisons by swapping operands and using `<`/`>=`. Mixed-width
regressions run through both simulators. Parameterized module definitions are
imported in dependency order, including children nested below another module.
The memory adapter supports zero-initialized, shared-address asynchronous RAM
with whole-word enable, and ROM banks of up to 16 eight-bit words. Clocked RAM,
masked writes, distinct read/write addresses, and nonzero RAM initialization fail
with diagnostics. The CPU wrappers write RAM during the low clock phase. Native
RAM contents are volatile; opening a generated project restores its zero state.

## Test generation

The test generator uses your local `cvgen-tests.toml` and its named oracle module.
Ports are read from your `.cv` project. For a circuit scope called `AND` with
inputs `A`, `B` and output `Y`, create this manifest:

```toml
[project]
file = "circuits/demo.cv"

[generate]
oracles = "oracles.py"
seed = 0
max_cases = 256

[[suite]]
scope = "AND"
oracle = "and"
```

Create the matching `oracles.py` beside it:

```python
from cv_gen.oracles import comb

@comb("and")
def and_gate(inputs):
    return {"Y": inputs["A"] & inputs["B"]}
```

```console
cv-gen tests scopes --deps
cv-gen tests generate
cv-gen tests run build/demo.tested.cv
cv-gen tests check
cv-gen tests csv --list
cv-gen tests csv -n cla16 -i 25 -m 1000 -s 42 out.csv
cv-gen tests push --dry-run
```

`tests generate` writes `build/<name>.tested.cv`. `tests check` generates and runs the tests with the pinned engine. `tests push` fetches the live project and verifies that only testbench data changes before upload. It requires a preview choice (`--use-default-preview` or `--preview-jpeg PATH`) and approval unless `--yes` is passed.

Shared commands use explicit project and server options:

```console
cv-gen project --server https://circuitverse.org pull --project-id ID --project-file project.cv
cv-gen auth --server https://circuitverse.org login
cv-gen auth --server https://circuitverse.org whoami
cv-gen engine status
```

The `CV_TOKEN` environment variable overrides the system keyring. Local pull records and backups live in `.cv-gen/`.

## Development

```console
uv run pytest
uv run ruff check src tests examples tools
```
