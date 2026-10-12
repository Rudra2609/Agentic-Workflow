import type { Metadata } from "next";

import { IssuesView } from "@/views/IssuesView";

export const metadata: Metadata = { title: "Issues" };

export default function Page() {
  return <IssuesView />;
}
