import { HardwareModel } from "./runtime.mjs";

let hardware, epoch;
self.onmessage = async ({ data }) => {
  const { id, command } = data;
  try {
    let snapshot;
    const started = performance.now();
    if (command === "create") {
      if (hardware) throw new Error("duplicate Worker initialization");
      epoch = data.epoch;
      const { default: createModule } = await import("./model.mjs");
      const module = await createModule({
        locateFile: (name) => new URL(name, import.meta.url).href,
        printErr: (message) => console.error("[Super Turbo]", message),
        onAbort: (message) => {
          throw new Error(`WASM abort: ${message}`);
        },
      });
      hardware = new HardwareModel(module, data.manifest);
      snapshot = hardware.snapshot();
    } else {
      if (!hardware || epoch !== data.epoch) throw new Error("stale/uninitialized Worker session");
      if (command === "advance") {
        hardware.queueKeys(data.keys);
        snapshot = hardware.advance(data.limit, data.budgetMs);
      }
      else if (command === "inputs") snapshot = hardware.applyInputs(data.changes);
      else if (command === "reset") snapshot = hardware.reset();
      else if (command === "snapshot") snapshot = hardware.snapshot();
      else if (command === "destroy") {
        hardware.dispose();
        hardware = null;
      } else throw new Error(`unknown Worker command: ${command}`);
    }
    const durationMs = performance.now() - started;
    self.postMessage(
      { id, epoch: data.epoch, snapshot, durationMs },
      snapshot ? [snapshot.pixels.buffer, snapshot.frames.buffer, snapshot.frameTimes.buffer] : [],
    );
  } catch (error) {
    self.postMessage({ id, epoch: data.epoch, error: String(error?.message || error) });
  }
};
