"""Apply the checked source seam to an isolated, pinned upstream checkout."""

import os
import shutil
import urllib.request
from pathlib import Path

from .compiler import ASSETS, ROOT, digest, run

FRONTEND_REV = "774003e5b14fb583b2c558d04f455b54031f40cc"
JQUERY_SHA256 = "c12f6098e641aaca96c60215800f18f5671039aecf812217fab3c0d152f6adb4"


def replace(path, before, after):
    text = path.read_text()
    if after in text:
        return
    if text.count(before) != 1:
        raise ValueError(f"frontend compatibility mismatch: {path}: {before}")
    path.write_text(text.replace(before, after))


def prepare(directory):
    directory = Path(directory).resolve()
    if not directory.exists():
        directory.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "https://github.com/CircuitVerse/cv-frontend-vue.git", str(directory)])
        run(["git", "checkout", FRONTEND_REV], cwd=directory)
    if run(["git", "rev-parse", "HEAD"], cwd=directory).stdout.strip() != FRONTEND_REV:
        raise ValueError("frontend checkout must use the pinned revision")
    src = directory / "src/simulator/src"
    replace(
        src / "setup.js",
        "    if (!localStorage.tutorials_tour_done && !embed) {",
        "    if (!localStorage.tutorials_tour_done && !embed && "
        "!new URL(location.href).searchParams.has('fastpath')) {",
    )
    public = directory / "v0/public"
    public.mkdir(exist_ok=True)
    jquery = public / "jquery-1.9.1.min.js"
    if not jquery.exists():
        with urllib.request.urlopen("https://code.jquery.com/jquery-1.9.1.min.js", timeout=30) as r:
            jquery.write_bytes(r.read())
    if digest(jquery.read_bytes()) != JQUERY_SHA256:
        raise ValueError("pinned jQuery asset hash mismatch")
    html = directory / "v0/index.html"
    comment = "<!-- jQuery is supplied by the bundled globalVariables module. -->"
    before = (
        comment
        if comment in html.read_text()
        else (
            '<script src="https://ajax.googleapis.com/ajax/libs/jquery/1.9.1/jquery.min.js"></script>'
        )
    )
    replace(html, before, '<script src="/simulator/jquery-1.9.1.min.js"></script>')
    replace(
        src / "engine.js",
        "export function play(scope = globalScope, resetNodes = false) {",
        "export function play(scope = globalScope, resetNodes = false) {\n"
        "    if (window.__cvFastpathHost?.active) { "
        "window.__cvFastpathHost.syncInputs(); return; }",
    )
    replace(
        src / "engine.js",
        "    willBeUpdatedSet(false)\n    if (loading === true",
        "    willBeUpdatedSet(false)\n"
        "    if (window.__cvFastpathHost?.active) { renderCanvas(scope); return; }\n"
        "    if (loading === true",
    )
    replace(
        src / "utils.ts",
        "export function clockTick() {",
        "export function clockTick() {\n  if ((window as any).__cvFastpathHost?.active) return;",
    )
    replace(
        src / "simulationArea.ts",
        "    simulationArea.ClockInterval = setInterval(clockTick, t);",
        "    simulationArea.ClockInterval = (window as any).__cvFastpathHost?.active\n"
        "      ? null : setInterval(clockTick, t);",
    )
    replace(
        src / "sequential.ts",
        "  simulationArea.clockEnabled = val;",
        "  simulationArea.clockEnabled = val;\n"
        "  if ((window as any).__cvFastpathHost?.active) {\n"
        "    const runner = (window as any).__cvSuperTurbo;\n"
        "    val ? runner.resume() : runner.pause();\n  }",
    )
    replace(
        src / "circuit.ts",
        "export function switchCircuit(id: string) {",
        "export function switchCircuit(id: string) {\n"
        "  (window as any).__cvFastpathHost?.circuitChanging(id);",
    )
    replace(
        src / "data/load.js",
        "export default function load(data) {",
        "export default function load(data) {\n    window.__cvFastpathHost?.beforeImport(data);",
    )
    replace(
        src / "data/save.js",
        "export async function generateSaveData(name, setName = true) {",
        "export async function generateSaveData(name, setName = true) {\n"
        "    if (window.__cvFastpathHost?.active) "
        "throw new Error('Exit Super Turbo before saving');",
    )
    replace(
        src / "data/backupCircuit.js",
        "export function scheduleBackup(scope = globalScope) {",
        "export function scheduleBackup(scope = globalScope) {\n"
        "    if (window.__cvFastpathHost?.active) return;",
    )
    replace(
        src / "wire.ts",
        "  private getWireColor(): string {",
        "  private getWireColor(): string {\n"
        "    if ((window as any).__cvFastpathHost?.active) return '#80909c';",
    )
    replace(
        directory / "src/main.ts",
        'app.mount("#app");',
        'app.mount("#app");\nimport("./simulator/src/cvgenFastpath.js")'
        ".then(m => m.initializeFastpath());",
    )
    shutil.copyfile(ASSETS / "frontend.js", src / "cvgenFastpath.js")
    (src / "fastpath").mkdir(exist_ok=True)
    for name in ["runtime.mjs", "controller.mjs", "doomkeys.mjs"]:
        shutil.copyfile(ASSETS / name, src / "fastpath" / name)
    if not (directory / "node_modules").exists():
        run(["npm", "ci", "--ignore-scripts"], cwd=directory)
    run(
        ["node", "scripts/multi-build.js", "v0"],
        cwd=directory,
        env={**os.environ, "VITE_BASE": "/simulator/"},
    )
    return directory / "dist/simulatorvue/v0"


if __name__ == "__main__":
    print(prepare(ROOT / "build/fastpath/frontend"))
