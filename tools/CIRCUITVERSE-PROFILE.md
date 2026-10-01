# Live CPU renderer: first Firefox profile

The main bottleneck is CircuitVerse's **event queue**, rather than drawing or
Turbo's scheduling. This is the live C renderer in `cpu-animation.cv`, with Demo
selected and its 16×16 matrix visible. Turbo and native rendering stayed enabled.
No simulator or userscript performance changes were made.

Firefox 157.0 sampled the content main thread at a 1 ms interval for 15.018 seconds,
after the first completed CPU frame. The capture contains 15,042 samples. Both
completed frames passed all 512 C-reference pixels and CPU/simulator fault checks.

## Where the main thread spends time

These call paths are mutually exclusive shares of the selected thread's samples:

| Call path | Sample share |
| --- | ---: |
| Native simulation: `play` and propagation beneath it | 96.30% |
| Canvas drawing | 1.94% |
| Clock toggling outside `play` | 0.67% |
| Other browser/native work | 0.47% |
| Turbo and test-harness bookkeeping | 0.37% |
| Other simulator work | 0.15% |
| Waveform call path | 0.08% |
| Idle | 0.01% |

Within the simulator, attributing each sample to its innermost simulator JavaScript
frame identifies these hot functions. The numbers below overlap with the broad
`play` call path above; **do not add the two tables together**.

| Function | Sample share | Interpretation |
| --- | ---: | --- |
| `EventQueue.add` | 53.79% | Insert events or reposition already queued events |
| `Node.resolve` | 13.57% | Propagate values through connections |
| `EventQueue.swap` | 12.10% | Reorder the array and update queued-object indices |
| `play` itself | 7.05% | Simulation loop outside sampled callees |
| `EventQueue.pop` | 2.17% | Remove the next event |
| `SubCircuit.addInputs` | 1.94% | Queue hierarchy inputs |
| `Splitter.resolve` | 1.30% | Split/join signal bits |

Queue insertion, swaps, and pops together account for **68.06%**. Function
identities were checked against their exact line/UTF-16 column in the deployed
bundle, whose SHA256 is recorded in the accompanying results JSON.

The deployed queue maintains a sorted array. Insertion and priority changes move
an event through neighboring entries by repeatedly swapping. This makes queue
ordering the strongest next optimization candidate for this circuit.

## What to try next

The first source-guided experiment is now measured: preserving the sorted array
while replacing repeated swaps with an insertion pass reduced median live CPU
frame time from 22.463 seconds to 13.970 seconds in three trials per mode.
See [queue experiment and verification](CIRCUITVERSE-QUEUE.md). This remains a
local engine experiment; the installed Turbo userscript has not changed.

Reprofile that candidate, then consider an indexed priority queue and compare it
against the existing queue using the same simulation edge traces and reference
frames. Preserve equal-time ordering, updates to already queued priorities, object
queue indices, reset behavior, and contention/error handling. Changing ordering
without these checks can change circuit behavior even when a frame looks plausible.

This is an engine experiment, beyond the scheduling-only Turbo userscript.
Improving the userscript's batch size does not remove the work inside `play`.
Disabling drawing would target only a small fraction of this main-thread profile.
An indexed heap or bucket queue has not been benchmarked yet.

This capture does not determine what percentage of C instructions is spent writing
pixels. CPU-generated column profiles remain a separate architectural experiment:
reducing instruction count could also reduce how many propagation events are needed.

## Inspect and reproduce

The full profile is `build/turbo/profile/cpu-firefox.json.gz`. Open
[Firefox Profiler](https://profiler.firefox.com/) and load the local file. It was
captured in a temporary Firefox profile and has not been uploaded or published.
Select the `127.0.0.1` content track and the **Script** view to inspect JavaScript
stacks. Use **Invert call stack** to bring the hot leaf functions to the top. The
compressed file was successfully imported into Firefox Profiler.
The raw summary and native simulator screenshot are beside it. Firefox's
[profile format documentation](https://github.com/firefox-devtools/profiler/blob/main/docs-developer/gecko-profile-format.md)
describes the stack, frame, and sample tables used by the summary parser.

Capture again with the reference projects already built:

```sh
uv run --with selenium python tools/profile-circuitverse.py
```

The tool imports the native default bundle through the existing localhost test
mirror, verifies the first frame, measures a five-second unprofiled interval,
captures fifteen seconds of sampled stacks, then verifies the second frame.
It enables Firefox's native profiler through an isolated automation session.
`--firefox` selects a different Firefox binary. If this machine finishes a frame
before the capture, shorten `--baseline-seconds` and `--seconds`.

Reanalyze without launching a browser or installing Selenium:

```sh
uv run python tools/profile-circuitverse.py \
  --analyze build/turbo/profile/cpu-firefox.json.gz
uv run pytest -o addopts='' tests/test_turbo_profile.py
```

The five-second baseline measured **1,606.7 edges/s** and the sampled interval
**1,461.7 edges/s**. They cover different parts of the frame; their difference
includes workload variation and profiler overhead. Do not treat it as a measured
profiler-overhead percentage or a new completed-frame benchmark.

These results describe one warmed-up region on this machine. Percentages cover
the content main thread, not every browser or GPU thread. Innermost-JS attribution
includes native work beneath that frame; inclusive stack shares overlap.

[Machine-readable results](circuitverse-profile-results.json) retain source hashes,
function locations, sample counts, validation, and these limitations.
