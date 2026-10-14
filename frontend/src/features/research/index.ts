import { defineFeature } from "@/lib/features";

import { ResearchPanel } from "./ResearchPanel";

/** Member 5 (Sprint 5): what each research step found — sub-questions, cited findings, sources, why it stopped. */
export default defineFeature({
  id: "research",
  title: "Research",
  ProjectPanel: ResearchPanel,
  order: 25,
});
