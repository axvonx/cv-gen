"""Compare native and insertion-pass queues in visible Firefox, using a local bridge.

uv run --with selenium python tools/benchmark-circuitverse-queue.py
No changes to the public simulator, saved projects or Turbo userscript.
"""

import argparse
import hashlib
import json
import statistics
import threading
import time
from http.server import ThreadingHTTPServer
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/turbo/queue"

TRACE = """
const queue=__cvTest.simulationArea.simulationQueue;
if (!queue.isEmpty()) throw Error('Trace requires an empty queue');
queue.reset();
const methods=['add','addImmediate','pop','reset','swap'];
const originals=Object.fromEntries(methods.map(name=>[name,queue[name]]));
const descriptors=Object.fromEntries(methods.map(name=>
    [name,Object.getOwnPropertyDescriptor(queue,name)]));
const ids=new WeakMap();
const trace=window.__queueTrace={capacity:queue.size,objects:[],operations:[],stats:{
    adds:0,updates:0,swaps:0,maxOccupancy:0,occupancy:{},eventTypes:{}},done:false};
const limit=arguments[0];
function identify(obj){
    if(!ids.has(obj)){
        ids.set(obj,trace.objects.length);
        trace.objects.push({delay:obj.propagationDelay,properties:{...obj.queueProperties}});
    }
    return ids.get(obj);
}
function restore(){
    methods.forEach(name=>{
        if(descriptors[name]) Object.defineProperty(queue,name,descriptors[name]);
        else delete queue[name]});
    trace.done=true;
}
function record(operation){
    trace.operations.push(operation);if(trace.operations.length>=limit) restore();
}
queue.swap=function(...args){trace.stats.swaps++;return originals.swap.apply(this,args)};
queue.add=function(obj,delay){
    const id=identify(obj), s=trace.stats;
    s.adds++;if(obj.queueProperties.inQueue) s.updates++;
    const type=obj.constructor.name;s.eventTypes[type]=(s.eventTypes[type]||0)+1;
    const n=this.frontIndex;s.maxOccupancy=Math.max(s.maxOccupancy,n);
    s.occupancy[n]=(s.occupancy[n]||0)+1;
    const result=originals.add.call(this,obj,delay);record(['add',id,delay??null]);return result;
};
queue.addImmediate=function(obj){
    const id=identify(obj),result=originals.addImmediate.call(this,obj);
    record(['addImmediate',id]);return result;
};
queue.pop=function(){const obj=originals.pop.call(this);record(['pop',identify(obj)]);return obj};
queue.reset=function(){const result=originals.reset.call(this);record(['reset']);return result};
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--mode", choices=["both", "native", "insertion"], default="both")
    parser.add_argument("--trace-operations", type=int, default=20000)
    parser.add_argument("--firefox", default="/Applications/Firefox.app/Contents/MacOS/firefox")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    spec = spec_from_file_location("harness", ROOT / "tools/circuitverse-turbo-firefox.py")
    harness = module_from_spec(spec)
    spec.loader.exec_module(harness)
    bundle = harness.OUT / (hashlib.sha256(b"/simulator-v0/simulator-v0.js").hexdigest() + ".asset")
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert digest == "4fff7c8a8f6d1bdf5ca826cdf0907ae2c0f5a77b552768fd33ff58b54fef2fe6", (
        "Unrecognized bundle: re-inspect the queue implementation before this experiment"
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), harness.Mirror)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    options = webdriver.FirefoxOptions()
    options.binary_location = args.firefox
    options.enable_bidi = True
    driver = webdriver.Firefox(options=options)
    driver.set_window_size(1440, 1000)
    js = driver.execute_script
    candidate = (ROOT / "tools/circuitverse-queue-experiment.js").read_text()

    def install_candidate():
        # execute_script's Firefox sandbox adds expensive cross-compartment
        # access to every queued object's properties. Compile in the page realm.
        js(
            "const script=document.createElement('script');script.textContent=arguments[0];"
            "document.head.append(script);script.remove();",
            candidate + "\nwindow.__restoreQueue=circuitVerseQueueExperiment.install("
            "__cvTest.simulationArea.simulationQueue);"
            "window.__queueSameRealm=Object.getPrototypeOf(__cvTest.simulationArea.simulationQueue.add)"
            "===Object.getPrototypeOf(__cvTest.simulationArea.simulationQueue.pop);",
        )
        assert js("return typeof window.__restoreQueue==='function'")
        assert js("return window.__queueSameRealm"), (
            "Candidate must share the native function realm"
        )

    report = {"bundleSha256": digest, "renderingEnabled": True, "runs": [], "passed": False}
    report["firefox"] = driver.capabilities["browserVersion"]
    report["candidateSha256"] = hashlib.sha256(candidate.encode()).hexdigest()
    cpu_ref = list(
        (ROOT / "examples/riscv_graphics/build/animation/expected-frame.bin").read_bytes()
    )

    def load(project):
        driver.get(f"http://127.0.0.1:{server.server_port}/simulator")
        WebDriverWait(driver, 60).until(
            lambda _: js("return !!window.__cvTest && !!window.globalScope")
        )
        js(
            "__cvTest.simulationArea.clockEnabled=false;__cvTest.loadJSON(arguments[0]);"
            "__cvTest.errorDetectedSet(false);__cvTest.play();",
            project.read_text(),
        )
        js("document.querySelector('.tabsbar-toggle .fa-chevron-up')?.closest('button').click()")
        WebDriverWait(driver, 10).until(
            lambda _: js("""
            const r=document.getElementById('simulationArea').getBoundingClientRect();
            return r.height>200 && r.top<innerHeight-200;
        """)
        )
        js("document.querySelector('button[title=\"Fit to Screen\"]')?.click()")
        assert js("return globalScope.name==='Demo' && !document.hidden")

    def wait_frames(target):
        last_log = 0

        def progressed(_):
            nonlocal last_log
            state = js(
                "return {completed:__frames.completed, errors:__frames.errors,"
                "fault:__cvTest.errorDetectedGet(), turbo:__circuitVerseTurbo.snapshot(),"
                "hidden:document.hidden,clockEnabled:__cvTest.simulationArea.clockEnabled}"
            )
            report["lastState"] = state
            if time.monotonic() - last_log > 10:
                last_log = time.monotonic()
                (OUT / "progress.json").write_text(json.dumps(state) + "\n")
                print(
                    f"Progress: frames={state['completed']}, "
                    f"edges={state['turbo']['totalEdges']}, {state['turbo']['status']}",
                    flush=True,
                )
            if state["completed"] < target and not state["turbo"]["enabled"]:
                raise RuntimeError(f"Turbo stopped before target: {state}")
            return state["completed"] >= target or state["errors"] or state["fault"]

        WebDriverWait(driver, 240, poll_frequency=0.2).until(progressed)
        assert not js("return __frames.errors.length || __cvTest.errorDetectedGet()")

    try:
        driver.script.add_preload_script(function_declaration="() => {" + harness.SCRIPT + "}")
        cpu = ROOT / "examples/riscv_graphics/build/cpu-animation.cv"
        if args.trace_operations:
            print("Native warm-up, then bounded queue trace", flush=True)
            load(cpu)
            js(harness.OBSERVER, cpu_ref, "cpu", 2)
            js("__cvTest.simulationArea.clockEnabled=true;__circuitVerseTurbo.setEnabled(true)")
            wait_frames(1)
            js("__cvTest.simulationArea.clockEnabled=false;__circuitVerseTurbo.setEnabled(false)")
            js(
                "const script=document.createElement('script');script.textContent=arguments[0];"
                "document.head.append(script);script.remove();",
                TRACE.replace("const limit=arguments[0];", f"const limit={args.trace_operations};"),
            )
            js("__cvTest.simulationArea.clockEnabled=true;__circuitVerseTurbo.setEnabled(true)")
            wait_frames(2)
            trace = js("return __queueTrace")
            assert trace["done"]
            (OUT / "trace.json").write_text(json.dumps(trace) + "\n")
            report["traceStats"] = trace["stats"]
            print("Trace saved (excluded from timing)", flush=True)
        for trial in range(args.runs):
            # Alternate order to reduce consistent order bias.
            modes = ["native", "insertion"] if trial % 2 == 0 else ["insertion", "native"]
            if args.mode != "both":
                modes = [args.mode]
            for mode in modes:
                print(f"CPU trial {trial + 1}: {mode}", flush=True)
                load(cpu)
                if mode == "insertion":
                    install_candidate()
                js(harness.OBSERVER, cpu_ref, "cpu", 2)
                # Existing observer only monitors gaps after two frames. Monitor
                # our warmed second frame separately; no gate instrumentation.
                js("""
                window.__queueGaps={samples:0,maxGapMs:0,gapsOver100Ms:0};
                let previous=null;const report=__frames;
                function monitor(now){
                    if(window.__frames!==report || report.completed>=2) return;
                    if(report.completed===1){
                        if(previous!==null){const gap=now-previous;__queueGaps.samples++;
                            __queueGaps.maxGapMs=Math.max(__queueGaps.maxGapMs,gap);
                            if(gap>100)__queueGaps.gapsOver100Ms++;}
                        previous=now;
                    }else previous=null;
                    requestAnimationFrame(monitor);
                }requestAnimationFrame(monitor);
                __cvTest.simulationArea.clockEnabled=true;__circuitVerseTurbo.setEnabled(true);
                """)
                wait_frames(2)
                frames = js("return __frames")
                latency = frames["times"][1] - frames["times"][0]
                edges = frames["edgeCounts"][1] - frames["edgeCounts"][0]
                row = {
                    "trial": trial + 1,
                    "mode": mode,
                    "frameMs": latency,
                    "edges": edges,
                    "edgesPerSecond": edges * 1000 / latency,
                    "browserFrames": js("return __queueGaps"),
                    "frames": frames,
                }
                report["runs"].append(row)
                print(
                    f"Verified 512 pixels; second frame {latency:.0f} ms, "
                    f"{row['edgesPerSecond']:.1f} edges/s",
                    flush=True,
                )
                if mode == "insertion":
                    js("__restoreQueue();__cvTest.simulationArea.clockEnabled=false")
        # Verify all playback frames and wraparound with the candidate as well.
        print("Verify candidate 64x64 playback: 32 frames plus wraparound", flush=True)
        load(ROOT / "examples/riscv_graphics/build/animation-64.cv")
        install_candidate()
        expected = list(
            (ROOT / "examples/riscv_graphics/build/animation-64/expected-frame.bin").read_bytes()
        )
        js(harness.OBSERVER, expected, "playback", 33)
        js("__cvTest.simulationArea.clockEnabled=true;__circuitVerseTurbo.setEnabled(true)")
        wait_frames(33)
        report["playback"] = js("return __frames")
        js("__restoreQueue()")
        report["medians"] = {
            mode: statistics.median(row["frameMs"] for row in report["runs"] if row["mode"] == mode)
            for mode in ["native", "insertion"]
            if any(row["mode"] == mode for row in report["runs"])
        }
        if args.mode == "both":
            report["speedup"] = report["medians"]["native"] / report["medians"]["insertion"]
        report["passed"] = True
        print(
            json.dumps({"medians": report["medians"], "speedup": report.get("speedup")}), flush=True
        )
    finally:
        (OUT / "results.json").write_text(json.dumps(report, indent=2) + "\n")
        try:
            driver.quit()
        finally:
            server.shutdown()


if __name__ == "__main__":
    main()
