"""Visible Firefox acceptance harness against the deployed default simulator bundle.

Run: uv run --with selenium python tools/circuitverse-turbo-firefox.py
Uses a localhost mirror with an appended test bridge (no engine code changes).
Outputs measurements and bundle SHA256 under build/turbo/. Rendering stays enabled.
"""

import argparse
import hashlib
import json
import statistics
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/turbo"
OUT.mkdir(parents=True, exist_ok=True)
SCRIPT = (ROOT / "tools/circuitverse-turbo.user.js").read_text()
ORIGIN = "https://circuitverse.org"
BRIDGE = """
window.__cvTest = {loadJSON: text=>load(JSON.parse(text)), load, simulationArea,
    switchCircuit, scopes:()=>scopeList$1,
    errorDetectedGet, errorDetectedSet, layoutModeSet, play, generateSaveData, clockTick};
"""


class Mirror(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path
        if path == "/simulator":
            data = b"""<html><head><script src="https://ajax.googleapis.com/ajax/libs/jquery/1.9.1/jquery.min.js"></script>
<script>window.logixProjectId=null;window.isUserLoggedIn=false;window.embed=false;</script>
<script type="module" src="/simulator-v0/simulator-v0.js"></script>
</head><body><div id="app"></div></body></html>"""
            mime = "text/html"
        else:
            try:
                cache = OUT / (hashlib.sha256(path.encode()).hexdigest() + ".asset")
                if not cache.exists():
                    cache.write_bytes(urllib.request.urlopen(ORIGIN + path, timeout=45).read())
                data = cache.read_bytes()
                mime = "text/javascript" if ".js" in path else "application/octet-stream"
                if path == "/simulator-v0/simulator-v0.js":
                    data += BRIDGE.encode()
            except Exception:
                self.send_error(404)
                return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


# Sample at the NEXT native scope tick, after the previous callback's full play().
# This avoids dropping intermediate frames even when Turbo batches many callbacks.
OBSERVER = """
const expected=arguments[0], kind=arguments[1], target=arguments[2];
const scope=globalScope, original=scope.clockTick;
const outputs=Object.fromEntries(scope.Output.map(p=>[p.label,p]));
const read=n=>outputs[n]?.inp1.value;
const matrix=scope.RGBLedMatrix[0], size=matrix.rows, pixels=size*size;
window.__frames={kind, target, completed:0, errors:[], times:[], started:performance.now(),
    startEdges:__circuitVerseTurbo.snapshot().totalEdges, previous:-1, edgeCounts:[],
    browserFrames:{maxGapMs:0,gapsOver100Ms:0,samples:0}};
const tracked=window.__frames;
let previousFrame=null;
function frameMonitor(now){
    if(window.__frames!==tracked) return;
    if(tracked.completed>=2 && tracked.completed<tracked.target){
        if(previousFrame!==null){
            const gap=now-previousFrame;
            tracked.browserFrames.maxGapMs=Math.max(tracked.browserFrames.maxGapMs,gap);
            if(gap>100) tracked.browserFrames.gapsOver100Ms++;
            tracked.browserFrames.samples++;
        }
        previousFrame=now;
    } else previousFrame=null;
    if(tracked.completed<tracked.target && !tracked.errors.length)
        requestAnimationFrame(frameMonitor);
}
requestAnimationFrame(frameMonitor);
scope.clockTick=function(...args){
    const report=window.__frames;
    if(__cvTest.errorDetectedGet() || (kind==='cpu' && (read('fault')!==0 || read('done')!==0))) {
        report.errors.push('CPU/simulator fault'); __cvTest.simulationArea.clockEnabled=false;
        __circuitVerseTurbo.setEnabled(false); return;
    }
    const frame=kind==='cpu'?read('result')-1:read('frame');
    const complete=kind==='cpu'?read('result')===report.completed+1:
        read('row_index')===size-1 && frame!==report.previous;
    if(complete){
        if(frame!==(report.completed&31)) report.errors.push('frame sequence: '+frame);
        const colors=matrix.colors.flat(), offset=frame*pixels;
        for(let i=0;i<pixels;i++) if(colors[i]!==expected[offset+i]*0x010101){
            report.errors.push(`pixel mismatch frame ${frame}, pixel ${i}: ${colors[i]}`); break;
        }
        report.previous=frame; report.completed++;
        report.times.push(performance.now());
        report.edgeCounts.push(__circuitVerseTurbo.snapshot().totalEdges);
        if(report.completed>=target || report.errors.length){
            report.elapsedMs=performance.now()-report.started;
            report.metrics=__circuitVerseTurbo.snapshot();
            __cvTest.simulationArea.clockEnabled=false; __circuitVerseTurbo.setEnabled(false);
        }
    }
    return original.apply(this,args);
};
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firefox", default="/Applications/Firefox.app/Contents/MacOS/firefox")
    parser.add_argument("--skip-cpu", action="store_true")
    parser.add_argument("--cpu-only", action="store_true")
    parser.add_argument("--benchmarks-only", action="store_true")
    parser.add_argument("--tampermonkey-only", action="store_true")
    parser.add_argument(
        "--normal-cpu-real-time",
        action="store_true",
        help="Use the 50 ms clock for CPU baseline (roughly an hour)",
    )
    parser.add_argument(
        "--tampermonkey-xpi", type=Path, help="Also install and verify actual Tampermonkey"
    )
    args = parser.parse_args()
    if not args.tampermonkey_only:
        # Refresh the entry bundle on every run; asset paths remain cached.
        bundle_cache = OUT / (
            hashlib.sha256(b"/simulator-v0/simulator-v0.js").hexdigest() + ".asset"
        )
        bundle_cache.write_bytes(
            urllib.request.urlopen(ORIGIN + "/simulator-v0/simulator-v0.js", timeout=45).read()
        )
    server = ThreadingHTTPServer(("127.0.0.1", 0), Mirror)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    options = webdriver.FirefoxOptions()
    options.binary_location = args.firefox
    options.enable_bidi = True
    service = Service(service_args=["--allow-system-access"] if args.tampermonkey_xpi else [])
    driver = webdriver.Firefox(options=options, service=service)
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(60)
    driver.set_window_size(1440, 1000)
    report = {
        "firefox": driver.capabilities["browserVersion"],
        "renderingEnabled": True,
        "passed": False,
    }
    result_file = OUT / (
        "tampermonkey-results.json"
        if args.tampermonkey_only
        else "cpu-results.json"
        if args.cpu_only
        else "benchmark-results.json"
        if args.benchmarks_only
        else "firefox-results.json"
    )
    js = driver.execute_script
    try:
        if args.tampermonkey_only:
            if not args.tampermonkey_xpi:
                parser.error("--tampermonkey-only requires --tampermonkey-xpi")
            report["tampermonkey"] = verify_tampermonkey(driver, args.tampermonkey_xpi)
            report["passed"] = True
            print(json.dumps(report), flush=True)
            return
        preload = driver.script.add_preload_script(function_declaration="() => {" + SCRIPT + "}")
        url = f"http://127.0.0.1:{server.server_port}/simulator"
        driver.get(url)
        WebDriverWait(driver, 60).until(
            lambda _: js("return !!window.__cvTest && !!window.globalScope")
        )
        assert js("return __circuitVerseTurbo.snapshot().registrations") == 1
        assert not js("return __circuitVerseTurbo.snapshot().enabled")
        assert js("return !document.hidden")
        report["earlyInterception"] = True
        report["scriptSha256"] = hashlib.sha256(SCRIPT.encode()).hexdigest()
        bundle = OUT / (hashlib.sha256(b"/simulator-v0/simulator-v0.js").hexdigest() + ".asset")
        report["bundleSha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()

        def load(project):
            js(
                "__circuitVerseTurbo.setEnabled(false); __cvTest.loadJSON(arguments[0]);"
                "__cvTest.errorDetectedSet(false); __cvTest.play();",
                project.read_text(),
            )
            # Collapse the native tab bar; this project has hundreds of scopes.
            # Otherwise tabs fill the viewport and the canvas cannot be seen.
            js(
                "document.querySelector('.tabsbar-toggle .fa-chevron-up')"
                "?.closest('button').click()"
            )
            WebDriverWait(driver, 10).until(
                lambda _: js("""
                const r=document.getElementById('simulationArea').getBoundingClientRect();
                return r.height>200 && r.top<innerHeight-200;
            """)
            )
            js("""document.querySelector('button[title="Fit to Screen"]')?.click()""")
            assert js("return globalScope.name") == "Demo"
            assert js("return __circuitVerseTurbo.snapshot().registrations") == 1
            assert js("return __cvTest.simulationArea.timePeriod") == 50

        playback = ROOT / "examples/riscv_graphics/build/animation-64.cv"
        expected = list(
            (ROOT / "examples/riscv_graphics/build/animation-64/expected-frame.bin").read_bytes()
        )
        cpu = ROOT / "examples/riscv_graphics/build/cpu-animation.cv"
        cpu_expected = list(
            (ROOT / "examples/riscv_graphics/build/animation/expected-frame.bin").read_bytes()
        )

        # State transitions with the actual simulator and native guards.
        load(playback)
        js("__circuitVerseTurbo.setEnabled(true)")
        WebDriverWait(driver, 10).until(
            lambda _: js("return __circuitVerseTurbo.snapshot().totalEdges>100")
        )
        saved = json.loads(js('return __cvTest.generateSaveData("Turbo verification",false)'))
        assert saved["timePeriod"] == 50
        assert saved["clockEnabled"] is True
        checks = ["saved-native-period"]
        for name, set_state, unset_state in [
            (
                "pause",
                "__cvTest.simulationArea.clockEnabled=false",
                "__cvTest.simulationArea.clockEnabled=true",
            ),
            ("layout", "__cvTest.layoutModeSet(true)", "__cvTest.layoutModeSet(false)"),
            ("error", "__cvTest.errorDetectedSet(true)", "__cvTest.errorDetectedSet(false)"),
            ("loading", "window.loading=true", "window.loading=false"),
        ]:
            before = js(set_state + "; return __circuitVerseTurbo.snapshot().totalEdges")
            time.sleep(0.55)
            assert js("return __circuitVerseTurbo.snapshot().totalEdges") == before, name
            js(unset_state)
            WebDriverWait(driver, 10).until(
                lambda _, baseline=before: (
                    js("return __circuitVerseTurbo.snapshot().totalEdges") > baseline
                )
            )
            checks.append(name)
        previous = js("return window.globalScope.id")
        other = js(
            "return Object.values(__cvTest.scopes())"
            ".find(s=>!s.Clock?.length && !s.SubCircuit?.length).id"
        )
        js("__cvTest.switchCircuit(arguments[0])", other)
        before = js("return __circuitVerseTurbo.snapshot().totalEdges")
        time.sleep(0.55)
        assert js("return __circuitVerseTurbo.snapshot().totalEdges") == before
        assert "No clock" in js("return __circuitVerseTurbo.snapshot().status")
        assert js("return window.globalScope.id") == other
        js("__cvTest.switchCircuit(arguments[0])", previous)
        checks.extend(["no-clock", "circuit-switch"])
        # Actual visibility change by selecting a second tab.
        first = driver.current_window_handle
        driver.switch_to.new_window("tab")
        driver.get("about:blank")
        driver.switch_to.window(
            first
        )  # switches visibility back, so use BiDi evaluate while second is selected
        second = next(h for h in driver.window_handles if h != first)
        driver.switch_to.window(second)

        # BiDi results are typed; use explicit primitive JSON for easy decoding.
        def hidden_snapshot():
            result = driver.script.evaluate(
                "JSON.stringify(window.__circuitVerseTurbo.snapshot())",
                {"context": first},
                await_promise=False,
            )
            return json.loads(result["result"]["value"])

        time.sleep(0.3)
        hidden_before = hidden_snapshot()
        print("Hidden-tab suspension verified", flush=True)
        time.sleep(0.6)
        hidden_after = hidden_snapshot()
        assert hidden_before["totalEdges"] == hidden_after["totalEdges"]
        assert "hidden" in hidden_after["status"]
        driver.switch_to.window(first)
        WebDriverWait(driver, 10).until(
            lambda _: (
                js("return __circuitVerseTurbo.snapshot().totalEdges") > hidden_after["totalEdges"]
            )
        )
        driver.switch_to.window(second)
        driver.close()
        driver.switch_to.window(first)
        checks.append("hidden-tab")
        # Import replaces the timer while Turbo is running; no overlapping runner.
        load(playback)
        js(
            "__circuitVerseTurbo.setEnabled(true); __cvTest.loadJSON(arguments[0])",
            playback.read_text(),
        )
        assert js("return __circuitVerseTurbo.snapshot().registrations") == 1
        checks.append("import")
        js("__cvTest.simulationArea.changeClockTime(100); __circuitVerseTurbo.setEnabled(false)")
        assert js("return __cvTest.simulationArea.timePeriod") == 100
        before = js("return __circuitVerseTurbo.snapshot().totalEdges")
        time.sleep(1)
        restored_edges = js("return __circuitVerseTurbo.snapshot().totalEdges") - before
        assert 5 <= restored_edges <= 15, restored_edges
        checks.append("restore-normal-speed")
        report["stateChecks"] = checks

        def run(project, reference, kind, turbo, target, timeout):
            load(project)
            # Pause during observer installation; starting clock state is the saved state.
            js("__cvTest.simulationArea.clockEnabled=false")
            js(OBSERVER, reference, kind, target)
            js(
                "__cvTest.simulationArea.clockEnabled=true;"
                "__circuitVerseTurbo.setEnabled(arguments[0])",
                turbo,
            )
            if kind == "cpu" and not turbo and not args.normal_cpu_real_time:
                # Untimed baseline: execute the complete native callback in yielding
                # tasks, with Turbo off. No gates, waveform or rendering are patched.
                js("""clearInterval(__cvTest.simulationArea.ClockInterval);
                    function nativeBatch(){
                        const start=performance.now();
                        while(__frames.completed<__frames.target && !__frames.errors.length
                            && performance.now()-start<8) __cvTest.clockTick();
                        if(__frames.completed<__frames.target && !__frames.errors.length)
                            setTimeout(nativeBatch,0);
                    } setTimeout(nativeBatch,0);""")
            WebDriverWait(driver, timeout, poll_frequency=0.25).until(
                lambda _: js(
                    "return __frames.completed>=__frames.target || __frames.errors.length"
                    " || __cvTest.errorDetectedGet()"
                    " || __circuitVerseTurbo.snapshot().status.startsWith('Turbo stopped:')"
                )
            )
            result = js("return __frames")
            assert not js("return __cvTest.errorDetectedGet()"), "native simulator error"
            assert not js(
                "return __circuitVerseTurbo.snapshot().status.startsWith('Turbo stopped:')"
            )
            assert not result["errors"], result["errors"]
            assert result["completed"] == target
            return result

        speedup = None
        if not args.cpu_only and not args.benchmarks_only:
            report["playback"] = {}
            for mode in [False, True]:
                label = "turbo" if mode else "normal"
                print(f"Verify 33 playback frames: {label}", flush=True)
                result = run(playback, expected, "playback", mode, 33, 360)
                report["playback"][label] = result
                print(
                    f"Verified {result['completed']} frames in {result['elapsedMs'] / 1000:.2f}s",
                    flush=True,
                )
        if not args.cpu_only:
            report["benchmarks"] = {}
            for mode in [False, True]:
                label = "turbo" if mode else "normal"
                runs = []
                for index in range(3):
                    result = run(playback, expected, "playback", mode, 5, 90)
                    # First two completed frames warm up; time the next three intervals.
                    intervals = [
                        b - a
                        for a, b in zip(result["times"][1:4], result["times"][2:5], strict=True)
                    ]
                    frame_ms = statistics.median(intervals)
                    runs.append(
                        {
                            "medianFrameMs": frame_ms,
                            "edgesPerSecond": (result["edgeCounts"][4] - result["edgeCounts"][1])
                            * 1000
                            / (result["times"][4] - result["times"][1]),
                            "maxFrameGapMs": result["browserFrames"]["maxGapMs"],
                            "frameGapsOver100Ms": result["browserFrames"]["gapsOver100Ms"],
                        }
                    )
                    print(f"Benchmark {label} {index + 1}: {frame_ms:.2f} ms/frame", flush=True)
                report["benchmarks"][label] = {
                    "runs": runs,
                    "medianFrameMs": statistics.median(r["medianFrameMs"] for r in runs),
                }
            speedup = (
                report["benchmarks"]["normal"]["medianFrameMs"]
                / report["benchmarks"]["turbo"]["medianFrameMs"]
            )
            report["speedup"] = speedup
            assert speedup >= 2, speedup
        if not args.skip_cpu and not args.benchmarks_only:
            report["cpu"] = {}
            for mode in [False, True]:
                label = "turbo" if mode else "normal"
                print(f"Verify two CPU frames: {label}", flush=True)
                # Normal clock needs around an hour; allow it explicitly.
                report["cpu"][label] = run(cpu, cpu_expected, "cpu", mode, 2, 9000)
                report["cpu"][label]["scheduling"] = (
                    "50 ms native"
                    if not mode and args.normal_cpu_real_time
                    else "untimed native callback"
                    if not mode
                    else "Turbo pump"
                )
                print(f"Verified two CPU frames: {label}", flush=True)
        driver.save_screenshot(str(OUT / "firefox.png"))
        if args.tampermonkey_xpi:
            driver.script.remove_preload_script(preload["script"])
            report["tampermonkey"] = verify_tampermonkey(driver, args.tampermonkey_xpi)
        report["passed"] = True
        result_file.write_text(json.dumps(report, indent=2))
        print(
            json.dumps({"speedup": speedup, "report": str(result_file)}),
            flush=True,
        )
    except Exception as error:
        report["failure"] = str(error)
        raise
    finally:
        # Keep partial results when an assertion or external dependency fails.
        result_file.write_text(json.dumps(report, indent=2))
        driver.quit()
        server.shutdown()


def verify_tampermonkey(driver, xpi):
    """Install the signed addon and userscript through Tampermonkey's real editor."""
    driver.install_addon(str(xpi.resolve()), temporary=True)
    driver.set_context("chrome")
    uuids = json.loads(
        driver.execute_script(
            'return Services.prefs.getStringPref("extensions.webextensions.uuids")'
        )
    )
    driver.set_context("content")
    driver.get(
        f"moz-extension://{uuids['firefox@tampermonkey.net']}/options.html#nav=new-user-script"
    )
    WebDriverWait(driver, 30).until(
        lambda _: driver.execute_script(
            'return !!document.querySelector(".CodeMirror")?.CodeMirror'
        )
    )
    driver.execute_script(
        'document.querySelector(".CodeMirror").CodeMirror.setValue(arguments[0])', SCRIPT
    )
    # Editor toolbar's save button is selected by title, verified during setup.
    driver.execute_script("""document.querySelector('button[title="Save"]').click()""")
    driver.get(ORIGIN + "/simulator")
    WebDriverWait(driver, 60).until(
        lambda _: driver.execute_script(
            "return !!window.__circuitVerseTurbo && !!window.globalScope"
        )
    )
    state = driver.execute_script("return __circuitVerseTurbo.snapshot()")
    assert state["registrations"] == 1 and state["status"] == "Normal speed", state
    driver.execute_script("""document.getElementById('circuitverse-turbo-panel')
        .shadowRoot.getElementById('toggle').click()""")
    WebDriverWait(driver, 10).until(
        lambda _: driver.execute_script("return __circuitVerseTurbo.snapshot().enabled")
    )
    driver.execute_script("""document.getElementById('circuitverse-turbo-panel')
        .shadowRoot.getElementById('toggle').click();
        document.getElementById('circuitverse-turbo-panel')
        .shadowRoot.getElementById('collapse').click();""")
    assert driver.execute_script("""return document.getElementById('circuitverse-turbo-panel')
        .shadowRoot.getElementById('body').hidden""")
    driver.execute_script("__circuitVerseTurbo.showPanel()")
    assert (
        driver.execute_script("""return document.getElementById('circuitverse-turbo-panel')
        .shadowRoot.getElementById('collapse').getAttribute('aria-label')""")
        == "Collapse panel"
    )
    assert not driver.execute_script("""return document.getElementById('circuitverse-turbo-panel')
        .shadowRoot.getElementById('body').hidden""")
    driver.save_screenshot(str(OUT / "tampermonkey.png"))
    return {"installed": True, "earlyInterception": True, "state": state}


if __name__ == "__main__":
    main()
