import { describe, expect, it } from "vitest";

import {
  MAX_DOCUMENTS,
  commonRoot,
  filesFromEntries,
  groupByFolder,
  mergeDocuments,
  suggestName,
  withoutCommonRoot,
  type DocItem,
  type EntryLike,
} from "@/lib/documents";

const MB = 1024 * 1024;
// only name and size matter to the checks, so no real bytes are allocated
const fake = (name: string, size = 1000) => ({ name, size }) as File;
const doc = (path: string, size = 1000): DocItem => ({ file: fake(path.split("/").pop()!, size), path });

describe("mergeDocuments", () => {
  it("adds usable files and says nothing", () => {
    const { docs, message } = mergeDocuments([doc("a.pdf")], [doc("Part A/b.docx"), doc("c.md")]);
    expect(docs.map((d) => d.path)).toEqual(["a.pdf", "Part A/b.docx", "c.md"]);
    expect(message).toBeNull();
  });

  it("ignores hidden files and exact duplicates silently", () => {
    const { docs, message } = mergeDocuments([doc("a.pdf")], [doc("Part A/.DS_Store"), doc("a.pdf")]);
    expect(docs).toHaveLength(1);
    expect(message).toBeNull();
  });

  it("leaves out unusable files with the reason, and keeps the good ones", () => {
    const one = mergeDocuments([], [doc("a.pdf"), doc("budget.xlsx")]);
    expect(one.docs.map((d) => d.path)).toEqual(["a.pdf"]);
    expect(one.message).toContain("“budget.xlsx” isn't a supported type");

    const many = mergeDocuments([], [doc("x.exe"), doc("Part B/big.pdf", 30 * MB), doc("empty.txt", 0), doc("y.zip"), doc("ok.txt")]);
    expect(many.docs.map((d) => d.path)).toEqual(["ok.txt"]);
    expect(many.message).toMatch(/^Left out 4 files that can't be used .*“x\.exe”, “Part B\/big\.pdf”, “empty\.txt” and 1 more\.$/);
  });

  it("keeps the count and total-size limits", () => {
    const full = Array.from({ length: MAX_DOCUMENTS }, (_, i) => doc(`${i}.txt`));
    const over = mergeDocuments(full, [doc("21.txt"), doc("22.txt")]);
    expect(over.docs).toHaveLength(MAX_DOCUMENTS);
    expect(over.message).toBe(`A project takes at most ${MAX_DOCUMENTS} documents; 2 more were not added.`);

    const heavy = Array.from({ length: 4 }, (_, i) => doc(`${i}.pdf`, 24 * MB));
    const tooBig = mergeDocuments(heavy, [doc("5.pdf", 10 * MB)]);
    expect(tooBig.docs).toHaveLength(4);
    expect(tooBig.message).toBe("All documents together may be at most 100 MB; 1 file was not added.");
  });
});

describe("folders", () => {
  it("drops the shared top folder so the parts show", () => {
    const docs = [doc("Assignment/Part A/brief.pdf"), doc("Assignment/Part B/data.md"), doc("Assignment/readme.txt")];
    expect(commonRoot(docs)).toBe("Assignment");
    expect(withoutCommonRoot(docs).map((d) => d.path)).toEqual(["Part A/brief.pdf", "Part B/data.md", "readme.txt"]);
    expect(suggestName(docs)).toBe("Assignment");
  });

  it("keeps paths when there is no shared top folder", () => {
    const docs = [doc("Part A/brief.pdf"), doc("Part B/data.md"), doc("loose.txt")];
    expect(commonRoot(docs)).toBeNull();
    expect(withoutCommonRoot(docs).map((d) => d.path)).toEqual(docs.map((d) => d.path));
    expect(suggestName(docs)).toBe("brief");
    expect(suggestName([doc("hotel_booking-spec.pdf")])).toBe("hotel booking spec");
    expect(suggestName([])).toBe("");
  });

  it("groups by folder in first-seen order, loose files first, with each file's index", () => {
    const groups = groupByFolder([doc("Part B/1.pdf"), doc("a.txt"), doc("Part A/2.pdf"), doc("Part B/3.pdf")]);
    expect(groups.map((g) => [g.folder, g.docs.map((d) => d.index)])).toEqual([
      [null, [1]],
      ["Part B", [0, 3]],
      ["Part A", [2]],
    ]);
  });
});

describe("filesFromEntries", () => {
  const fileEntry = (fullPath: string): EntryLike => ({
    isFile: true,
    isDirectory: false,
    fullPath,
    file: (ok) => ok(fake(fullPath.split("/").pop()!)),
  });
  const dirEntry = (fullPath: string, children: EntryLike[]): EntryLike => ({
    isFile: false,
    isDirectory: true,
    fullPath,
    createReader: () => {
      // browsers hand directory contents over in batches until an empty batch
      const batches = [children.slice(0, 1), children.slice(1), []];
      return { readEntries: (ok) => ok(batches.shift() ?? []) };
    },
  });

  it("walks dropped folders in order and keeps each file's path", async () => {
    const dropped = [
      dirEntry("/Part A", [fileEntry("/Part A/brief.pdf"), dirEntry("/Part A/extra", [fileEntry("/Part A/extra/x.md")])]),
      fileEntry("/loose.txt"),
    ];
    const docs = await filesFromEntries(dropped);
    expect(docs.map((d) => d.path)).toEqual(["Part A/brief.pdf", "Part A/extra/x.md", "loose.txt"]);
  });

  it("stops at the limit", async () => {
    const many = dirEntry("/big", Array.from({ length: 10 }, (_, i) => fileEntry(`/big/${i}.txt`)));
    expect(await filesFromEntries([many], 3)).toHaveLength(3);
  });
});
