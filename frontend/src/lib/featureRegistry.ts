/** The discovered features (see src/features/README.md). Import from here, never from the generated file. */
import { FEATURE_MODULES } from "@/features/_registry.generated";

import { validateFeatures, type FeatureManifest } from "./features";

export const FEATURES: readonly FeatureManifest[] = validateFeatures(FEATURE_MODULES);

export const PROJECT_PANELS = FEATURES.filter((f) => f.ProjectPanel !== undefined);

export const FEATURE_PAGES = FEATURES.filter((f) => f.Page !== undefined && f.route);

export function findFeaturePage(route: string): FeatureManifest | undefined {
  return FEATURE_PAGES.find((f) => f.route === route);
}
