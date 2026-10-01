import test from "node:test";
import assert from "node:assert/strict";
import { fetchPackage, sha256 } from "../tools/fastpath/runtime.mjs";

test("package loader rejects unsupported, unverified and corrupt assets", async () => {
  const original = globalThis.fetch;
  const project = new TextEncoder().encode('{"scopes":[]}');
  const hash = await sha256(project);
  let manifest = { abi: 2, profile: "rv32-graphics" };
  globalThis.fetch = async (url) =>
    String(url).endsWith("manifest.json")
      ? new Response(JSON.stringify(manifest))
      : new Response(project);
  const base = new URL("http://localhost/package/");
  try {
    await assert.rejects(fetchPackage(base), /unsupported/);
    manifest = { abi: 1, profile: "rv32-graphics" };
    await assert.rejects(fetchPackage(base), /unverified/i);
    manifest = {
      ...manifest,
      validation: { passed: true },
      projectSha256: hash,
      assets: { "project.cv": "bad" },
    };
    await assert.rejects(fetchPackage(base), /hash mismatch/);
    manifest.assets["project.cv"] = hash;
    assert.equal((await fetchPackage(base)).projectText, '{"scopes":[]}');
    manifest.assets["../project.cv"] = hash;
    await assert.rejects(fetchPackage(base), /asset path/);
  } finally {
    globalThis.fetch = original;
  }
});
