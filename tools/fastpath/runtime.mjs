/** Bulk WASM access shared by the Worker and differential test runner. */
export class HardwareModel {
  constructor(module, manifest) {
    this.module = module;
    this.manifest = manifest;
    this.inputs = manifest.ports.filter((p) => p.direction === "input");
    this.outputs = manifest.ports.filter((p) => p.direction === "output");
    this.values = Uint32Array.from(this.inputs.map((p) => p.initial));
    const display = manifest.display;
    this.pixelCount = display.width ? display.width * display.height : display.size ** 2;
    // Frame records: a header (index, edges, ...) and, unless framePixels is false,
    // that frame's pixels. A framebuffer profile copies pixels only when a frame completes.
    this.stride = (display.frameHeader ?? 3) + (display.framePixels === false ? 0 : this.pixelCount);
    this.maxBatch = display.maxBatch ?? 65536;
    this.framebuffer = display.kind === "framebuffer";
    this.copiedFrame = -1;
    this.pointer = module._malloc(this.values.byteLength);
    if (!this.pointer) throw new Error("input allocation failed");
    this.check(module._fp_create());
  }
  check(result) {
    if (result < 0) throw new Error(this.module.UTF8ToString(this.module._fp_error()));
    return result;
  }
  reset() {
    this.values.set(this.inputs.map((p) => p.initial));
    this.check(this.module._fp_reset());
    return this.snapshot();
  }
  applyInputs(changes) {
    const phase = this.snapshot().clock;
    for (const [name, value] of Object.entries(changes)) {
      const i = this.inputs.findIndex((p) => p.name === name);
      if (i < 0 || name === this.manifest.clock) throw new Error(`invalid input: ${name}`);
      const width = this.inputs[i].width;
      if (!Number.isInteger(value) || value < 0 || value > 2 ** width - 1)
        throw new Error(`input value outside ${width}-bit range: ${name}`);
      this.values[i] = value;
    }
    this.values[this.inputs.findIndex((p) => p.name === this.manifest.clock)] = phase;
    this.module.HEAPU32.set(this.values, this.pointer >>> 2);
    this.check(this.module._fp_apply_inputs(this.pointer));
    return this.snapshot();
  }
  queueKeys(events = []) {
    for (const value of events) {
      if (!this.framebuffer || !Number.isInteger(value)) throw new Error("invalid key event");
      this.check(this.module._fp_key(value));
    }
  }
  advance(limit = 65536, budgetMs = 8) {
    if (
      !Number.isInteger(limit) ||
      limit < 0 ||
      limit > this.maxBatch ||
      !Number.isFinite(budgetMs) ||
      budgetMs < 0 ||
      budgetMs > 8
    )
      throw new Error("invalid advance limits");
    this.check(this.module._fp_advance(limit, budgetMs));
    return this.snapshot();
  }
  snapshot() {
    const m = this.module;
    const pointer = m._fp_snapshot();
    if (!pointer) throw new Error("model disposed");
    const counters = m.HEAPU32.slice(pointer >>> 2, (pointer >>> 2) + 6);
    const copy = (ptr, n) => m.HEAPU32.slice(ptr >>> 2, (ptr >>> 2) + n);
    const raw = copy(m._fp_outputs(), this.outputs.length);
    const completed = counters[3] + counters[4] * 2 ** 32;
    const fresh = !this.framebuffer || completed !== this.copiedFrame;
    this.copiedFrame = completed;
    return {
      edges: counters[0] + counters[1] * 2 ** 32,
      clock: counters[2],
      completed,
      outputs: Object.fromEntries(this.outputs.map((p, i) => [p.name, raw[i]])),
      inputs: Object.fromEntries(
        this.inputs.map((p, i) => [
          p.name,
          p.name === this.manifest.clock ? counters[2] : this.values[i],
        ]),
      ),
      pixels: fresh ? copy(m._fp_pixels(), this.pixelCount) : new Uint32Array(0),
      frames: copy(m._fp_frames(), counters[5]),
      frameTimes: m.HEAPF64.slice(
        m._fp_frame_times() >>> 3,
        (m._fp_frame_times() >>> 3) + counters[5] / this.stride,
      ),
      console: this.framebuffer ? m.UTF8ToString(m._fp_console()) : "",
    };
  }
  dispose() {
    this.module._fp_destroy();
    this.module._free(this.pointer);
  }
}

export async function sha256(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

export async function fetchPackage(base) {
  const response = await fetch(new URL("manifest.json", base));
  if (!response.ok) throw new Error("package manifest not found");
  const manifest = await response.json();
  if (
    manifest.abi !== 1 ||
    !["rv32-graphics", "rom-playback", "rv32-doom"].includes(manifest.profile)
  )
    throw new Error("unsupported backend ABI/profile");
  if (manifest.validation?.passed !== true)
    throw new Error(
      "Package unverified; run tools/fastpath/verify.mjs against the C reference first",
    );
  const assets = {};
  await Promise.all(
    Object.entries(manifest.assets).map(async ([name, hash]) => {
      if (!/^[a-zA-Z0-9_.-]+$/.test(name)) throw new Error("invalid package asset path");
      const r = await fetch(new URL(name, base));
      if (!r.ok) throw new Error(`missing package asset: ${name}`);
      const bytes = await r.arrayBuffer();
      if ((await sha256(bytes)) !== hash) throw new Error(`package asset hash mismatch: ${name}`);
      assets[name] = bytes;
    }),
  );
  if (!assets["project.cv"] || (await sha256(assets["project.cv"])) !== manifest.projectSha256)
    throw new Error("project identity mismatch");
  return { manifest, projectText: new TextDecoder().decode(assets["project.cv"]) };
}
