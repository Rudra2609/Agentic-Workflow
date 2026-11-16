import { defineFeature } from "@/lib/features";

import { CodingPanel } from "./CodingPanel";

/** Member 7 (Sprint 7): the coding agent's steps — live tool-call log, diff viewer, command output, request changes. */
export default defineFeature({
  id: "coding",
  title: "Coding",
  ProjectPanel: CodingPanel,
  order: 40,
});
