"use client";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { EmptyState, PageHeader } from "@/components/ui";
import { findFeaturePage } from "@/lib/featureRegistry";

export function FeaturePageView({ route }: { route: string }) {
  const feature = findFeaturePage(route);
  if (!feature?.Page) {
    return (
      <>
        <PageHeader title="Feature not found" />
        <EmptyState title={`No feature page is registered at /features/${route}.`} />
      </>
    );
  }
  const Page = feature.Page;
  return (
    <ErrorBoundary name={feature.title}>
      <Page route={route} />
    </ErrorBoundary>
  );
}
