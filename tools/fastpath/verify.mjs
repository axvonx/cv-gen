/** Native C++/WASM differential checks and complete-frame reference checks. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { spawn } from "node:child_process";
import readline from "node:readline";
import { HardwareModel } from "./runtime.mjs";

const directory = path.resolve(process.argv[2]);
const expected = fs.readFileSync(process.argv[3]);
const manifest = JSON.parse(fs.readFileSync(path.join(directory, "manifest.json")));
const { default: factory } = await import(pathToFileURL(path.join(directory, "model.mjs")));
const module = await factory({ locateFile: (name) => path.join(directory, name) });
const model = new HardwareModel(module, manifest);
const child = spawn(path.join(directory, "native-model"), [], {
  stdio: ["pipe", "pipe", "inherit"],
});
const lines = readline.createInterface({ input: child.stdout })[Symbol.asyncIterator]();
const ports = manifest.ports.filter((p) => p.direction === "output");
let comparisons = 0,
  frames = 0;
async function compare(command, snapshot) {
  child.stdin.write(command + "\n");
  const line = await lines.next();
  assert(!line.done, "native model exited");
  const native = JSON.parse(line.value);
  const outputs = Object.fromEntries(ports.map((p, i) => [p.name, native.outputs[i]]));
  assert.deepEqual(snapshot.outputs, outputs, `${command}: outputs`);
  assert.equal(snapshot.edges, native.counters[0] + native.counters[1] * 2 ** 32);
  assert.equal(snapshot.clock, native.counters[2]);
  assert.equal(snapshot.completed, native.counters[3] + native.counters[4] * 2 ** 32);
  assert.deepEqual([...snapshot.pixels], native.pixels, `${command}: framebuffer`);
  assert.deepEqual([...snapshot.frames], native.frames, `${command}: completed frames`);
  ++comparisons;
  return snapshot;
}
async function inputs(changes) {
  const snapshot = model.applyInputs(changes);
  const values = [...model.values];
  return compare("inputs " + values.join(" "), snapshot);
}
function checkFrames(snapshot) {
  const count = manifest.display.size ** 2,
    stride = count + 3;
  for (let i = 0; i < snapshot.frames.length; i += stride) {
    const index = snapshot.frames[i];
    assert.equal(index & 31, frames & 31, "frame sequence");
    for (let pixel = 0; pixel < count; ++pixel)
      assert.equal(
        snapshot.frames[i + 3 + pixel],
        expected[(frames & 31) * count + pixel] * 0x010101,
        `frame ${frames}, pixel ${pixel}`,
      );
    ++frames;
  }
}
try {
  await compare("snapshot", model.snapshot());
  if (manifest.profile === "rv32-graphics") {
    await inputs({ run: 0, load_enable: 0 });
    for (const [address, data] of [
      [0xf000, 0x11223344],
      [0xf014, 0xbeefcafe],
      [0xfffc, 0xdeadbeef],
      [0xe100, 0x80007fff],
    ]) {
      await inputs({ load_address: address, load_data: data });
      await inputs({ load_enable: 1 });
      await inputs({ load_enable: 0, inspect: 1, peek_address: address });
      assert.equal(model.snapshot().outputs.peek_word, data);
      await inputs({ inspect: 0 });
    }
    await compare("reset", model.reset());
    // Per-phase comparisons catch boot, register and low-phase memory mistakes.
    for (let i = 0; i < 1000; ++i) await compare("advance 1", model.advance(1, 0));
    await inputs({ run: 0 });
    const held = model.snapshot().outputs.pc;
    await compare("advance 20", model.advance(20, 0));
    assert.equal(model.snapshot().outputs.pc, held);
    await inputs({ run: 1 });
    await compare("reset", model.reset());
  }
  let batches = 0;
  while (frames < 33) {
    const snapshot = await compare("advance 1024", model.advance(1024, 0));
    checkFrames(snapshot);
    if (++batches > 10000) throw new Error("frame completion limit exceeded");
  }
  if (manifest.profile === "rv32-graphics") {
    const pixels = model.snapshot().pixels.slice();
    await inputs({ run: 0, inspect: 1 });
    for (let i = 0; i < 256; ++i) {
      const snapshot = await inputs({ peek_address: 0xf000 + i });
      assert.equal(snapshot.outputs.pixel * 0x010101, pixels[i], `RAM/display pixel ${i}`);
    }
  }
  const report = {
    passed: true,
    profile: manifest.profile,
    comparisons,
    frames,
    pixelsChecked: frames * manifest.display.size ** 2,
    modelId: manifest.modelId,
  };
  fs.writeFileSync(
    path.join(directory, "verification.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  manifest.validation = report;
  fs.writeFileSync(path.join(directory, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  console.log(JSON.stringify(report));
} finally {
  model.dispose();
  child.stdin.end();
}
