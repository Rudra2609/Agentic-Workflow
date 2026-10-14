import { defineFeature } from "@/lib/features";

import { PlanPanel } from "./PlanPanel";

/** Member 3 (Sprint 3): the plan as a dependency graph, roadmap and coverage matrix; edit, approve or change it. */
export default defineFeature({
  id: "planning",
  title: "Plan",
  ProjectPanel: PlanPanel,
  order: 20,
});
