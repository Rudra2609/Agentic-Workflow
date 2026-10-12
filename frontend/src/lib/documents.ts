/**
 * Requirements documents chosen before a project starts: checks, merging, folder handling. Pure functions (the
 * drop zone in components/DocumentDrop.tsx is the UI). Limits mirror the API (routers/projects.py).
 */
import { formatBytes } from "./format";

export const DOCUMENT_ACCEPT = ".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,application/pdf,text/plain,text/markdown,image/png,image/jpeg";
export const MAX_DOCUMENT_BYTES = 25 * 1024 * 1024;
export const MAX_DOCUMENTS = 20;
export const MAX_TOTAL_BYTES = 100 * 1024 * 1024;
const EXTENSIONS = new Set(["pdf", "docx", "txt", "md", "png", "jpg", "jpeg"]);

/** A chosen file and where it sits: "Part A/brief.pdf", or just "brief.pdf". */
export interface DocItem {
  file: File;
  path: string;
}

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

export function folderOf(path: string): string | null {
  const slash = path.lastIndexOf("/");
  return slash > 0 ? path.slice(0, slash) : null;
}

/** Why a file can't be used, in plain words, or null when it can. */
export function documentProblem(file: File, path = file.name): string | null {
  if (!EXTENSIONS.has(extensionOf(file.name))) {
    return `“${path}” isn't a supported type. Use a PDF, Word, text, Markdown, PNG or JPEG file.`;
  }
  if (file.size > MAX_DOCUMENT_BYTES) return `“${path}” is ${formatBytes(file.size)}; the limit is 25 MB.`;
  if (file.size === 0) return `“${path}” is empty.`;
  return null;
}

function names(paths: readonly string[]): string {
  const shown = paths.slice(0, 3).map((p) => `“${p}”`).join(", ");
  return paths.length > 3 ? `${shown} and ${paths.length - 3} more` : shown;
}

/**
 * Adds `incoming` to `current`: hidden files (".DS_Store") are ignored, exact duplicates (same path and size) are
 * skipped, unusable files are left out with a reason, and the count and total-size limits are kept. Returns the
 * new list and one message for the person, or null when everything was added.
 */
export function mergeDocuments(current: readonly DocItem[], incoming: readonly DocItem[]): { docs: DocItem[]; message: string | null } {
  const docs = [...current];
  const seen = new Set(current.map((d) => `${d.path}:${d.file.size}`));
  let total = current.reduce((n, d) => n + d.file.size, 0);
  const rejected: { path: string; problem: string }[] = [];
  let overCount = 0;
  let overSize = 0;
  for (const d of incoming) {
    const name = d.path.split("/").pop() ?? d.path;
    if (name.startsWith(".")) continue;
    const key = `${d.path}:${d.file.size}`;
    if (seen.has(key)) continue;
    const problem = documentProblem(d.file, d.path);
    if (problem) {
      rejected.push({ path: d.path, problem });
      continue;
    }
    if (docs.length >= MAX_DOCUMENTS) {
      overCount += 1;
      continue;
    }
    if (total + d.file.size > MAX_TOTAL_BYTES) {
      overSize += 1;
      continue;
    }
    seen.add(key);
    docs.push(d);
    total += d.file.size;
  }
  const parts: string[] = [];
  if (rejected.length === 1) parts.push(rejected[0]!.problem);
  else if (rejected.length > 1) parts.push(`Left out ${rejected.length} files that can't be used (only PDF, Word, text, Markdown, PNG and JPEG up to 25 MB): ${names(rejected.map((r) => r.path))}.`);
  if (overCount) parts.push(`A project takes at most ${MAX_DOCUMENTS} documents; ${overCount} more ${overCount === 1 ? "was" : "were"} not added.`);
  if (overSize) parts.push(`All documents together may be at most 100 MB; ${overSize} ${overSize === 1 ? "file was" : "files were"} not added.`);
  return { docs, message: parts.length ? parts.join(" ") : null };
}

/**
 * The folder every document shares at the top, when there is one and something below it: dropping "Assignment"
 * (with Part A, Part B, Part C inside) gives "Assignment", so the parts show as Part A, Part B, Part C.
 */
export function commonRoot(docs: readonly DocItem[]): string | null {
  if (docs.length === 0) return null;
  const roots = new Set(docs.map((d) => (d.path.includes("/") ? d.path.split("/")[0]! : null)));
  if (roots.size !== 1) return null;
  const [root] = roots;
  return root ?? null;
}

/** Paths as shown and sent: without the shared top folder. */
export function withoutCommonRoot(docs: readonly DocItem[]): DocItem[] {
  const root = commonRoot(docs);
  return root ? docs.map((d) => ({ ...d, path: d.path.slice(root.length + 1) })) : [...docs];
}

/** Groups in first-seen order; files that are not in any folder come first under `folder: null`. */
export function groupByFolder(docs: readonly DocItem[]): { folder: string | null; docs: { doc: DocItem; index: number }[] }[] {
  const groups = new Map<string | null, { doc: DocItem; index: number }[]>();
  docs.forEach((doc, index) => {
    const folder = folderOf(doc.path);
    if (!groups.has(folder)) groups.set(folder, []);
    groups.get(folder)!.push({ doc, index });
  });
  return [...groups.entries()]
    .sort(([a], [b]) => (a === null ? -1 : b === null ? 1 : 0))
    .map(([folder, list]) => ({ folder, docs: list }));
}

/** A project name from the chosen documents: the shared top folder, else the first file's name. */
export function suggestName(docs: readonly DocItem[]): string {
  const root = commonRoot(docs);
  if (root) return root;
  const first = docs[0];
  if (!first) return "";
  const name = first.path.split("/").pop() ?? first.path;
  return name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
}

/** Minimal shape of the browser's FileSystemEntry API (drag-and-drop of folders). */
export interface EntryLike {
  isFile: boolean;
  isDirectory: boolean;
  fullPath: string;
  file?: (ok: (f: File) => void, fail: (e: unknown) => void) => void;
  createReader?: () => { readEntries: (ok: (entries: EntryLike[]) => void, fail: (e: unknown) => void) => void };
}

/**
 * Every file under the dropped entries, in order, with its path inside the drop ("Part A/brief.pdf"). Stops after
 * `limit` files so dropping a huge folder can't hang the page.
 */
export async function filesFromEntries(entries: readonly EntryLike[], limit = 200): Promise<DocItem[]> {
  const out: DocItem[] = [];
  async function walk(entry: EntryLike): Promise<void> {
    if (out.length >= limit) return;
    if (entry.isFile && entry.file) {
      const file = await new Promise<File>((ok, fail) => entry.file!(ok, fail));
      out.push({ file, path: entry.fullPath.replace(/^\/+/, "") || file.name });
    } else if (entry.isDirectory && entry.createReader) {
      const reader = entry.createReader();
      for (;;) {
        const batch = await new Promise<EntryLike[]>((ok, fail) => reader.readEntries(ok, fail));
        if (batch.length === 0) break;
        for (const child of batch) await walk(child);
      }
    }
  }
  for (const entry of entries) await walk(entry);
  return out;
}
