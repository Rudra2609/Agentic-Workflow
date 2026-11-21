import { defineFeature } from "@/lib/features";

import { TestingPanel } from "./TestingPanel";

/** Member 8 (Sprint 8): test runs — stage timeline, failures with hints, logs, the test -> fix -> re-test loop, re-run. */
export default defineFeature({
  id: "testing",
  title: "Testing",
  ProjectPanel: TestingPanel,
  order: 45,
});
