import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { FeatureRegistryError, generateRegistry, scanFeatures } from "../scripts/gen-features.mjs";

let root: string;

async function feature(dir: string, file: string, source: string) {
  await mkdir(path.join(root, dir), { recursive: true });
  await writeFile(path.join(root, dir, file), source, "utf8");
}

const manifest = (id: string, extra = "") => `
import { defineFeature } from "@/lib/features";
import { Panel } from "./Panel";
export default defineFeature({ id: "${id}", title: "${id} title", ProjectPanel: Panel${extra} });
`;

beforeEach(async () => {
  root = await mkdtemp(path.join(tmpdir(), "hmap-features-"));
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

describe("gen-features", () => {
  it("writes a registry that imports every feature folder, sorted", async () => {
    await feature("research", "index.tsx", manifest("research", ', route: "research", Page: Panel'));
    await feature("doc-intel", "index.ts", manifest("doc-intel"));

    const out = path.join(root, "_registry.generated.ts");
    const result = await generateRegistry({ featuresDir: root, outFile: out });

    expect(result.features.map((f) => f.id)).toEqual(["doc-intel", "research"]);
    expect(result.changed).toBe(true);
    const text = await readFile(out, "utf8");
    expect(text).toContain('import feature_doc_intel from "./doc-intel";');
    expect(text).toContain('import feature_research from "./research";');
    expect(text).toMatch(/FEATURE_MODULES: readonly FeatureManifest\[\] = \[\s*feature_doc_intel,\s*feature_research,\s*\]/);
    expect(text).toContain("DO NOT EDIT");

    // deterministic: a second run with no changes does not rewrite the file
    expect((await generateRegistry({ featuresDir: root, outFile: out })).changed).toBe(false);
  });

  it("ignores _private and dot folders and writes an empty registry when there are no features", async () => {
    await feature("_shared", "index.ts", "export const x = 1;");
    await feature(".cache", "index.ts", "junk");
    const out = path.join(root, "_registry.generated.ts");
    const result = await generateRegistry({ featuresDir: root, outFile: out });
    expect(result.features).toEqual([]);
    expect(await readFile(out, "utf8")).toContain("FEATURE_MODULES: readonly FeatureManifest[] = [];");
  });

  it("rejects a manifest without a default export with a clear message", async () => {
    await feature("broken", "index.ts", 'export const manifest = { id: "broken", title: "B" };');
    await expect(scanFeatures(root)).rejects.toThrow(FeatureRegistryError);
    await expect(scanFeatures(root)).rejects.toThrow(/broken[\\/]index\.ts: missing `export default defineFeature/);
  });

  it("lists every problem at once (id/folder mismatch, missing title, missing index, Page without route)", async () => {
    await feature("alpha", "index.ts", 'export default defineFeature({ id: "beta", title: "A", ProjectPanel: P });');
    await feature("gamma", "index.ts", 'export default defineFeature({ id: "gamma", ProjectPanel: P });');
    await feature("delta", "Panel.tsx", "export {};");
    await feature("eps", "index.ts", 'export default defineFeature({ id: "eps", title: "E", Page: P });');

    const err = (await scanFeatures(root).catch((e: unknown) => e)) as Error;
    expect(err).toBeInstanceOf(FeatureRegistryError);
    expect(err.message).toContain('id "beta" must equal its folder name "alpha"');
    expect(err.message).toContain("manifest has no `title`");
    expect(err.message).toMatch(/delta[\\/] has no index\.ts or index\.tsx/);
    expect(err.message).toContain("a feature with a Page needs a `route`");
  });

  it("rejects non-literal ids, bad ids, duplicate routes and empty manifests", async () => {
    await feature("one", "index.ts", 'const ID = "one"; export default defineFeature({ id: ID, title: "1", ProjectPanel: P });');
    await feature("Two", "index.ts", 'export default defineFeature({ id: "Two", title: "2", ProjectPanel: P });');
    await feature("three", "index.ts", 'export default defineFeature({ id: "three", title: "3", route: "x", Page: P });');
    await feature("four", "index.ts", 'export default defineFeature({ id: "four", title: "4", route: "x", Page: P });');
    await feature("five", "index.ts", 'export default defineFeature({ id: "five", title: "5" });');

    const err = (await scanFeatures(root).catch((e: unknown) => e)) as Error;
    expect(err.message).toContain("`id` must be a plain string literal");
    expect(err.message).toContain('id "Two" must be lower case');
    expect(err.message).toContain('both use route "x"');
    expect(err.message).toContain("must provide a ProjectPanel and/or a Page");
  });

  it("does not write the registry when validation fails", async () => {
    await feature("bad", "index.ts", "export default {}");
    const out = path.join(root, "_registry.generated.ts");
    await expect(generateRegistry({ featuresDir: root, outFile: out })).rejects.toThrow(FeatureRegistryError);
    await expect(readFile(out, "utf8")).rejects.toThrow();
  });
});
