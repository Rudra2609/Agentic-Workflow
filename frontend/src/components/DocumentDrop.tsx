"use client";

/**
 * The requirements in-tray: drop files or whole folders on it, or pick them. A sheet hovers over the tray and sinks
 * in while something is dragged over. Chosen documents show as filed slips, grouped under a folder tab per folder
 * (an assignment split into Part A, Part B, Part C shows as three folders); each slip has Replace and Remove, and
 * "Add files" / "Add a folder" add more. The real controls are visually hidden file inputs, so keyboard and
 * screen-reader use is the browser's own file picker.
 */
import { useId, useRef, useState, type DragEvent } from "react";

import {
  DOCUMENT_ACCEPT,
  MAX_DOCUMENTS,
  documentProblem,
  extensionOf,
  filesFromEntries,
  folderOf,
  groupByFolder,
  mergeDocuments,
  withoutCommonRoot,
  type DocItem,
  type EntryLike,
} from "@/lib/documents";
import { formatBytes } from "@/lib/format";

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer.types).includes("Files");
// React passes unknown attributes through; TypeScript's input props don't know the folder-picker ones.
const FOLDER_PICKER = { webkitdirectory: "", directory: "" } as object;

/** Files from a drop, walking into dropped folders. Entries must be taken before the first await. */
async function dropped(dt: DataTransfer): Promise<DocItem[]> {
  const entries = Array.from(dt.items)
    .filter((i) => i.kind === "file")
    .map((i) => i.webkitGetAsEntry?.() as EntryLike | null);
  const plain = Array.from(dt.files).map((file) => ({ file, path: file.name }));
  if (!entries.some((e) => e?.isDirectory)) return plain;
  return filesFromEntries(entries.filter((e): e is EntryLike => Boolean(e)));
}

const keycap =
  "hm-key inline-flex h-9 cursor-pointer items-center rounded-[5px] border border-line-strong bg-surface px-3.5 text-sm font-medium text-fg hover:bg-surface-2";

