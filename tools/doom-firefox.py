"""DOOM in Super Turbo, in visible Firefox: reference frames, keyboard input, speed.

    uv run --with selenium python tools/doom-firefox.py

Serves the pinned frontend and build/fastpath/doom, enables Super Turbo, and:
1. runs without input and requires every frame's game state, retired instructions,
   cycles and framebuffer hash to equal the ISS log (build/doom/run-im-iss);
2. holds the up-arrow key through real browser keyboard events and requires the
   frames to diverge from the no-input run (the player moved);
3. measures completed-frame intervals and simulated cycles per second, and checks
   that native CircuitVerse propagation never ran.
Writes build/fastpath/doom-firefox.json and a screenshot.
"""

import argparse
import itertools
import json
import statistics
import threading
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastpath.compiler import ROOT
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

OBSERVER = """
window.__doom={frames:[]};
__cvFastpathHost.completedFrame=frame=>{
 const h=frame.header;
 __doom.frames.push({index:h[0],time:frame.time,info:h[3],
  hash:((BigInt(h[5])<<32n)|BigInt(h[4])).toString(16).padStart(16,'0'),
  cycles:h[6]+h[7]*2**32,instret:h[8]+h[9]*2**32});
};
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=60, help="no-input frames to compare")
    parser.add_argument("--walk-frames", type=int, default=12, help="frames with up held")
    parser.add_argument("--reference", type=Path, default=ROOT / "build/doom/run-im-iss/frames.tsv")
    args = parser.parse_args()
    spec = spec_from_file_location("serve", ROOT / "tools/serve-circuitverse-fastpath.py")
    serve = module_from_spec(spec)
    spec.loader.exec_module(serve)
    http = serve.server(
        ROOT / "build/fastpath/frontend/dist/simulatorvue/v0", ROOT / "build/fastpath", 0
    )
    threading.Thread(target=http.serve_forever, daemon=True).start()
    expected = [line.split("\t") for line in args.reference.read_text().strip().splitlines()[1:]]
    options = webdriver.FirefoxOptions()
    options.page_load_strategy = "eager"
    driver = webdriver.Firefox(options=options)
    driver.set_window_size(1440, 1000)
    driver.set_script_timeout(60)
    js = driver.execute_script
    wait = WebDriverWait(driver, 600, poll_frequency=0.1)
    report = {"firefox": driver.capabilities["browserVersion"], "passed": False}
    try:
        port = http.server_address[1]
        driver.get(f"http://127.0.0.1:{port}/simulator?fastpath=/packages/doom/")
        wait.until(lambda d: js("return window.__cvSuperTurbo?.status") or "")
        wait.until(
            lambda d: (
                "Compatible" in js("return __cvSuperTurbo.status")
                or js("return __cvSuperTurbo.error")
            )
        )
        assert not js("return __cvSuperTurbo.error"), js("return __cvSuperTurbo.error")
        js(OBSERVER)
        started = time.time()
        js("document.querySelector('#cv-super-panel [data-action=toggle]').click()")
        wait.until(
            lambda d: (
                js("return __doom.frames.length") >= args.frames
                or js("return __cvSuperTurbo.error")
            )
        )
        assert not js("return __cvSuperTurbo.error"), js("return __cvSuperTurbo.error")
        frames = js("return __doom.frames")[: args.frames]
        for frame, row in zip(frames, expected, strict=False):
            info = frame["info"]
            got = [
                info >> 28,
                (info >> 27) & 1,
                info & 0x07FFFFFF,
                frame["instret"],
                frame["cycles"],
                frame["hash"],
            ]
            want = [int(row[1]), int(row[2]), int(row[3]), int(row[4]), int(row[5]), row[6]]
            assert got == want, f"frame {frame['index']}: browser {got} != ISS {want}"
        report["referenceFrames"] = len(frames)
        gameplay = [f for f in frames if f["index"] >= 45]
        intervals = [b["time"] - a["time"] for a, b in itertools.pairwise(gameplay)]
        cycles = gameplay[-1]["cycles"] - gameplay[0]["cycles"]
        span = (gameplay[-1]["time"] - gameplay[0]["time"]) / 1000
        report["gameplay"] = {
            "frames": len(gameplay),
            "medianFrameMs": round(statistics.median(intervals), 1),
            "maxFrameMs": round(max(intervals), 1),
            "framesPerSecond": round(1000 / statistics.median(intervals), 2),
            "simulatedCyclesPerSecond": round(cycles / span),
        }
        boot = frames[41]
        report["firstGameplayFrameSeconds"] = round(
            (boot["time"] - frames[0]["time"]) / 1000 + frames[0]["cycles"] / (cycles / span), 1
        )
        report["wallSecondsToReferenceFrames"] = round(time.time() - started, 1)
        # Walk: hold up arrow through real keyboard events.
        before = js("return __doom.frames.length")
        canvas = driver.find_element("css selector", "#cv-doom-screen canvas")
        ActionChains(driver).move_to_element(canvas).key_down(Keys.ARROW_UP).perform()
        wait.until(lambda d: js("return __doom.frames.length") >= before + args.walk_frames)
        ActionChains(driver).key_up(Keys.ARROW_UP).perform()
        walked = js("return __doom.frames")[before : before + args.walk_frames]
        diverged = [
            f["index"]
            for f in walked
            if f["index"] <= len(expected) and f["hash"] != expected[f["index"] - 1][6]
        ]
        assert diverged, "holding up-arrow did not change the rendered frames"
        report["walk"] = {"framesWithKeyHeld": len(walked), "firstDivergentFrame": diverged[0]}
        js("__cvSuperTurbo.pause()")
        driver.save_screenshot(str(ROOT / "build/fastpath/doom-firefox.png"))
        counters = js("return __cvTest.nativeCounters()")
        assert not any(counters.values()), f"native propagation ran: {counters}"
        report["nativeCounters"] = counters
        report["status"] = js("return __cvSuperTurbo.status")
        report["passed"] = True
    finally:
        (ROOT / "build/fastpath/doom-firefox.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        driver.quit()
        http.shutdown()


if __name__ == "__main__":
    main()
