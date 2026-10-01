import test from "node:test";
import assert from "node:assert/strict";
import { SuperTurboController } from "../tools/fastpath/controller.mjs";

class FakeWorker {
  static instances = [];
  constructor() {
    this.requests = [];
    this.terminated = false;
    FakeWorker.instances.push(this);
  }
  postMessage(request) {
    this.requests.push(request);
  }
  terminate() {
    this.terminated = true;
  }
  reply(
    snapshot = {
      edges: 0,
      completed: 0,
      outputs: {},
      pixels: new Uint32Array(1),
      frames: new Uint32Array(),
      frameTimes: new Float64Array(),
    },
  ) {
    const request = this.requests.shift();
    this.onmessage({ data: { id: request.id, epoch: request.epoch, snapshot, durationMs: 1 } });
  }
}
const info = { base: new URL("http://localhost/package/"), manifest: { display: { size: 1 } } };
function fixture() {
  let blocked = null,
    entries = 0,
    exits = 0;
  const host = {
    enter() {
      entries++;
    },
    leave() {
      exits++;
    },
    present() {},
    blocked: () => blocked,
  };
  return {
    runner: new SuperTurboController(host, FakeWorker),
    block: (value) => {
      blocked = value;
    },
    counts: () => ({ entries, exits }),
  };
}
const tick = () => new Promise((resolve) => setImmediate(resolve));
async function boot(runner) {
  const starting = runner.setMode("super", info);
  await tick();
  runner.worker.reply();
  await starting;
}

test("one pending batch; processed pause freezes execution", async () => {
  const { runner } = fixture();
  await boot(runner);
  runner.resume();
  runner.pump();
  assert.equal(runner.worker.requests.length, 1);
  const pausing = runner.pause();
  runner.worker.reply();
  await pausing;
  await tick();
  assert.equal(runner.running, false);
  assert.equal(runner.worker.requests.length, 0);
  runner.dispose();
});
test("hidden stops grants without catch-up; scope/layout requires resume", async () => {
  const { runner, block } = fixture();
  await boot(runner);
  block("Hidden tab — suspended");
  runner.resume();
  assert.equal(runner.worker.requests.length, 0);
  block(null);
  runner.pump();
  assert.equal(runner.worker.requests.length, 1);
  block("Layout mode — paused");
  runner.worker.reply();
  await tick();
  runner.pump();
  assert.equal(runner.running, false);
  block(null);
  runner.pump();
  assert.equal(runner.worker.requests.length, 0);
  runner.dispose();
});
test("stale replies cannot replace the current snapshot", async () => {
  const { runner } = fixture();
  await boot(runner);
  runner.resume();
  const pending = runner.pending;
  runner.receive({ epoch: runner.epoch - 1, id: pending.id, snapshot: { edges: 999 } });
  assert.equal(runner.pending, pending);
  assert.equal(runner.last.edges, 0);
  const stop = runner.pause();
  runner.worker.reply();
  await stop;
  runner.dispose();
});
test("concurrent mode changes are serialized and terminate the old worker", async () => {
  const { runner, counts } = fixture();
  await boot(runner);
  const old = runner.worker;
  const restarting = runner.setMode("super", info),
    leaving = runner.setMode("native");
  await tick();
  assert.equal(old.terminated, true);
  runner.worker.reply();
  await restarting;
  await leaving;
  assert.equal(runner.mode, "native");
  assert.equal(runner.worker, null);
  assert.deepEqual(counts(), { entries: 2, exits: 2 });
});
test("pause during an input operation prevents automatic resume", async () => {
  const { runner } = fixture();
  await boot(runner);
  runner.resume();
  const inputs = runner.applyInputs({ run: 0 });
  await tick();
  runner.worker.reply();
  await tick();
  assert.equal(runner.worker.requests[0].command, "inputs");
  const stop = runner.pause();
  runner.worker.reply();
  await inputs;
  await stop;
  assert.equal(runner.running, false);
  runner.dispose();
});
test("worker exceptions stop the session without native fallback", async () => {
  const { runner, counts } = fixture();
  await boot(runner);
  runner.resume();
  const worker = runner.worker;
  const request = worker.requests.shift();
  runner.receive({ id: request.id, epoch: request.epoch, error: "convergence failure" });
  await tick();
  assert.equal(runner.running, false);
  assert.equal(worker.terminated, true);
  assert.equal(runner.mode, "super");
  assert.equal(counts().exits, 0);
  assert.match(runner.status, /convergence failure/);
  runner.dispose();
});
test("disposing an outstanding pump cannot poison a replacement session", async () => {
  const { runner } = fixture();
  await boot(runner);
  runner.resume();
  runner.dispose();
  await boot(runner);
  await tick();
  assert.equal(runner.error, undefined);
  assert.ok(runner.worker);
  runner.dispose();
});
test("presentation exceptions reject the batch and stop its Worker", async () => {
  const { runner } = fixture();
  await boot(runner);
  runner.host.present = () => {
    throw new Error("canvas failure");
  };
  runner.lastPaint = -Infinity;
  runner.resume();
  const worker = runner.worker;
  worker.reply();
  await tick();
  assert.equal(worker.terminated, true);
  assert.match(runner.error, /canvas failure/);
  runner.dispose();
});
