import { defineFeature } from "@/lib/features";

import { EchoPage } from "./EchoPage";
import { EchoPanel } from "./EchoPanel";

export default defineFeature({
  id: "echo",
  title: "Echo",
  route: "echo",
  ProjectPanel: EchoPanel,
  Page: EchoPage,
  order: 1000,
});
