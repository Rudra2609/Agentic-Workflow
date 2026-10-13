/** Shapes returned by the doc_intel API (backend `hmap/agents/doc_intel`, contract `RequirementSet`). */

export interface SourceRef {
  doc_id: string;
  page: number | null;
  block_ids: string[];
  char_span: [number, number] | null;
  quote: string | null;
  folder: string | null;
}

export type Priority = "must" | "should" | "could";

export interface Requirement {
  id: string;
  text: string;
  type: "functional" | "non_functional";
  priority: Priority;
  source_ref: SourceRef;
  confidence: number;
}

export interface Constraint {
  id: string;
  text: string;
  kind: "technology" | "format" | "process" | "resource" | "other";
  source_ref: SourceRef | null;
}

export interface Deliverable {
  id: string;
  name: string;
  format: string;
  source_ref: SourceRef | null;
}

export interface RubricLevel {
  label: string;
  description: string;
  marks: number | null;
}

export interface EvaluationCriterion {
  id: string;
  criterion: string;
  max_marks: number;
  rubric_levels: RubricLevel[];
  source_ref: SourceRef | null;
}

export interface RequirementSet {
  project_id: string;
  source_docs: Array<{ artifact_id: string; media_type: string }>;
  requirements: Requirement[];
  constraints: Constraint[];
  deliverables: Deliverable[];
  evaluation_criteria: EvaluationCriterion[];
  open_questions: string[];
  total_marks: number | null;
}

export interface VersionInfo {
  version: number;
  created_by: string;
  created_at: string;
}

export interface RequirementsResponse {
  artifact: { artifact_id: string; version: number; created_by: string; created_at: string };
  requirement_set: RequirementSet;
  versions: VersionInfo[];
}

export type BBox = [number, number, number, number];

export interface Block {
  id: string;
  type: "heading" | "paragraph" | "list_item" | "table" | "note" | "header" | "footer";
  text: string;
  page: number | null;
  bbox: BBox | null;
  level: number | null;
  section_path: string[];
  char_start: number;
  char_end: number;
  ocr: boolean;
}

export interface PageInfo {
  number: number;
  width: number;
  height: number;
  ocr: boolean;
  ocr_engine: string | null;
  ocr_confidence: number | null;
}

export interface SourceDocument {
  doc_id: string;
  name: string;
  folder: string | null;
  kind: "pdf" | "docx" | "text" | "image";
  pages: PageInfo[];
  blocks: Block[];
  text: string;
  warnings: string[];
}

export interface ExtractionInfo {
  chunks: number;
  llm_chunks: number;
  rules_only_chunks: number;
  /** "provider:model" (or "cache:<model>" when replayed, "memory" when already extracted) -> parts answered */
  answered_by: Record<string, number>;
  quotes: Record<string, number>;
  ocr_pages: Record<string, number>;
  prompt_version: string;
}

export interface DocumentModel {
  project_id: string;
  documents: SourceDocument[];
  extraction?: ExtractionInfo;
}
