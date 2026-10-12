import type { Metadata } from "next";

import { WorkspaceView } from "@/views/WorkspaceView";

export const metadata: Metadata = { title: "My projects" };

export default function Home() {
  return <WorkspaceView />;
}
