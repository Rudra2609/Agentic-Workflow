import { defineFeature } from "@/lib/features";

import { RequirementsPanel } from "./RequirementsPanel";

/** Member 2 (Sprint 2): the requirements found in a project's documents, with sources, edits and versions. */
export default defineFeature({
  id: "doc_intel",
  title: "Requirements",
  ProjectPanel: RequirementsPanel,
  order: 10,
});
