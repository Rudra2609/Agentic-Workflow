import { defineFeature } from "@/lib/features";

import { OpsPage } from "./OpsPage";

/** Member 4 (Sprint 4 §5b): operations — why a step failed, dead letters and their replay, traces and dashboards. */
export default defineFeature({
  id: "ops",
  title: "Operations",
  route: "ops",
  Page: OpsPage,
  order: 90,
});
