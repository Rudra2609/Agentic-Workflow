import type { Metadata } from "next";

import { ProjectDetailView } from "@/views/ProjectDetailView";

export const metadata: Metadata = { title: "Project" };

export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ProjectDetailView key={id} projectId={decodeURIComponent(id)} />;
}
