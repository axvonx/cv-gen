# CircuitVerse queue experiment

This is a local engine experiment, separate from the scheduling-only Turbo
userscript. It replaces repeated adjacent swaps during insertion with a pass
that shifts displaced entries, updates their indices once, and places the moving
object once. It retains the native sorted-array representation and linear
insertion complexity.

The initial Firefox profile attributed 68.06% of content-main-thread samples to
queue add/swap/pop operations. A bounded native CPU trace contained 20,000 queue
operations, 10,414 adds (751 updates), and about 9.90 swaps per add. Queue occupancy
at add averaged 151.64 and peaked at 397. The trace was collected separately from
timed runs, after the first verified CPU frame. Its event stream is available at
`build/turbo/queue/trace.json`.

## Measured result

Three visible Firefox 157.0 trials per mode measured the second completed CPU
frame after warm-up, with Turbo enabled in both modes:

| Queue | Frame times (ms) | Median (ms) | Median edges/s |
| --- | --- | ---: | ---: |
| Native adjacent swaps | 22,556 / 22,193 / 22,463 | 22,463 | 1,609.3 |
| Insertion pass | 14,414 / 13,941 / 13,970 | 13,970 | 2,587.7 |

The candidate was **1.608× faster**, reducing median frame time by **37.81%**.
Every measured frame executed 36,150 edges. All six CPU runs checked their first
two frames against the C reference (3,072 pixel comparisons total), with no CPU
or simulator faults. The candidate's 33 playback frames passed all 135,168 pixel
comparisons. Measured second-frame browser gaps peaked below 86 ms, with none
over 100 ms, in both modes. These measurements describe this machine and circuit;
they do not establish a general simulator speedup or a browser frame-rate guarantee.

[Machine-readable results](circuitverse-queue-results.json) retain individual
trials, hashes, trace statistics and validation limits.

## Behavior preserved

- The earliest simulation timestamp is popped first. Newly inserted equal-time
  events precede older equal-time events when popped.
- Updating an already queued object moves it using strict comparisons, retaining
  the native position among ties. Both directions of movement are supported.
- Object queue membership, indices, queue time, default delays (including native
  zero-delay fallback), capacity errors and reset behavior are retained.
- Native `addImmediate()` permits duplicates and bypasses sorting. If it introduces
  aliases, the prototype uses original insertion until reset. No callers of this
  method were found in the inspected simulator source.
- Restoring the experiment restores exact own method descriptors, or deletes
  temporary own methods to recover inherited methods.

The differential tests use CircuitVerse's original queue at commit
`6f725c5a924dc0b73527215eb5aa0618e45330e1` as an oracle. The fixture retains its
upstream MIT license. Tests cover 80,000 seeded operations and replay the captured
native stream, comparing pop results, queue times/order, membership and indices.

## Reproduce

The graphics reference projects must already be built. Run:

```sh
node --test tests/circuitverse-queue.test.cjs
uv run --with selenium python tools/benchmark-circuitverse-queue.py
CV_QUEUE_TRACE=build/turbo/queue/trace.json \
  node --test tests/circuitverse-queue.test.cjs
```

The harness uses a temporary visible Firefox profile and the existing local mirror
of the deployed simulator. It checks the inspected bundle hash before applying
the experiment. Rendering remains enabled. It warms each trial through frame one,
measures frame two, alternates native/candidate order over three trials, and
checks all 512 pixels in the CPU renderer's first two frames and native faults.
It also verifies all 32 64×64 playback frames plus wraparound with the candidate.

Use `--trace-operations 0` to omit trace capture, `--runs` to change trial count,
and `--mode native` or `--mode insertion` for a single implementation. Results
and browser-frame gaps are saved to `build/turbo/queue/results.json`.

The replacement is compiled through a script element in the page's own JavaScript
context. Compiling a hot replacement with Selenium `execute_script` creates
cross-compartment accesses in Firefox and invalidates the performance comparison.
Early trials using that approach were discarded. The final harness checks that
the replacement and native queue methods share a function prototype.

## Scope and next experiments

### Reprofile of the insertion pass

An 8-second, 1 ms Gecko sampling capture after warm-up attributed **48.33%** of
content-main-thread samples to insertion-pass `add`, **21.00%** to `Node.resolve`,
**11.68%** to `play` outside sampled callees, **3.39%** to `SubCircuit.addInputs`,
and **3.09%** to `pop`. Queue insertion remains the largest sampled cost. Both
completed CPU frames passed all 512 reference pixels and fault checks again.

The queue script was served as a separate local JavaScript resource, in the same
realm as native queue methods. An initial inline-script capture was discarded
for hotspot decisions because Firefox did not label queue frames separately;
excluding those frames incorrectly attributed their cost to native callers.
The summary parser now includes the separately served experiment in simulator
stacks, and capture rejects missing candidate frames.

```sh
uv run --with selenium python tools/profile-circuitverse.py \
  --queue insertion --seconds 8 --baseline-seconds 2 \
  --out build/turbo/profile/insertion-external
```

[Reprofile results](circuitverse-queue-profile-results.json) preserve counts,
hashes and limitations. The raw profile remains local at the recorded path and
can be opened in Firefox Profiler. The capture length and frame region differ
from the original profile; percentage changes are not exact function speedups.

The next queue experiment should compare timestamp buckets and an indexed heap
against the native trace oracle. Timestamp buckets may avoid shifting when many
events share times; an indexed heap may help large queues. Neither is assumed to
preserve native ties or priority-update ordering without differential verification.
Replaying this bounded trace found an average of 1.99 distinct queued timestamps
at insertion and a maximum of two, despite average occupancy of 151.64 events.
Effective insertion delays were zero (8,379 adds) or ten (2,035 adds); 746 of 751
priority updates retained the same timestamp, and five moved later. This makes
timestamp buckets the first candidate for this workload. The trace does not cover
every frame or project, so tests must also cover movement to earlier times and
different delay distributions.
After queue work, examine parent-gate resolvability checks and connection fan-out
inside `Node.resolve`, followed by the amount of work needed per rendered frame.

This prototype does not modify the public simulator, the installed userscript or
saved circuit contents. It is not yet a supported public-page accelerator. The
local test bridge supplies the private queue reference; delivering this change
requires either a simulator build containing the change or a separately verified
way to reach that reference on the public page.

The captured replay and reference frames do not prove equivalence for every
CircuitVerse project. Dedicated contention/error and waveform regression circuits,
control integration checks and further profiles remain necessary before deployment.

Insertion remains dominant in the reprofile. Next, evaluate an indexed
heap or timestamp buckets against the captured workload. A simple heap tie breaker
is not assumed equivalent to native reprioritization. Larger rendering gains can
also come from reducing CPU instructions and propagation events, for example a
column-span display circuit rather than individual pixel stores.
