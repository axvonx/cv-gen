/** Compare every settled native-CircuitVerse port sample with the compiled RTL. */
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { HardwareModel } from "./runtime.mjs";
import { createHash } from "node:crypto";

const directory = path.resolve(process.argv[2]);
const trace = JSON.parse(fs.readFileSync(process.argv[3]));
const manifest = JSON.parse(fs.readFileSync(path.join(directory, "manifest.json")));
const ports = manifest.ports.filter((p) => p.direction === "output");
assert.deepEqual(
  trace.fields,
  ports.map((p) => p.name),
);
const { default: factory } = await import(pathToFileURL(path.join(directory, "model.mjs")));
const module = await factory({ locateFile: (name) => path.join(directory, name) });
const hardware = new HardwareModel(module, manifest);
let hash = 2166136261;
const strongHash = createHash("sha256"),
  row = Buffer.alloc(ports.length * 4);
for (let edge = 1; edge <= trace.edges; ++edge) {
  hardware.check(module._fp_advance(1, 0));
  module._fp_snapshot();
  const start = module._fp_outputs() >>> 2;
  for (let i = 0; i < ports.length; ++i) {
    const value = module.HEAPU32[start + i];
    hash = Math.imul(hash ^ value, 16777619) >>> 0;
    row.writeUInt32LE(value, i * 4);
  }
  strongHash.update(row);
}
hardware.dispose();
assert.equal(hash, trace.hash, `native CV / compiled RTL port trace through edge ${trace.edges}`);
const sha256 = strongHash.digest("hex");
assert.equal(sha256, trace.sha256, "full settled-port transcript SHA256");
console.log(
  JSON.stringify({ passed: true, edges: trace.edges, fields: trace.fields, hash, sha256 }),
);
