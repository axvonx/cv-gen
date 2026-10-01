"""Visible Firefox lifecycle, reference-frame and comparative performance acceptance."""

import argparse
import hashlib
import json
import statistics
import threading
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastpath.compiler import ROOT
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait


def module_file(name, file):
    spec = spec_from_file_location(name, file)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUPER_OBSERVER = """
const expected=arguments[0],target=arguments[1], controller=__cvSuperTurbo;
window.__superFrames={completed:0,errors:[],times:[],edges:[]};
__cvFastpathHost.completedFrame=frame=>{
 const r=__superFrames;if(r.completed>=target)return;
 if((frame.index&31)!==(r.completed&31))r.errors.push('frame order');
 for(let i=0;i<frame.pixels.length;i++)
  if(frame.pixels[i]!==expected[(r.completed&31)*frame.pixels.length+i]*0x010101){
   r.errors.push(`frame ${r.completed} pixel ${i}`);break;
  }
 r.times.push(frame.time);r.edges.push(frame.edges);r.completed++;
 if(r.completed>=target || r.errors.length)controller.pause();
};
controller.resume();
"""
GAPS = """
window.__fastGaps={samples:0,maxGapMs:0,gapsOver100Ms:0};
const active=__fastGaps;let previous=null;
function monitor(now){
 if(active!==window.__fastGaps)return;
 const completed=window.__frames?.completed ?? window.__superFrames?.completed ?? 0;
 if(window.__fastContinuous || completed===1){
  if(previous!==null){const gap=now-previous;active.samples++;
   active.maxGapMs=Math.max(active.maxGapMs,gap);if(gap>100)active.gapsOver100Ms++;}
  previous=now;
 }else previous=null;
 if(window.__fastContinuous || completed<2)requestAnimationFrame(monitor);
}requestAnimationFrame(monitor);
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, default=ROOT / "build/fastpath")
    parser.add_argument("--cpu", default="cpu")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--skip-benchmark", action="store_true")
    parser.add_argument("--trace-only", action="store_true")
    args = parser.parse_args()
    serve = module_file("fastpath_serve", ROOT / "tools/serve-circuitverse-fastpath.py")
    native = module_file("native_harness", ROOT / "tools/circuitverse-turbo-firefox.py")
    http = serve.server(ROOT / "build/fastpath/frontend/dist/simulatorvue/v0", args.packages, 0)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    options = webdriver.FirefoxOptions()
    options.enable_bidi = True
    options.page_load_strategy = "eager"
    driver = webdriver.Firefox(options=options)
    driver.set_page_load_timeout(45)
    driver.set_window_size(1440, 1000)
    driver.set_script_timeout(60)
    js = driver.execute_script
    wait = WebDriverWait(driver, 180, poll_frequency=0.05)
    report = {
        "firefox": driver.capabilities["browserVersion"],
        "passed": False,
        "renderingEnabled": True,
        "runs": [],
        "checks": [],
    }
    expected = list(
        (ROOT / "examples/riscv_graphics/build/animation/expected-frame.bin").read_bytes()
    )
    cpu_path = args.packages / args.cpu
    manifest = json.loads((cpu_path / "manifest.json").read_text())
    report["modelId"] = manifest["modelId"]
    report["projectSha256"] = manifest["projectSha256"]
    report["toolchain"] = manifest["toolchain"]

    def navigate(package=args.cpu):
        driver.get(f"http://127.0.0.1:{http.server_port}/simulator?fastpath=/packages/{package}/")
        wait.until(
            lambda _: js("return !!window.__cvFastpathPackage || !!window.__cvSuperTurbo?.error")
        )
        assert not js("return __cvSuperTurbo.error"), js("return __cvSuperTurbo.snapshot()")
        assert js("return __cvSuperTurbo.mode==='native' && !document.hidden")
        js(
            "const panel=document.getElementById('circuitverse-turbo-panel');"
            "if(panel)panel.style.display='none';"
        )
        js("document.querySelector('.driver-close-btn')?.click()")

    def async_js(source, *values):
        value = driver.execute_async_script(
            "const done=arguments[arguments.length-1];Promise.resolve().then(async()=>{"
            + source
            + "}).then(value=>done({value})).catch(error=>done({error:error.message}));",
            *values,
        )
        assert "error" not in value, value
        return value.get("value")

    def enable():
        return async_js(
            "await __cvSuperTurbo.setMode('super',__cvFastpathPackage);"
            "return __cvSuperTurbo.snapshot();"
        )

    def pause():
        return async_js("return await __cvSuperTurbo.pause();")

    def frames(target=2, reference=expected):
        js(SUPER_OBSERVER, reference, target)
        wait.until(
            lambda _: js(
                "return __superFrames.completed>=arguments[0] || __superFrames.errors.length "
                "|| !!__cvSuperTurbo.error",
                target,
            )
        )
        pause()
        result = js("return __superFrames")
        assert not result["errors"], result
        assert not js("return __cvSuperTurbo.error")
        return result

    def stable():
        before = js("return __cvSuperTurbo.snapshot().edges")
        time.sleep(0.12)
        assert js("return __cvSuperTurbo.snapshot().edges") == before
        return before

    try:
        driver.script.add_preload_script(function_declaration="() => {" + native.SCRIPT + "}")
        if args.trace_only:
            navigate()
            candidate = (ROOT / "tools/circuitverse-queue-experiment.js").read_text()
            fields = [p["name"] for p in manifest["ports"] if p["direction"] == "output"]
            js(
                "const script=document.createElement('script');script.textContent=arguments[0];"
                "document.head.append(script);",
                candidate + "\nwindow.__restoreQueue=circuitVerseQueueExperiment.install("
                "__cvTest.simulationArea.simulationQueue);",
            )
            observer = native.OBSERVER.replace(
                "const frame=kind===",
                """
            if (__circuitVerseTurbo.snapshot().totalEdges > 0) {
                for (const field of __nativeTrace.fields) {
                    const value=read(field);
                    if (!Number.isInteger(value)) throw new Error('undefined native port '+field);
                    __nativeTrace.hash=Math.imul(__nativeTrace.hash^value,16777619)>>>0;
                    __nativeTrace.values[__nativeTrace.edges*__nativeTrace.fields.length+
                        __nativeTrace.fields.indexOf(field)]=value;
                }
                __nativeTrace.edges++;
            }
            const frame=kind===""",
            )
            js(
                "window.__nativeTrace={fields:arguments[0],hash:2166136261,edges:0,"
                "values:new Uint32Array(100000*arguments[0].length)};",
                fields,
            )
            js(observer, expected, "cpu", 2)
            js("__cvTest.simulationArea.clockEnabled=true;__circuitVerseTurbo.setEnabled(true)")
            wait.until(lambda _: js("return __frames.completed>=2 || __frames.errors.length"))
            assert not js("return __frames.errors.length")
            trace = async_js(
                "const t=__nativeTrace;"
                "if(t.edges>100000)throw new Error('trace capacity exceeded');"
                "const bytes=t.values.buffer.slice(0,t.edges*t.fields.length*4);"
                "const digest=await crypto.subtle.digest('SHA-256',bytes);"
                "const sha256=Array.from(new Uint8Array(digest),"
                "b=>b.toString(16).padStart(2,'0')).join('');"
                "return {edges:t.edges,fields:t.fields,hash:t.hash,sha256};"
            )
            target = ROOT / "build/fastpath/native-port-trace.json"
            target.write_text(json.dumps(trace, indent=2) + "\n")
            report["passed"] = True
            print(json.dumps(trace), flush=True)
            return
        navigate()
        assert js("return __circuitVerseTurbo.snapshot().registrations") == 1, (
            "Local source build must remain recognizable by native Turbo"
        )
        enable()
        js("__cvTest.simulationArea.changeClockTime(100)")
        assert js("return __cvTest.simulationArea.ClockInterval===null")
        js("__cvTest.simulationArea.changeClockTime(50)")
        frames(33)
        assert js("return Object.values(__cvTest.nativeCounters()).every(n=>n===0)")
        report["checks"].extend(["CPU 32 frames plus wrap", "zero native propagation"])
        js("window.__fastContinuous=true;" + GAPS)
        async_js(
            "__cvSuperTurbo.resume();await new Promise(r=>setTimeout(r,2000));"
            "await __cvSuperTurbo.pause();"
        )
        report["sustainedSuperBrowserFrames"] = js("return __fastGaps")
        js("window.__fastContinuous=false;window.__fastGaps=null;")
        js("__cvSuperTurbo.resume();document.querySelector('[name=changeClockEnable]').click()")
        wait.until(lambda _: js("return !__cvSuperTurbo.running && !__cvSuperTurbo.pending"))
        stable()
        report["checks"].extend(
            ["native pause control", "period changes do not start native timer"]
        )
        before = stable()
        async_js("await __cvSuperTurbo.stepHalfEdge();")
        assert js("return __cvSuperTurbo.snapshot().edges") == before + 1
        async_js("await __cvSuperTurbo.reset();")
        assert js("return __cvSuperTurbo.snapshot().edges") == 0
        async_js(
            "await __cvTest.setInputs({run:0,load_address:0xf000,load_data:0x11223344});"
            "await __cvTest.setInputs({load_enable:1});"
            "await __cvTest.setInputs({load_enable:0,inspect:1,peek_address:0xf000});"
        )
        assert js("return __cvSuperTurbo.snapshot().outputs.peek_word") == 0x11223344
        held_pc = js("return __cvSuperTurbo.snapshot().outputs.pc")
        held_edges = js("return __cvSuperTurbo.snapshot().edges")
        js("__cvSuperTurbo.resume()")
        wait.until(lambda _: js("return __cvSuperTurbo.snapshot().edges") > held_edges)
        pause()
        assert js("return __cvSuperTurbo.snapshot().outputs.pc") == held_pc
        report["checks"].append("run hold preserves clock and loader semantics")
        async_js("await __cvSuperTurbo.reset();")
        report["checks"].extend(
            ["pause freezes edges", "one-half-edge step", "reset", "loader/inspect"]
        )

        # A real hidden tab, read through BiDi without making it visible.
        js("__cvSuperTurbo.resume()")
        first = driver.current_window_handle
        driver.switch_to.new_window("tab")
        second = driver.current_window_handle
        time.sleep(0.3)

        def hidden_state():
            result = driver.script.evaluate(
                "JSON.stringify({hidden:document.hidden,s:__cvSuperTurbo.snapshot()})",
                {"context": first},
                await_promise=False,
            )
            return json.loads(result["result"]["value"])

        hidden_before = hidden_state()
        time.sleep(0.3)
        hidden_after = hidden_state()
        assert hidden_after["hidden"]
        assert hidden_before["s"]["edges"] == hidden_after["s"]["edges"]
        driver.switch_to.window(first)
        wait.until(
            lambda _: js("return __cvSuperTurbo.snapshot().edges") > hidden_after["s"]["edges"]
        )
        pause()
        driver.switch_to.window(second)
        driver.close()
        driver.switch_to.window(first)
        report["checks"].append("real hidden-tab suspension and resume")

        js("__cvTest.layoutModeSet(true);__cvSuperTurbo.resume()")
        stable()
        js("__cvTest.layoutModeSet(false)")
        stable()
        js(
            "__cvSuperTurbo.resume();__cvTest.switchCircuit(Object.values(__cvTest.scopes()).find(s=>s.name==='rv32_graphics').id)"
        )
        pause()
        stable()
        js("__cvTest.switchCircuit(__cvFastpathPackage.manifest.display.scopeId)")
        stable()
        report["checks"].extend(["layout requires resume", "scope switch requires resume"])

        latencies = []
        for _ in range(20):
            value = async_js(
                "__cvSuperTurbo.resume();const start=performance.now();"
                "await __cvSuperTurbo.pause();return performance.now()-start;"
            )
            latencies.append(value)
        report["pauseAckMs"] = {"samples": latencies, "p95": sorted(latencies)[18]}
        assert report["pauseAckMs"]["p95"] < 50
        stable()
        js("__cvTest.errorDetectedSet(true);__cvSuperTurbo.resume()")
        assert js("return !!__cvSuperTurbo.error && !__cvSuperTurbo.running")
        async_js("await __cvSuperTurbo.setMode('native');")
        assert not js("return __cvFastpathHost.active || __cvTest.simulationArea.clockEnabled")
        js("__cvTest.errorDetectedSet(false);__cvTest.simulationArea.clockEnabled=true")
        restored_before = js("return __circuitVerseTurbo.snapshot().totalEdges")
        time.sleep(0.16)
        assert js("return !__cvFastpathHost.active && !__cvTest.errorDetectedGet()")
        restored_edges = js("return __circuitVerseTurbo.snapshot().totalEdges") - restored_before
        assert 2 <= restored_edges <= 6, restored_edges
        js("__cvTest.simulationArea.clockEnabled=false")
        report["checks"].append("error stop and native restoration")

        for package, size in [("playback16", 16), ("playback64", 64)]:
            navigate(package)
            enable()
            reference = list(
                (
                    ROOT / f"examples/riscv_graphics/build/animation-{size}/expected-frame.bin"
                ).read_bytes()
            )
            frames(33, reference)
            assert js("return Object.values(__cvTest.nativeCounters()).every(n=>n===0)")
            report["checks"].append(f"{size}x{size} playback 32 plus wrap")
        # Import while active disposes the Worker and pauses the imported project.
        js(
            "__cvSuperTurbo.resume();__cvTest.loadJSON(arguments[0])",
            (cpu_path / "project.cv").read_text(),
        )
        assert js(
            "return !__cvFastpathHost.active && !__cvSuperTurbo.worker "
            "&& !__cvTest.simulationArea.clockEnabled"
        )
        report["checks"].append("project import invalidates backend")

        for trial in range(0 if args.skip_benchmark else args.runs):
            for mode in ["insertion", "super"] if trial % 2 == 0 else ["super", "insertion"]:
                print(f"Visible Firefox trial {trial + 1}: {mode}", flush=True)
                navigate()
                js(GAPS)
                if mode == "super":
                    enable()
                    result = frames()
                    gaps = js("return __fastGaps")
                    assert js("return Object.values(__cvTest.nativeCounters()).every(n=>n===0)")
                else:
                    candidate = (ROOT / "tools/circuitverse-queue-experiment.js").read_text()
                    js(
                        "const script=document.createElement('script');"
                        "script.textContent=arguments[0];document.head.append(script);",
                        candidate + "\nwindow.__restoreQueue=circuitVerseQueueExperiment.install("
                        "__cvTest.simulationArea.simulationQueue);",
                    )
                    js(native.OBSERVER, expected, "cpu", 2)
                    js(
                        "__cvTest.simulationArea.clockEnabled=true;__circuitVerseTurbo.setEnabled(true)"
                    )
                    wait.until(
                        lambda _: js(
                            "return __frames.completed>=2 || __frames.errors.length "
                            "|| __cvTest.errorDetectedGet()"
                        )
                    )
                    raw = js("return __frames")
                    assert not raw["errors"], raw
                    result = {"times": raw["times"], "edges": raw["edgeCounts"]}
                    gaps = js("return __fastGaps")
                frame_ms = result["times"][1] - result["times"][0]
                edges = result["edges"][1] - result["edges"][0]
                report["runs"].append(
                    {
                        "trial": trial + 1,
                        "mode": mode,
                        "frameMs": frame_ms,
                        "edges": edges,
                        "edgesPerSecond": edges * 1000 / frame_ms,
                        "browserFrames": gaps,
                    }
                )
                print(f"  {frame_ms:.3f} ms, {edges} half-edges", flush=True)
                (ROOT / "build/fastpath/progress.json").write_text(json.dumps(report, indent=2))
        if report["runs"]:
            report["medianFrameMs"] = {
                mode: statistics.median(r["frameMs"] for r in report["runs"] if r["mode"] == mode)
                for mode in ["insertion", "super"]
            }
            report["speedup"] = (
                report["medianFrameMs"]["insertion"] / report["medianFrameMs"]["super"]
            )
            assert report["speedup"] >= 10
        driver.save_screenshot(str(ROOT / "build/fastpath/firefox.png"))
        report["passed"] = True
        report["method"] = (
            "Visible Firefox; same source frontend; first frame warmup, second frame timing; "
            "three alternating trials. WASM timestamps at hardware completion; native timestamps "
            "at next settled callback. Presentation coalesced at 30Hz; "
            "simulation frames are not skipped. Per-run RAF gaps sample the warmed second frame; "
            "a separate two-second Super Turbo run measures sustained responsiveness."
        )
        report["frontendSha256"] = hashlib.sha256(
            (ROOT / "build/fastpath/frontend/dist/simulatorvue/v0/simulator-v0.js").read_bytes()
        ).hexdigest()
        print(json.dumps(report, indent=2), flush=True)
    finally:
        result_file = "trace-results.json" if args.trace_only else "firefox-results.json"
        (ROOT / "build/fastpath" / result_file).write_text(json.dumps(report, indent=2) + "\n")
        driver.quit()
        http.shutdown()
        http.server_close()


if __name__ == "__main__":
    main()
