import { defineFeature } from "@/lib/features";

import { RefinePanel } from "./RefinePanel";

/** Member 4 (Sprint 4): how each result was checked and improved — rounds, problems by kind, scores, what changed. */
export default defineFeature({
  id: "refine",
  title: "Refinement",
  ProjectPanel: RefinePanel,
  order: 30,
});
