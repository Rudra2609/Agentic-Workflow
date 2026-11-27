import { defineFeature } from "@/lib/features";

import { ModelsPage } from "./ModelsPage";

/** Member 11 (Sprint 11): models — the router's live decisions, the model registry, what fits on this machine,
 * the benchmark and the fine-tune experiment. */
export default defineFeature({
  id: "models",
  title: "Models",
  route: "models",
  Page: ModelsPage,
  order: 95,
});
