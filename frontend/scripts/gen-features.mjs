#!/usr/bin/env node
/**
 * Feature-panel auto-registration (Sprint 1 item 1.18, UI part).
 *
 * Scans `src/features/<id>/index.ts(x)` and writes `src/features/_registry.generated.ts`, which imports each
 * folder's default-exported manifest. Runs automatically before `npm run dev|build|test|typecheck`, so a member adds
 * a UI panel by creating ONLY their own folder: no nav, layout or registry file is edited by hand.
 *
 * Each index file must `export default defineFeature({ id: "<folder name>", title: "...", ... })`.
 * The static checks here catch the common mistakes early with a clear message; `tsc` checks the full shape.
 *
 * Usage: node scripts/gen-features.mjs [--features-dir <dir>] [--out <file>]
 */
import { existsSync } from "node:fs";
import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// lower case, digits, "-" or "_": folder names follow the backend plug-in names (e.g. doc_intel, ownership.toml)
export const ID_PATTERN = /^[a-z][a-z0-9_-]*$/;
export const ROUTE_PATTERN = /^[a-z0-9][a-z0-9-]*$/;
export const GENERATED_FILENAME = "_registry.generated.ts";

export class FeatureRegistryError extends Error {
  constructor(message) {
    super(message);
    this.name = "FeatureRegistryError";
  }
}

/** Value of `key: "literal"` in the manifest source, `undefined` if absent, `null` if present but not a literal. */
function readStringProp(source, key) {
  const literal = new RegExp(`(?:^|[\\s{,])${key}\\s*:\\s*(["'])((?:(?!\\1)[^\\\\\\n])*)\\1`, "m").exec(source);
  if (literal) return literal[2];
  return new RegExp(`(?:^|[\\s{,])${key}\\s*:`, "m").test(source) ? null : undefined;
}

function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'])\/\/.*$/gm, "$1");
}

/**
 * Find and statically validate every feature folder. Throws {@link FeatureRegistryError} listing ALL problems.
 * Folders whose name starts with `_` or `.` are ignored (shared helpers, generated files).
 */
export async function scanFeatures(featuresDir) {
  if (!existsSync(featuresDir)) return [];
  const entries = (await readdir(featuresDir, { withFileTypes: true }))
    .filter((d) => d.isDirectory() && !d.name.startsWith("_") && !d.name.startsWith("."))
    .map((d) => d.name)
    .sort();

  const problems = [];
  const features = [];
  const rel = (p) => path.relative(process.cwd(), p) || p;

  for (const dir of entries) {
    const folder = path.join(featuresDir, dir);
    const candidates = ["index.ts", "index.tsx"].filter((f) => existsSync(path.join(folder, f)));
    if (candidates.length === 0) {
      problems.push(`${rel(folder)}/ has no index.ts or index.tsx (each feature folder needs one manifest file).`);
      continue;
    }
    if (candidates.length > 1) {
      problems.push(`${rel(folder)}/ has both index.ts and index.tsx; keep exactly one.`);
      continue;
    }
    const file = path.join(folder, candidates[0]);
    const source = stripComments(await readFile(file, "utf8"));
    const where = rel(file);

    if (!/\bexport\s+default\b/.test(source)) {
      problems.push(`${where}: missing \`export default defineFeature({ id: "${dir}", title: "..." })\`.`);
      continue;
    }
    const id = readStringProp(source, "id");
    const title = readStringProp(source, "title");
    const route = readStringProp(source, "route");

    if (id === undefined) problems.push(`${where}: manifest has no \`id\` (use id: "${dir}").`);
    else if (id === null) problems.push(`${where}: \`id\` must be a plain string literal, e.g. id: "${dir}".`);
    else if (!ID_PATTERN.test(id)) problems.push(`${where}: id "${id}" must be lower case (letters, digits, - or _: ${ID_PATTERN}).`);
    else if (id !== dir) problems.push(`${where}: id "${id}" must equal its folder name "${dir}".`);

    if (title === undefined) problems.push(`${where}: manifest has no \`title\`.`);
    else if (title === null || !title.trim()) problems.push(`${where}: \`title\` must be a non-empty string literal.`);

    if (route === null) problems.push(`${where}: \`route\` must be a plain string literal.`);
    else if (route !== undefined && !ROUTE_PATTERN.test(route)) {
      problems.push(`${where}: route "${route}" must be lower-case kebab-case (${ROUTE_PATTERN}).`);
    }

    const hasPanel = /\bProjectPanel\s*[:,}]/.test(source); // `ProjectPanel: X` or shorthand
    const hasPage = /\bPage\s*[:,}]/.test(source);
    if (!hasPanel && !hasPage) problems.push(`${where}: manifest must provide a ProjectPanel and/or a Page component.`);
    if (hasPage && route === undefined) problems.push(`${where}: a feature with a Page needs a \`route\`.`);

    if (typeof id === "string" && typeof title === "string") {
      features.push({ dir, id, title, route: typeof route === "string" ? route : undefined, file });
    }
  }

  const seenRoutes = new Map();
  for (const f of features) {
    if (!f.route) continue;
    const other = seenRoutes.get(f.route);
    if (other) problems.push(`Features "${other}" and "${f.id}" both use route "${f.route}"; routes must be unique.`);
    else seenRoutes.set(f.route, f.id);
  }

  if (problems.length > 0) {
    throw new FeatureRegistryError(
      `Invalid feature manifest${problems.length > 1 ? "s" : ""} (see src/features/README.md):\n` +
        problems.map((p) => `  - ${p}`).join("\n"),
    );
  }
  return features;
}

