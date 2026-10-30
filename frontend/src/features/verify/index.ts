import { defineFeature } from "@/lib/features";

import { VerifyPanel } from "./VerifyPanel";

/** Member 6 (Sprint 6): every research claim checked — verdict chips, quote vs saved page, conflicts, follow-up research. */
export default defineFeature({
  id: "verify",
  title: "Verification",
  ProjectPanel: VerifyPanel,
  order: 27,
});
