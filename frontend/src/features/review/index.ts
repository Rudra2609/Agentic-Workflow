import { defineFeature } from "@/lib/features";

import { ReviewPanel } from "./ReviewPanel";

/** Member 10 (Sprint 10): final review — requirement verdicts, marks, failures traced to their step, the recovery
 * rounds, and a person's override / accept / request changes. */
export default defineFeature({
  id: "review",
  title: "Review",
  ProjectPanel: ReviewPanel,
  order: 60,
});
