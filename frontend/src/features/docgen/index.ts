import { defineFeature } from "@/lib/features";

import { DocsPanel } from "./DocsPanel";

/** Member 9 (Sprint 9): generated documentation — preview, every claim checked against the code, examples, regenerate. */
export default defineFeature({
  id: "docgen",
  title: "Docs",
  ProjectPanel: DocsPanel,
  order: 50,
});
