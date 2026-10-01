/** One outstanding Worker operation; native execution is owned by the host seam. */
export class SuperTurboController {
  constructor(host, WorkerClass = Worker) {
    this.host = host;
    this.WorkerClass = WorkerClass;
    this.mode = "native";
    this.running = false;
    this.status = "Native";
    this.epoch = 0;
    this.sequence = 0;
    this.pending = null;
    this.last = null;
    this.budgetMs = 8;
    this.pauseWaiters = [];
    this.listeners = new Set();
    this.commandTail = Promise.resolve();
    this.lastPaint = 0;
    this.frameTimes = [];
    this.controlRevision = 0;
    this.keyQueue = [];
  }
  /** Key events ride along with the next batch; they enter the machine at a frame. */
  queueKey(value) {
    if (this.mode === "super" && this.manifest?.display.kind === "framebuffer")
      this.keyQueue.push(value);
  }
  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  notify() {
    for (const listener of this.listeners) listener(this.snapshot());
  }
  snapshot() {
    return {
      mode: this.mode,
      running: this.running,
      status: this.status,
      epoch: this.epoch,
      pending: !!this.pending,
      budgetMs: this.budgetMs,
      edges: this.last?.edges || 0,
      completed: this.last?.completed || 0,
      durationMs: this.durationMs || 0,
      outputs: this.last?.outputs || {},
      frameTimes: this.frameTimes.slice(),
      error: this.error,
    };
  }
  request(command, extra = {}) {
    if (this.pending) return Promise.reject(new Error("overlapping Worker operation"));
    return new Promise((resolve, reject) => {
      const id = ++this.sequence;
      const timer = setTimeout(
        () => this.fail("Worker operation timed out"),
        command === "create" ? 30000 : 2000,
      );
      this.pending = { id, resolve, reject, timer };
      this.worker.postMessage({ id, epoch: this.epoch, command, ...extra });
    });
  }
  receive(data) {
    if (data.epoch !== this.epoch || data.id !== this.pending?.id) return;
    const pending = this.pending;
    this.pending = null;
    clearTimeout(pending.timer);
    try {
      if (data.error) {
        pending.reject(new Error(data.error));
        this.fail(data.error);
        return;
      }
      this.durationMs = data.durationMs;
      if (data.snapshot) {
        this.last = data.snapshot;
        const now = performance.now();
        const display = this.manifest.display;
        const header = display.frameHeader ?? 3;
        const count = display.width ? display.width * display.height : display.size ** 2;
        const stride = header + (display.framePixels === false ? 0 : count);
        for (let i = 0; i < this.last.frames.length; i += stride) {
          const frame = {
            index: this.last.frames[i],
            time: this.last.frameTimes[i / stride],
            edges: this.last.frames[i + 1] + this.last.frames[i + 2] * 2 ** 32,
            header: this.last.frames.slice(i, i + header),
            pixels: this.last.frames.slice(i + header, i + stride),
          };
          this.frameTimes.push({ index: frame.index, time: frame.time, edges: frame.edges });
          if (this.frameTimes.length > 256) this.frameTimes.shift();
          this.host.completedFrame?.(frame);
        }
        if (this.last.console) this.host.console?.(this.last.console);
        if (!this.running || now - this.lastPaint >= 1000 / 30 || this.last.pixels.length) {
          this.host.present(this.last);
          this.lastPaint = now;
        }
      }
      pending.resolve(data.snapshot);
      for (const resolve of this.pauseWaiters.splice(0)) resolve(this.snapshot());
      this.notify();
    } catch (error) {
      pending.reject(error);
      this.fail(error.message || String(error));
    }
  }
  enqueue(action) {
    const next = this.commandTail.then(action);
    this.commandTail = next.catch(() => {});
    return next;
  }
  setMode(mode, packageInfo) {
    return this.enqueue(() => this.switchMode(mode, packageInfo));
  }
  async switchMode(mode, packageInfo) {
    if (!["native", "super"].includes(mode)) throw new Error("unknown mode");
    await this.pause();
    if (this.worker) this.disposeWorker();
    const wasSuper = this.mode === "super";
    if (wasSuper) this.host.leave();
    if (mode === "native") {
      this.mode = "native";
      if (!wasSuper) this.host.leave();
      this.status = "Native — paused";
      this.notify();
      return;
    }
    this.mode = "super";
    this.status = "Loading";
    this.error = undefined;
    this.manifest = packageInfo.manifest;
    this.frameTimes = [];
    this.last = null;
    try {
      this.host.enter(packageInfo);
      this.worker = new this.WorkerClass(new URL("worker.mjs", packageInfo.base), {
        type: "module",
      });
      ++this.epoch;
      const epoch = this.epoch;
      this.worker.onmessage = ({ data }) => this.receive(data);
      this.worker.onerror = (event) => {
        if (this.epoch === epoch) this.fail(event.message || "Worker failed");
      };
      await this.request("create", { manifest: this.manifest });
      this.status = "Super Turbo — paused";
      this.notify();
    } catch (error) {
      this.fail(error.message);
      throw error;
    }
  }
  fail(message) {
    this.running = false;
    this.error = message;
    this.status = `Stopped: ${message}`;
    if (this.pending) {
      clearTimeout(this.pending.timer);
      this.pending.reject(new Error(message));
      this.pending = null;
    }
    this.worker?.terminate();
    this.worker = null;
    for (const resolve of this.pauseWaiters.splice(0)) resolve(this.snapshot());
    this.notify();
  }
  resume(userAction = true) {
    if (userAction) ++this.controlRevision;
    if (this.mode !== "super" || !this.worker || this.error) return;
    this.running = true;
    this.status = "Super Turbo";
    this.notify();
    this.pump();
  }
  async pause(userAction = true) {
    if (userAction) ++this.controlRevision;
    this.running = false;
    if (!this.error)
      this.status = this.mode === "super" ? "Super Turbo — paused" : "Native — paused";
    if (this.pending) await new Promise((resolve) => this.pauseWaiters.push(resolve));
    if (this.last) this.host.present(this.last);
    this.notify();
    return this.snapshot();
  }
  pump() {
    if (!this.running || this.pending || this.mode !== "super" || this.error) return;
    const blocked = this.host.blocked();
    if (blocked) {
      if (blocked !== "Hidden tab — suspended" && blocked !== "Loading") this.running = false;
      this.status = blocked;
      this.notify();
      return;
    }
    this.status = "Super Turbo";
    const epoch = this.epoch;
    const display = this.manifest.display;
    this.request("advance", {
      limit: display.maxBatch ?? 65536,
      budgetMs: this.budgetMs,
      keys: this.keyQueue.splice(0),
    })
      .then(() => {
        if (this.epoch === epoch) this.yield(() => this.pump());
      })
      .catch((error) => {
        if (this.epoch === epoch) this.fail(error.message);
      });
  }
  // Framebuffer profiles continue without setTimeout's nested-timer clamp (>= 4 ms),
  // which would otherwise idle the Worker for about half of each 8 ms batch.
  yield(next) {
    if (this.manifest?.display.kind !== "framebuffer" || typeof MessageChannel === "undefined")
      return setTimeout(next, 0);
    if (!this.channel) {
      this.channel = new MessageChannel();
      this.channel.port1.onmessage = () => this.channelNext?.();
    }
    this.channelNext = next;
    this.channel.port2.postMessage(0);
  }
  async operation(command, extra) {
    const wasRunning = this.running;
    const revision = this.controlRevision;
    await this.pause(false);
    if (this.mode !== "super" || !this.worker || this.error) throw new Error("backend unavailable");
    const result = await this.request(command, extra);
    if (wasRunning && command === "inputs" && revision === this.controlRevision) this.resume(false);
    return result;
  }
  applyInputs(changes) {
    return this.enqueue(() => this.operation("inputs", { changes }));
  }
  reset() {
    return this.enqueue(() => {
      this.frameTimes = [];
      return this.operation("reset");
    });
  }
  stepHalfEdge() {
    return this.enqueue(() => this.operation("advance", { limit: 1, budgetMs: 0 }));
  }
  disposeWorker() {
    ++this.epoch;
    this.channel?.port1.close();
    this.channel?.port2.close();
    this.channel = null;
    if (this.pending) {
      clearTimeout(this.pending.timer);
      this.pending.reject(new Error("session disposed"));
      this.pending = null;
    }
    this.worker?.terminate();
    this.worker = null;
    for (const resolve of this.pauseWaiters.splice(0)) resolve(this.snapshot());
  }
  dispose() {
    this.running = false;
    this.disposeWorker();
    this.mode = "native";
    this.notify();
  }
}
