"""Capture a local Gecko sampling profile of the live CircuitVerse CPU renderer.

uv run --with selenium python tools/profile-circuitverse.py
Uses a temporary visible Firefox profile and the acceptance harness's native bundle
mirror. --queue insertion applies the local queue experiment in the page context.
Does not upload profiles or modify the public simulator or installed userscript.
"""

import argparse
import collections
import gzip
import hashlib
import importlib.util
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/turbo/profile"


def load_harness():
    spec = importlib.util.spec_from_file_location(
        "turbo_firefox", ROOT / "tools/circuitverse-turbo-firefox.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def all_threads(profile):
    yield from profile.get("threads", [])
    for process in profile.get("processes", []):
        yield from all_threads(process)


def summarize(profile, capture_ms):
    """Count leaf JS and inclusive stacks on simulator content-main threads.

    Sampling percentages are shares of the selected thread's samples, not exact
    function timings. Inclusive shares overlap; leaf-JS attribution includes native
    work beneath that JS frame. Preserve full profiles for the browser profiler.
    """
    result = {"threads": [], "captureMs": capture_ms}
    for thread in all_threads(profile):
        strings = thread.get("stringTable", [])
        if thread.get("name") != "GeckoMain" or not any(
            "/simulator-v0/simulator-v0.js" in value for value in strings
        ):
            continue
        frames = thread["frameTable"]
        stacks = thread["stackTable"]
        samples = thread["samples"]
        f_schema, s_schema, p_schema = frames["schema"], stacks["schema"], samples["schema"]
        memo = {}

        def get_stack(
            index,
            memo=memo,
            stacks=stacks,
            frames=frames,
            s_schema=s_schema,
            strings=strings,
            f_schema=f_schema,
        ):
            if index is None:
                return ()
            if index in memo:
                return memo[index]
            chain = []
            while index is not None and index not in memo:
                entry = stacks["data"][index]
                frame = frames["data"][entry[s_schema["frame"]]]
                location = strings[frame[f_schema["location"]]]
                category_index = f_schema.get("category")
                category = (
                    frame[category_index]
                    if category_index is not None and category_index < len(frame)
                    else None
                )
                chain.append((index, location, category))
                index = entry[s_schema["prefix"]]
            prefix = memo.get(index, ())
            for stack_id, location, category in reversed(chain):
                prefix = (*prefix, (location, category))
                memo[stack_id] = prefix
            return prefix

        leaf = collections.Counter()
        inclusive = collections.Counter()
        categories = collections.Counter()
        branches = collections.Counter()
        total = active = simulator_js = 0
        category_names = profile["meta"]["categories"]
        for sample in samples["data"]:
            total += 1
            stack = get_stack(sample[p_schema["stack"]])
            if not stack:
                categories["No stack"] += 1
                branches["No stack"] += 1
                continue
            category = next(
                (category for _, category in reversed(stack) if category is not None), None
            )
            name = category_names[category]["name"] if category is not None else "Unknown"
            categories[name] += 1
            if name != "Idle":
                active += 1
            js_frames = [
                location
                for location, _ in stack
                if "/simulator-v0/simulator-v0.js" in location
                or "circuitverse-queue-experiment.js" in location
            ]
            script_frames = [
                location
                for location, _ in stack
                if ".user.js" in location
                or "circuitVerseTurbo" in location
                or "/simulator:" in location
            ]
            if js_frames:
                simulator_js += 1
                leaf[js_frames[-1]] += 1
                inclusive.update(set(js_frames))
                # Mutually exclusive attribution to broad outer call paths.
                if any(location.startswith("play (") for location in js_frames):
                    branches["Native play / propagation"] += 1
                elif any(
                    "renderCanvas" in location or "draw (" in location for location in js_frames
                ):
                    branches["Canvas drawing"] += 1
                elif any(
                    "plot" in location.lower() or "nextCycle" in location for location in js_frames
                ):
                    branches["Waveform"] += 1
                elif any("clockTick" in location for location in js_frames):
                    branches["Clock toggling outside play"] += 1
                else:
                    branches["Other simulator work"] += 1
            elif script_frames:
                branches["Turbo / test harness bookkeeping"] += 1
            elif name == "Idle":
                branches["Idle"] += 1
            else:
                branches["Other browser / native work"] += 1

        def top(counter, limit=25, total=total):
            return [
                {"function": name, "samples": count, "percentOfThreadSamples": 100 * count / total}
                for name, count in counter.most_common(limit)
            ]

        result["threads"].append(
            {
                "name": thread["name"],
                "pid": thread.get("pid"),
                "processType": thread.get("processType"),
                "samples": total,
                "nonIdleSamples": active,
                "samplesWithSimulatorJS": simulator_js,
                "categories": dict(categories),
                "branches": top(branches),
                "leafSimulatorJS": top(leaf),
                "inclusiveSimulatorJS": top(inclusive),
            }
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firefox", default="/Applications/Firefox.app/Contents/MacOS/firefox")
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument(
        "--analyze", type=Path, help="Summarize a saved profile without launching Firefox"
    )
    parser.add_argument("--baseline-seconds", type=float, default=5)
    parser.add_argument("--queue", choices=["native", "insertion"], default="native")
    parser.add_argument(
        "--out", type=Path, help="Directory for the profile, summary and screenshot"
    )
    args = parser.parse_args()
    if args.analyze:
        opener = gzip.open if args.analyze.suffix == ".gz" else open
        with opener(args.analyze, "rt") as file:
            print(json.dumps(summarize(json.load(file), None), indent=2))
        return
    from selenium import webdriver
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.support.ui import WebDriverWait

    out = args.out or (OUT / "insertion" if args.queue == "insertion" else OUT)
    out.mkdir(parents=True, exist_ok=True)
    harness = load_harness()
    bundle_path = "/simulator-v0/simulator-v0.js"
    bundle = harness.OUT / (hashlib.sha256(bundle_path.encode()).hexdigest() + ".asset")
    bundle.write_bytes(urllib.request.urlopen(harness.ORIGIN + bundle_path, timeout=45).read())

    class ProfileMirror(harness.Mirror):
        def do_GET(self):
            if self.path != "/circuitverse-queue-experiment.js":
                return super().do_GET()
            data = (ROOT / "tools/circuitverse-queue-experiment.js").read_bytes()
            data += b"""
window.__restoreQueue=circuitVerseQueueExperiment.install(__cvTest.simulationArea.simulationQueue);
window.__queueSameRealm=Object.getPrototypeOf(__cvTest.simulationArea.simulationQueue.add)
    ===Object.getPrototypeOf(__cvTest.simulationArea.simulationQueue.pop);
"""
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript")
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), ProfileMirror)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    options = webdriver.FirefoxOptions()
    options.binary_location = args.firefox
    options.enable_bidi = True
    driver = webdriver.Firefox(
        options=options, service=Service(service_args=["--allow-system-access"])
    )
    driver.set_window_size(1440, 1000)
    driver.set_script_timeout(120)
    driver.set_page_load_timeout(60)
    js = driver.execute_script
    result = {
        "firefox": driver.capabilities["browserVersion"],
        "bundleSha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "userscriptSha256": hashlib.sha256(harness.SCRIPT.encode()).hexdigest(),
        "renderingEnabled": True,
        "queueImplementation": args.queue,
        "passed": False,
    }
    try:
        driver.script.add_preload_script(function_declaration="() => {" + harness.SCRIPT + "}")
        driver.get(f"http://127.0.0.1:{server.server_port}/simulator")
        WebDriverWait(driver, 60).until(
            lambda _: js("return !!window.__cvTest && !!window.globalScope")
        )
        js(
            "__cvTest.loadJSON(arguments[0]);__cvTest.errorDetectedSet(false);__cvTest.play();",
            (ROOT / "examples/riscv_graphics/build/cpu-animation.cv").read_text(),
        )
        js("document.querySelector('.tabsbar-toggle .fa-chevron-up')?.closest('button').click()")
        WebDriverWait(driver, 10).until(
            lambda _: js("""
            const r=document.getElementById('simulationArea').getBoundingClientRect();
            return r.height>200 && r.top<innerHeight-200;
        """)
        )
        js("""document.querySelector('button[title="Fit to Screen"]')?.click()""")
        assert js("return globalScope.name") == "Demo"
        assert js("return !document.hidden")
        if args.queue == "insertion":
            assert result["bundleSha256"] == (
                "4fff7c8a8f6d1bdf5ca826cdf0907ae2c0f5a77b552768fd33ff58b54fef2fe6"
            ), "Unrecognized bundle: inspect the queue before profiling this experiment"
            candidate = (ROOT / "tools/circuitverse-queue-experiment.js").read_text()
            result["candidateSha256"] = hashlib.sha256(candidate.encode()).hexdigest()
            js(
                "const script=document.createElement('script');"
                "script.src='/circuitverse-queue-experiment.js';"
                "document.head.append(script);",
            )
            WebDriverWait(driver, 10).until(
                lambda _: js("return typeof window.__restoreQueue==='function'")
            )
            assert js("return window.__queueSameRealm"), "Queue replacement has the wrong realm"
            result["candidateSameRealm"] = True
        reference = list(
            (ROOT / "examples/riscv_graphics/build/animation/expected-frame.bin").read_bytes()
        )
        js("__cvTest.simulationArea.clockEnabled=false")
        js(harness.OBSERVER, reference, "cpu", 2)
        js("__cvTest.simulationArea.clockEnabled=true;__circuitVerseTurbo.setEnabled(true)")
        print("Warm up and verify CPU frame 1", flush=True)
        WebDriverWait(driver, 180, poll_frequency=0.2).until(
            lambda _: js(
                "return __frames.completed>=1 || __frames.errors.length"
                " || __cvTest.errorDetectedGet()"
            )
        )
        assert not js("return __frames.errors.length || __cvTest.errorDetectedGet()")
        # Measure a short baseline without sampling; stay within the second frame.
        before = js("return {time:performance.now(),...__circuitVerseTurbo.snapshot()}")
        time.sleep(args.baseline_seconds)
        after = js("return {time:performance.now(),...__circuitVerseTurbo.snapshot()}")
        baseline = (
            (after["totalEdges"] - before["totalEdges"]) * 1000 / (after["time"] - before["time"])
        )
        result["unprofiledEdgesPerSecond"] = baseline
        print(f"Unprofiled baseline: {baseline:.1f} edges/s", flush=True)
        assert after["enabled"], "Second frame finished before profile; shorten baseline"
        # Sample without changing any gate methods or drawing/waveform scheduler.
        driver.set_context("chrome")
        supported = driver.execute_script("return Services.profiler.GetFeatures()")
        features = [f for f in ["js", "stackwalk", "jssources", "processcpu"] if f in supported]
        driver.execute_script(
            "Services.profiler.StartProfiler(1000000,1,arguments[0],['GeckoMain'])", features
        )
        driver.set_context("content")
        start = js("return {time:performance.now(),...__circuitVerseTurbo.snapshot()}")
        print(f"Capture {args.seconds:g}s Gecko profile (1 ms sampling)", flush=True)
        time.sleep(args.seconds)
        end = js("return {time:performance.now(),...__circuitVerseTurbo.snapshot()}")
        assert end["enabled"], "Second frame finished during capture; shorten the profile interval"
        # Do not gather while simulating: pause after the measured region.
        js("__cvTest.simulationArea.clockEnabled=false;__circuitVerseTurbo.setEnabled(false)")
        driver.set_context("chrome")
        raw = driver.execute_async_script("""
            const done=arguments[arguments.length-1];
            Services.profiler.getProfileDataAsync().then(p=>done(JSON.stringify(p)))
              .catch(error=>done(JSON.stringify({error:String(error)})));
        """)
        driver.execute_script("Services.profiler.StopProfiler()")
        driver.set_context("content")
        profile = json.loads(raw)
        assert "error" not in profile, profile.get("error")
        with gzip.open(out / "cpu-firefox.json.gz", "wt") as file:
            file.write(raw)
        elapsed = end["time"] - start["time"]
        result["profiledEdgesPerSecond"] = (
            (end["totalEdges"] - start["totalEdges"]) * 1000 / elapsed
        )
        result["profilerFeatures"] = features
        result["profile"] = summarize(profile, elapsed)
        assert result["profile"]["threads"], "No simulator content thread found"
        if args.queue == "insertion":
            assert any(
                "circuitverse-queue-experiment.js" in row["function"]
                for thread in result["profile"]["threads"]
                for row in thread["leafSimulatorJS"]
            ), "Candidate frames are missing: do not infer hotspots from caller attribution"
        # Finish frame 2 and retain pixel/fault checks with the profiler stopped.
        js("__cvTest.simulationArea.clockEnabled=true;__circuitVerseTurbo.setEnabled(true)")
        WebDriverWait(driver, 180, poll_frequency=0.2).until(
            lambda _: js(
                "return __frames.completed>=2 || __frames.errors.length"
                " || __cvTest.errorDetectedGet()"
            )
        )
        result["frames"] = js("return __frames")
        js("__cvTest.simulationArea.clockEnabled=false;__circuitVerseTurbo.setEnabled(false)")
        assert not result["frames"]["errors"]
        assert not js("return __cvTest.errorDetectedGet()")
        assert result["frames"]["completed"] == 2
        if args.queue == "insertion":
            js("__restoreQueue()")
        driver.save_screenshot(str(out / "cpu-firefox.png"))
        result["passed"] = True
        print(
            json.dumps(
                {
                    "unprofiledEdgesPerSecond": baseline,
                    "profiledEdgesPerSecond": result["profiledEdgesPerSecond"],
                    "contentThreads": len(result["profile"]["threads"]),
                    "report": str(out / "summary.json"),
                }
            ),
            flush=True,
        )
    except Exception as error:
        result["failure"] = str(error)
        raise
    finally:
        (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        driver.quit()
        server.shutdown()


if __name__ == "__main__":
    main()
