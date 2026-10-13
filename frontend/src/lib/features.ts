/**
 * Feature-panel plug-in contract. Each member owns `src/features/<id>/` and default-exports a manifest from its
 * `index.ts(x)`; `scripts/gen-features.mjs` collects them into `src/features/_registry.generated.ts`.
 */
import type { ComponentType } from "react";

import type { HmapEvent, Project, Task } from "./types";

/** Props every project panel receives (the project page already has this data; panels need not refetch it). */
export interface ProjectPanelProps {
  projectId: string;
  project: Project;
  /** All tasks of the project, refreshed live. */
  tasks: readonly Task[];
  /** Live events of this project (plus project-less agent events), oldest first. */
  events: readonly HmapEvent[];
  /** Refetch project + tasks (e.g. after the panel created a task). */
  reload: () => void;
}

export interface FeaturePageProps {
  /** The `route` segment the page is served at: `/features/<route>`. */
  route: string;
}

export interface FeatureManifest {
  /** Unique id (lower case, digits, - or _); must equal the folder name, e.g. "doc_intel". */
  id: string;
  /** Tab label on the project page / sidebar label for the Page. */
  title: string;
  /** Required with `Page`: served at `/features/<route>`. */
  route?: string;
  /** Rendered as a tab on every project detail page. */
  ProjectPanel?: ComponentType<ProjectPanelProps>;
  /** Stand-alone page with its own sidebar entry. */
  Page?: ComponentType<FeaturePageProps>;
  /** Sort key (lower first, default 100); ties sorted by title. */
  order?: number;
}

/** Identity helper that gives manifests full type checking. */
export function defineFeature<T extends FeatureManifest>(manifest: T): T {
  return manifest;
}

/** Runtime validation (defence in depth behind the generator): returns the sorted manifests or throws. */
export function validateFeatures(manifests: readonly unknown[]): FeatureManifest[] {
  const problems: string[] = [];
  const ids = new Set<string>();
  const routes = new Set<string>();
  const valid: FeatureManifest[] = [];

  manifests.forEach((raw, i) => {
    if (!raw || typeof raw !== "object") {
      problems.push(`feature #${i} did not default-export a manifest object`);
      return;
    }
    const m = raw as Partial<FeatureManifest>;
    const label = typeof m.id === "string" ? `"${m.id}"` : `#${i}`;
    if (typeof m.id !== "string" || !/^[a-z][a-z0-9_-]*$/.test(m.id)) problems.push(`feature ${label}: bad id`);
    else if (ids.has(m.id)) problems.push(`feature ${label}: duplicate id`);
    if (typeof m.title !== "string" || !m.title.trim()) problems.push(`feature ${label}: missing title`);
    if (m.ProjectPanel === undefined && m.Page === undefined) problems.push(`feature ${label}: no ProjectPanel or Page`);
    if (m.Page !== undefined && !m.route) problems.push(`feature ${label}: a Page needs a route`);
    if (m.route !== undefined) {
      if (!/^[a-z0-9][a-z0-9-]*$/.test(m.route)) problems.push(`feature ${label}: bad route "${m.route}"`);
      else if (routes.has(m.route)) problems.push(`feature ${label}: duplicate route "${m.route}"`);
      routes.add(m.route);
    }
    if (typeof m.id === "string") ids.add(m.id);
    valid.push(m as FeatureManifest);
  });

  if (problems.length > 0) throw new Error(`Invalid feature manifests:\n  - ${problems.join("\n  - ")}`);
  return valid.sort((a, b) => (a.order ?? 100) - (b.order ?? 100) || a.title.localeCompare(b.title));
}
