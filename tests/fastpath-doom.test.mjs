import test from "node:test";
import assert from "node:assert/strict";
import { SuperTurboController } from "../tools/fastpath/controller.mjs";
import { doomKeyEvent } from "../tools/fastpath/doomkeys.mjs";

test("browser keys map to doomkeys.h codes in the key-FIFO format", () => {
  assert.equal(doomKeyEvent("ArrowUp", true), 0x300 | 0xad);
  assert.equal(doomKeyEvent("ArrowUp", false), 0x100 | 0xad);
  assert.equal(doomKeyEvent("Control", true), 0x300 | 0xa3);
  assert.equal(doomKeyEvent(" ", true), 0x300 | 0xa2);
  assert.equal(doomKeyEvent("Y", true), 0x300 | 0x79);
  assert.equal(doomKeyEvent("F1", true), 0x300 | 0xbb);
  assert.equal(doomKeyEvent("F12", true), 0x300 | 0xd8);
  assert.equal(doomKeyEvent("Meta", true), null);
});

class FakeWorker {
  constructor() {
    this.requests = [];
  }
  postMessage(request) {
    this.requests.push(request);
  }
  terminate() {}
  reply(snapshot) {
    const request = this.requests.shift();
    this.onmessage({ data: { id: request.id, epoch: request.epoch, snapshot, durationMs: 1 } });
  }
}
const display = {
  kind: "framebuffer",
  width: 2,
  height: 1,
  frameHeader: 10,
  framePixels: false,
  maxBatch: 1 << 20,
};
const tick = () => new Promise((resolve) => setImmediate(resolve));
const empty = () => ({
  edges: 0,
  completed: 0,
  outputs: {},
  pixels: new Uint32Array(0),
  frames: new Uint32Array(),
  frameTimes: new Float64Array(),
});

test("framebuffer profile: keys ride with batches; header-only frame records", async () => {
  const frames = [],
    presented = [],
    logged = [];
  const host = {
    enter() {},
    leave() {},
    blocked: () => null,
    present: (snapshot) => presented.push(snapshot.pixels.length),
    completedFrame: (frame) => frames.push(frame),
    console: (text) => logged.push(text),
  };
  const runner = new SuperTurboController(host, FakeWorker);
  const starting = runner.setMode("super", {
    base: new URL("http://localhost/package/"),
    manifest: { display },
  });
  await tick();
  runner.worker.reply(empty());
  await starting;
  runner.queueKey(0x3ad);
  runner.resume();
  const batch = runner.worker.requests[0];
  assert.equal(batch.limit, 1 << 20);
  assert.deepEqual(batch.keys, [0x3ad]);
  const header = [1, 64, 0, 0x2, 0xdeadbeef, 1, 7, 0, 3, 0];
  runner.worker.reply({
    ...empty(),
    completed: 1,
    pixels: Uint32Array.of(0xff0000, 0x00ff00),
    frames: Uint32Array.from([...header, 2, 128, 0, 0x2, 1, 2, 9, 0, 4, 0]),
    frameTimes: Float64Array.of(5, 6),
    console: "boot\n",
  });
  assert.equal(frames.length, 2);
  assert.deepEqual([...frames[0].header], header);
  assert.equal(frames[1].edges, 128);
  assert.equal(frames[1].pixels.length, 0);
  assert.deepEqual(logged, ["boot\n"]);
  assert.equal(presented.at(-1), 2, "a completed frame is presented immediately");
  await runner.pause(); // lands before the deferred continuation grants another batch
  await tick();
  assert.equal(runner.running, false);
  assert.equal(runner.worker.requests.length, 0);
  runner.dispose();
});
