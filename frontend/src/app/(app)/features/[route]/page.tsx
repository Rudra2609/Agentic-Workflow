import type { Metadata } from "next";

import { findFeaturePage } from "@/lib/featureRegistry";
import { FeaturePageView } from "@/views/FeaturePageView";

type Params = { params: Promise<{ route: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { route } = await params;
  return { title: findFeaturePage(route)?.title ?? "Feature" };
}

export default async function FeaturePage({ params }: Params) {
  const { route } = await params;
  return <FeaturePageView route={route} />;
}
