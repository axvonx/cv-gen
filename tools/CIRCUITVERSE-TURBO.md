# CircuitVerse Turbo for Firefox

[Installable userscript](circuitverse-turbo.user.js) for Firefox with Tampermonkey,
on CircuitVerse's default <https://circuitverse.org/simulator> page. It changes
runtime scheduling only. Projects, saved clock periods, gate propagation, waveform
recording, and the simulator's drawing scheduler keep their native behavior.

## Install

1. Install [Tampermonkey for Firefox](https://addons.mozilla.org/firefox/addon/tampermonkey/).
2. In Tampermonkey's dashboard, choose **Create a new script**. Replace the entire
   editor contents with `tools/circuitverse-turbo.user.js`, then **File → Save**.
3. Reload the simulator. The panel should show **Normal speed** and **Turbo off**.
   Load your project normally; enable Turbo using the bottom-right panel.

Keep the metadata's `document-start`, `raw` sandbox, and `unsafeWindow` grant.
Early interception is necessary: installing into an already running page requires
a reload. There are no dependencies or external scripts in the userscript.

## Use

- **Turbo off** is the default on every page load. Click it to turn Turbo on.
- The native clock-period field continues to show the project's normal interval.
  That period does **not** describe the accelerated interval while Turbo is active.
  Turning Turbo off restores scheduling at the latest registered native interval.
- Ordinary clock pause, layout mode, and simulator errors still stop clock edges.
  Turbo follows the selected circuit, including clocks inside its subcircuits.
- The panel shows accepted edges/second, mean accepted tick time, and the current
  batch budget. One native callback executes one complete simulation edge.
- **−** collapses the panel; **+** restores it. Tampermonkey also provides
  **Toggle CircuitVerse Turbo** and **Restore Turbo panel** menu actions.
- Turbo favors throughput and can increase CPU use. It yields every 8 ms or 256
  callbacks, whichever comes first. Repeated animation-frame gaps above 100 ms
  reduce the budget toward 2 ms; sustained recovery restores it toward 8 ms.
  One expensive native tick cannot be interrupted.

## Status messages

| Status | Meaning |
| --- | --- |
| Normal speed | The native registered interval is running; Turbo is off. |
| Turbo running | Complete native callbacks are being pumped sequentially. |
| Suspended: hidden tab | Turbo's clock runner is stopped. Visibility resumes it with fresh measurements and no catch-up. |
| Loading | No continuous pumping; checks every 250 ms. |
| No clock in selected circuit | No clocks in this scope or its subcircuits; checks every 250 ms. |
| Native pause / layout mode / simulator error | The native callback did not accept a clock edge; checks every 250 ms. |
| Slow simulation tick; yielding | A tick took over 100 ms; the batch ended immediately. |
| Reload required | Initialization may have happened before the hook; reload the page. |
| Unsupported: clock hook not found | No inspected callback was intercepted. Timing remains native. |
| Unsupported: ambiguous clock registrations | Multiple recognized registrations exist. Turbo is off and all use native timing. |
| Turbo stopped: … | An unexpected accelerator error restored native scheduling. Reload before trying Turbo again. |

The first release supports Firefox's default `/simulator` route only. Vue v1,
embeds, and Chromium are unsupported. The default page currently uses a Vue shell
around the native simulator; that shell is supported. Recognition uses the
inspected callback name and its clock, waveform, simulation, drawing and guard
markers, never the interval's delay alone. Future incompatible callbacks fail
closed. If another extension replaces timers after this script, disable that
extension and reload before diagnosing a missing hook.

## Reproduce verification

Fast deterministic browser timer/task tests:

```sh
node --test tests/circuitverse-turbo.test.cjs
```

Generate the reference projects if missing (requires the tools described in
[the graphics example](../examples/riscv_graphics/README.md)):

```sh
uv run python examples/riscv_graphics/animate.py
uv run python examples/riscv_graphics/animate.py --size 64 --playback-only
```

Visible Firefox integration, reference comparisons, and three benchmark runs per
mode, with native rendering enabled:

```sh
uv run --with selenium python tools/circuitverse-turbo-firefox.py
```

The harness mirrors the deployed default bundle to localhost and appends a test
bridge to expose its existing functions. It injects the unchanged userscript into
the page context using Firefox WebDriver BiDi before page scripts run. It records
the deployed bundle hash, Firefox version, pause/layout/error/loading checks,
circuit switching, imports, real hidden-tab suspension, restoration, all 32
64×64 C-reference frames plus wraparound, and the CPU's first two reference frames.
No simulator logic is replaced. Frame sampling occurs at the following scope tick,
after the previous full native simulation has finished, so batches cannot hide
intermediate completed frames.

The playback benchmark uses two completed frames for warm-up, then measures three
frame intervals in each of three runs per mode. Its acceptance threshold is a
normal/Turbo median frame-latency ratio of at least 2. Measurements apply to this
machine and circuit; there is no promise of a 1 ms interval or video frame rate.

The CPU baseline is **untimed**: Turbo is off and the complete native callback is
called in yielding tasks to verify pixels without an hour-long wait. CPU Turbo
uses the actual userscript pump. For a literal 50 ms native-clock CPU baseline,
add `--normal-cpu-real-time` (allow roughly an hour). `--skip-cpu` runs playback
only, and `--cpu-only` runs state checks and CPU comparisons without playback
benchmarks.

Actual signed Tampermonkey installation and early interception are a separate
check, not inferred from page injection. Download its signed Firefox `.xpi` from
Mozilla, then run:

```sh
uv run --with selenium python tools/circuitverse-turbo-firefox.py \
  --tampermonkey-only --tampermonkey-xpi /path/to/tampermonkey.xpi
```

This creates a temporary Firefox profile, installs the addon, saves the exact
userscript through Tampermonkey's editor, and verifies early interception and
on/off controls on the public simulator. Your everyday Firefox profile is not
changed. `--firefox /path/to/firefox` selects a different Firefox binary.
`--benchmarks-only` repeats the benchmark and state checks without the full frame
scans or CPU runs. Generated JSON reports, cached assets, and screenshots live in
`build/turbo/`.

## Measured results

Verified in visible Firefox **157.0** with Tampermonkey **5.5.0**. The final
benchmark used the native collapsed tab bar and Fit to Screen control so the
64×64 matrix was visible. Drawing remained enabled.

| Mode | Three run medians (ms/frame) | Median (ms/frame) | Median measured edges/s | Largest measured browser frame gap |
| --- | --- | --- | --- | --- |
| Normal | 6,722 / 6,726 / 6,758 | 6,726 | 19.1 | 17.68 ms |
| Turbo | 60 / 60 / 61 | 60 | 2,064.5 | 66.68 ms |

Turbo reduced median frame latency by **112.1×** in this playback benchmark,
exceeding the required 2× threshold. Neither mode had a browser animation-frame
gap above 100 ms during the measured regions. These are circuit-specific local
results, not guaranteed performance.

Both modes matched all **32 frames plus wraparound**: 135,168 pixels per mode.
The CPU's first **two frames** matched all 512 reference pixels, with no CPU or
simulator faults, in both the untimed native baseline and the Turbo pump. The
literal 50 ms CPU baseline was not run. Turbo's two CPU frames took 54.14 seconds;
the untimed baseline took 87.30 seconds (not a normal-speed latency benchmark).

All 13 deterministic tests passed. Firefox integration passed saved-period,
processed pause/resume, layout, loading, error, no-clock, circuit-switching,
import/replacement, hidden-tab, and normal-speed restoration checks. Actual signed
Tampermonkey installation captured one native registration early, started off,
and passed panel toggle/collapse/restore checks. The only subsequent userscript
change corrected the restore button's accessible label; its final installation
and controls were checked again.

[Machine-readable verification summary](circuitverse-turbo-results.json) includes
the deployed bundle hash, source hashes, and per-run measurements. Raw reports
and screenshots remain in `build/turbo/`.

## Profiling the live renderer

The [first CPU profile](CIRCUITVERSE-PROFILE.md) identifies the native event queue
as the main optimization target. Use `tools/profile-circuitverse.py` to capture
local Firefox sampling profiles with the CPU frame-reference checks enabled.
