import type { Metadata } from "next";

import { TeamView } from "@/views/TeamView";

export const metadata: Metadata = { title: "AI team" };

export default function Page() {
  return <TeamView />;
}
