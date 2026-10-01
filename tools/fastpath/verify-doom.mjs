/** Verifies an rv32-doom package against the ISS oracle, frame for frame.
 *
 *   node tools/fastpath/verify-doom.mjs <package> <iss frames.tsv> [keys file]
 *
 * Runs the packaged WASM model through the same HardwareModel the browser Worker
 * uses. Key events for frame N are queued while frame N-1 is the latest completed
 * frame, so they enter the FIFO at doorbell N exactly as in the ISS and native
 * testbench. Every frame's game info, retired instructions, cycles and FNV-1a
 * framebuffer+palette hash must equal the ISS log (tools/doom/iss.c). */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { HardwareModel } from "./runtime.mjs";

const directory = path.resolve(process.argv[2]);
const expected = fs
  .readFileSync(process.argv[3], "utf8")
  .trim()
  .split("\n")
  .slice(1)
  .map((line) => line.split("\t"));
const schedule = new Map();
if (process.argv[4])
  for (const line of fs.readFileSync(process.argv[4], "utf8").split("\n")) {
    const fields = line.replace(/#.*/, "").trim().split(/\s+/);
    if (fields.length < 3) continue;
    const [frame, pressed, key] = fields.map(Number);
    assert(frame > 0, "frame-0 key events are not supported by the package boot");
    if (!schedule.has(frame)) schedule.set(frame, []);
    schedule.get(frame).push(0x100 | (pressed ? 0x200 : 0) | (key & 0xff));
  }
const manifest = JSON.parse(fs.readFileSync(path.join(directory, "manifest.json")));
assert.equal(manifest.profile, "rv32-doom");
const { default: factory } = await import(pathToFileURL(path.join(directory, "model.mjs")));
const module = await factory({ locateFile: (name) => path.join(directory, name) });
const model = new HardwareModel(module, manifest);
const header = manifest.display.frameHeader;
let frames = 0,
  edges = 0,
  console = "";
const started = performance.now();
try {
  while (frames < expected.length) {
    model.queueKeys(schedule.get(frames + 1));
    schedule.delete(frames + 1);
    const snapshot = model.advance(65536, 0);
    edges = snapshot.edges;
    console += snapshot.console;
    for (let i = 0; i < snapshot.frames.length; i += model.stride) {
      const f = snapshot.frames.slice(i, i + header);
      const row = expected[frames];
      const hash = ((BigInt(f[5]) << 32n) | BigInt(f[4])).toString(16).padStart(16, "0");
      const info = f[3];
      assert.equal(f[0], frames + 1, "frame sequence");
      assert.deepEqual(
        [info >>> 28, (info >>> 27) & 1, info & 0x07ffffff, f[8] + f[9] * 2 ** 32],
        [Number(row[1]), Number(row[2]), Number(row[3]), Number(row[4])],
        `frame ${frames + 1}: state/menu/tic/instret`,
      );
      assert.equal(f[6] + f[7] * 2 ** 32, Number(row[5]), `frame ${frames + 1}: cycles`);
      assert.equal(hash, row[6], `frame ${frames + 1}: framebuffer hash`);
      ++frames;
    }
  }
  const seconds = (performance.now() - started) / 1000;
  assert.match(console, /I_InitGraphics/, "console output");
  const report = {
    passed: true,
    profile: manifest.profile,
    reference: "tools/doom/iss.c frames.tsv",
    frames,
    keyEvents: process.argv[4] ? path.basename(process.argv[4]) : null,
    halfEdges: edges,
    nodeSeconds: Number(seconds.toFixed(1)),
    nodeCyclesPerSecond: Math.round(edges / 2 / seconds),
    modelId: manifest.modelId,
  };
  fs.writeFileSync(
    path.join(directory, "verification.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  manifest.validation = report;
  fs.writeFileSync(path.join(directory, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  process.stdout.write(JSON.stringify(report) + "\n");
} finally {
  model.dispose();
}