export function importName(id) {
  return `feature_${id.replace(/-/g, "_")}`;
}

/** Deterministic file contents (no timestamps), so unchanged features never touch the file. */
export function renderRegistry(features) {
  const lines = [
    "// AUTO-GENERATED by scripts/gen-features.mjs before `npm run dev|build|test|typecheck`. DO NOT EDIT.",
    "// To add a panel or page, create src/features/<id>/index.ts(x) (see src/features/README.md).",
    'import type { FeatureManifest } from "@/lib/features";',
  ];
  for (const f of features) lines.push(`import ${importName(f.id)} from "./${f.dir}";`);
  lines.push("");
  lines.push(
    features.length === 0
      ? "export const FEATURE_MODULES: readonly FeatureManifest[] = [];"
      : `export const FEATURE_MODULES: readonly FeatureManifest[] = [\n${features
          .map((f) => `  ${importName(f.id)},`)
          .join("\n")}\n];`,
  );
  lines.push("");
  return lines.join("\n");
}

export async function generateRegistry({ featuresDir, outFile } = {}) {
  const dir = featuresDir ?? path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/features");
  const out = outFile ?? path.join(dir, GENERATED_FILENAME);
  const features = await scanFeatures(dir);
  const content = renderRegistry(features);
  const previous = existsSync(out) ? await readFile(out, "utf8") : null;
  const changed = previous !== content;
  if (changed) await writeFile(out, content, "utf8");
  return { features, outFile: out, changed };
}

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--features-dir") args.featuresDir = path.resolve(argv[++i]);
    else if (argv[i] === "--out") args.outFile = path.resolve(argv[++i]);
  }
  return args;
}

const invokedDirectly = process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
if (invokedDirectly) {
  try {
    const { features, outFile, changed } = await generateRegistry(parseArgs(process.argv.slice(2)));
    const names = features.map((f) => f.id).join(", ") || "none";
    console.log(`gen-features: ${features.length} feature(s) [${names}] -> ${path.relative(process.cwd(), outFile)}${changed ? "" : " (unchanged)"}`);
  } catch (err) {
    console.error(`gen-features: ${err instanceof Error ? err.message : String(err)}`);
    process.exit(1);
  }
}
