/** Types for scripts/gen-features.mjs (used by the Vitest suite). */
export interface ScannedFeature {
  dir: string;
  id: string;
  title: string;
  route: string | undefined;
  file: string;
}

export declare const ID_PATTERN: RegExp;
export declare const ROUTE_PATTERN: RegExp;
export declare const GENERATED_FILENAME: string;

export declare class FeatureRegistryError extends Error {}

export declare function scanFeatures(featuresDir: string): Promise<ScannedFeature[]>;
export declare function importName(id: string): string;
export declare function renderRegistry(features: readonly ScannedFeature[]): string;
export declare function generateRegistry(options?: {
  featuresDir?: string;
  outFile?: string;
}): Promise<{ features: ScannedFeature[]; outFile: string; changed: boolean }>;
