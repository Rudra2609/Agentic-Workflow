import { describe, expect, it } from "vitest";

import { validateFeatures } from "@/lib/features";
import { FEATURES, PROJECT_PANELS, FEATURE_PAGES, findFeaturePage } from "@/lib/featureRegistry";

const Panel = () => null;

describe("feature registry", () => {
  it("loads the shipped echo example as a panel and a page", () => {
    expect(FEATURES.map((f) => f.id)).toContain("echo");
    expect(PROJECT_PANELS.some((f) => f.id === "echo")).toBe(true);
    expect(FEATURE_PAGES.some((f) => f.route === "echo")).toBe(true);
    expect(findFeaturePage("echo")?.title).toBe("Echo");
    expect(findFeaturePage("nope")).toBeUndefined();
  });

  it("sorts by order then title", () => {
    const sorted = validateFeatures([
      { id: "b", title: "B", ProjectPanel: Panel },
      { id: "a", title: "A", ProjectPanel: Panel, order: 200 },
      { id: "c", title: "C", ProjectPanel: Panel, order: 1 },
    ]);
    expect(sorted.map((f) => f.id)).toEqual(["c", "b", "a"]);
  });

  it("rejects duplicates and incomplete manifests at runtime", () => {
    expect(() =>
      validateFeatures([
        { id: "x", title: "X", ProjectPanel: Panel },
        { id: "x", title: "X2", ProjectPanel: Panel },
      ]),
    ).toThrow(/duplicate id/);
    expect(() => validateFeatures([{ id: "y", title: "Y", Page: Panel }])).toThrow(/a Page needs a route/);
    expect(() => validateFeatures([undefined])).toThrow(/did not default-export/);
  });
});