export function DocumentDrop({
  id,
  docs,
  onChange,
  onMessage,
  describedBy,
  invalid,
}: {
  id: string;
  docs: readonly DocItem[];
  onChange: (docs: DocItem[]) => void;
  /** A plain-words note about files that were left out, or null to clear it. */
  onMessage: (message: string | null) => void;
  describedBy?: string;
  invalid?: boolean;
}) {
  const [over, setOver] = useState(false);
  const folderId = useId();
  const formatsId = useId();
  const replaceRef = useRef<HTMLInputElement>(null);
  const replacing = useRef<number | null>(null);

  function add(incoming: DocItem[]) {
    if (incoming.length === 0) return;
    const { docs: next, message } = mergeDocuments(docs, incoming);
    onChange(next);
    onMessage(message);
  }

  function replace(file: File | undefined) {
    const index = replacing.current;
    replacing.current = null;
    if (!file || index === null || !docs[index]) return;
    const folder = folderOf(docs[index].path);
    const path = folder ? `${folder}/${file.name}` : file.name;
    const problem = documentProblem(file, path);
    if (problem) return onMessage(problem);
    onChange(docs.map((d, i) => (i === index ? { file, path } : d)));
    onMessage(null);
  }

  const drag = {
    onDragEnter: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      setOver(true);
    },
    onDragOver: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    },
    onDragLeave: (e: DragEvent) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false);
    },
    onDrop: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      setOver(false);
      dropped(e.dataTransfer).then(add, () => onMessage("That folder couldn't be read. Try choosing it with “Add a folder”."));
    },
  };

  const shown = withoutCommonRoot(docs);
  const groups = groupByFolder(shown);
  const foldered = groups.some((g) => g.folder !== null);
  const total = docs.reduce((n, d) => n + d.file.size, 0);
  const describe = [formatsId, describedBy].filter(Boolean).join(" ");

  return (
    <div
      {...drag}
      data-over={over || undefined}
      className="hm-intray-zone group rounded-[6px] has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-focus"
    >
      <input
        id={id}
        type="file"
        multiple
        accept={DOCUMENT_ACCEPT}
        className="sr-only"
        aria-label={docs.length ? "Add files" : "Choose files"}
        aria-describedby={describe}
        aria-invalid={invalid || undefined}
        onChange={(e) => {
          add(Array.from(e.target.files ?? []).map((file) => ({ file, path: file.name })));
          e.target.value = ""; // choosing the same file again still fires change
        }}
      />
      <input
        id={folderId}
        type="file"
        {...FOLDER_PICKER}
        className="sr-only"
        aria-label={docs.length ? "Add a folder" : "Choose a folder"}
        aria-describedby={describe}
        onChange={(e) => {
          add(Array.from(e.target.files ?? []).map((file) => ({ file, path: file.webkitRelativePath || file.name })));
          e.target.value = "";
        }}
      />
      <input
        ref={replaceRef}
        type="file"
        accept={DOCUMENT_ACCEPT}
        tabIndex={-1}
        aria-hidden="true"
        className="sr-only"
        onChange={(e) => {
          replace(e.target.files?.[0]);
          e.target.value = "";
        }}
      />

      {docs.length === 0 ? (
        <div className="flex flex-col items-center gap-5 px-6 py-7 text-center sm:flex-row sm:gap-9 sm:px-9 sm:text-left">
          <label htmlFor={id} aria-hidden="true" className="hm-intray cursor-pointer">
            <span className="hm-intray-back" />
            <span className="hm-intray-sheet" />
            <span className="hm-intray-lip" />
          </label>
          <div className="min-w-0">
            <p className="text-lg font-semibold tracking-tight text-fg">{over ? "Let go to file them" : "Drop your requirements documents here"}</p>
            <p className="mt-1 text-sm text-fg-2">Files or whole folders. If the work comes in parts, a folder per part is fine.</p>
            <div className="mt-3 flex flex-wrap items-center justify-center gap-2 sm:justify-start">
              <label htmlFor={id} className={keycap}>
                Choose files
              </label>
              <label htmlFor={folderId} className={keycap}>
                Choose a folder
              </label>
            </div>
            <p id={formatsId} className="mt-2.5 text-xs text-muted">
              PDF, Word, text, Markdown, PNG or JPEG. Up to {MAX_DOCUMENTS} files, 25 MB each.
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-6 px-4 py-5 sm:px-6">
          {groups.map((g) => (
            <section key={g.folder ?? ""} aria-label={g.folder ? `Folder ${g.folder}` : "Files"}>
              {foldered && (
                <h4 className="hm-folder-tab text-sm text-fg">
                  <span aria-hidden="true" className="hm-folder-glyph" />
                  {g.folder ?? "Not in a folder"}
                  <span className="text-xs font-normal text-muted">
                    {g.docs.length} file{g.docs.length === 1 ? "" : "s"}
                  </span>
                </h4>
              )}
              <ul className={foldered ? "hm-clipped space-y-2.5 rounded-[3px] rounded-tl-none p-3" : "space-y-2.5"}>
                {g.docs.map(({ doc, index }) => {
                  const name = doc.path.split("/").pop() ?? doc.path;
                  return (
                    <li key={`${doc.path}:${index}`} className="hm-slip flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[3px] px-4 py-3">
                      <span aria-hidden="true" className="hm-doc-icon">
                        <span className="hm-stamp text-accent-ink">{extensionOf(name).toUpperCase()}</span>
                      </span>
                      <span className="min-w-0 flex-1 basis-48">
                        <span className="block truncate font-semibold text-fg">{name}</span>
                        <span className="block text-xs text-muted">{formatBytes(doc.file.size)}</span>
                      </span>
                      <span className="flex items-center gap-1">
                        <button
                          type="button"
                          aria-label={`Replace ${name}`}
                          onClick={() => {
                            replacing.current = index;
                            replaceRef.current?.click();
                          }}
                          className="h-8 rounded-[5px] px-2.5 text-sm text-fg-2 hover:bg-hover hover:text-fg"
                        >
                          Replace
                        </button>
                        <button
                          type="button"
                          aria-label={`Remove ${name}`}
                          onClick={() => {
                            onChange(docs.filter((_, i) => i !== index));
                            onMessage(null);
                          }}
                          className="h-8 rounded-[5px] px-2.5 text-sm text-danger hover:bg-danger-soft"
                        >
                          Remove
                        </button>
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-dotted border-line-strong pt-4">
            <label htmlFor={id} className={keycap}>
              Add files
            </label>
            <label htmlFor={folderId} className={keycap}>
              Add a folder
            </label>
            <p id={formatsId} className="min-w-0 flex-1 basis-56 text-xs text-muted">
              {over
                ? "Let go to add them."
                : `${docs.length} of ${MAX_DOCUMENTS} documents, ${formatBytes(total)}. Drop more files or folders here to add them.`}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
