"use client";

import { useState } from "react";

import { Badge, Button, EmptyState, ErrorState, LoadingState, Mono } from "@/components/ui";
import { usePreferences } from "@/lib/preferences";

import { pageImageUrl } from "./client";
import { findSource, highlight } from "./logic";
import type { DocumentModel, SourceRef } from "./types";

/**
 * Where an item came from: the page image with the source block outlined (PDF / scan / photo), or the document text
 * with the quote highlighted (DOCX / text, or when a page image is not available).
 */
export function SourceView({
  projectId,
  model,
  loading,
  error,
  onRetry,
  sourceRef,
  label,
  onClose,
}: {
  projectId: string;
  model: DocumentModel | undefined;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  sourceRef: SourceRef | null;
  label: string;
  onClose: () => void;
}) {
  const { developer } = usePreferences();
  const [imageFailed, setImageFailed] = useState(false);
  if (loading) return <LoadingState label="Opening the document…" />;
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  const { doc, block } = findSource(model, sourceRef);
  if (!sourceRef || !doc) {
    return <EmptyState title="No source for this item">It was added by hand, or its document is no longer stored.</EmptyState>;
  }
  const page = block?.page ?? sourceRef.page;
  const showImage = (doc.kind === "pdf" || doc.kind === "image") && page && !imageFailed;
  const blockText = block?.text ?? "";
  const span: [number, number] | null =
    block && sourceRef.char_span
      ? [sourceRef.char_span[0] - block.char_start, sourceRef.char_span[1] - block.char_start]
      : null;
  const segments = highlight(blockText, sourceRef.quote, span);
  const pageInfo = doc.pages.find((p) => p.number === page);

  return (
    <div className="space-y-3" aria-live="polite">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-fg">Source of {label}</p>
          <p className="mt-0.5 text-xs text-muted">
            {doc.folder ? `${doc.folder} / ` : ""}
            {doc.name}
            {page ? ` · page ${page}` : ""}
            {block && block.section_path.length > 0 ? ` · ${block.section_path.join(" › ")}` : ""}
          </p>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>

      {pageInfo?.ocr && (
        <p className="text-xs text-muted">
          This page is a scan or photo; its text was read with{" "}
          {pageInfo.ocr_engine === "vision" ? "an AI vision model" : pageInfo.ocr_engine === "tesseract" ? "Tesseract OCR" : "no OCR"}.
        </p>
      )}

      {showImage ? (
        <figure className="relative overflow-hidden rounded-[3px] border border-line bg-white">
          {/* eslint-disable-next-line @next/next/no-img-element -- an authenticated API image, not a static asset */}
          <img
            src={pageImageUrl(projectId, doc.doc_id, page)}
            alt={`Page ${page} of ${doc.name}`}
            className="block h-auto w-full"
            onError={() => setImageFailed(true)}
          />
          {block?.bbox && (
            <span
              aria-hidden="true"
              className="pointer-events-none absolute rounded-[2px] bg-warning/20 outline-2 outline-warning"
              style={{
                left: `${block.bbox[0] * 100}%`,
                top: `${block.bbox[1] * 100}%`,
                width: `${(block.bbox[2] - block.bbox[0]) * 100}%`,
                height: `${(block.bbox[3] - block.bbox[1]) * 100}%`,
              }}
            />
          )}
          <figcaption className="sr-only">The highlighted area is where this item was found.</figcaption>
        </figure>
      ) : null}

      {blockText ? (
        <blockquote className="border-l-2 border-warning bg-surface-2 px-3 py-2 text-sm leading-relaxed text-fg-2">
          {segments.map((s, i) =>
            s.mark ? (
              <mark key={i} className="rounded-[2px] bg-warning/25 px-0.5 text-fg">
                {s.text}
              </mark>
            ) : (
              <span key={i}>{s.text}</span>
            ),
          )}
        </blockquote>
      ) : sourceRef.quote ? (
        <blockquote className="border-l-2 border-line-strong px-3 py-2 text-sm text-fg-2">“{sourceRef.quote}”</blockquote>
      ) : null}

      {developer && (
        <p className="flex flex-wrap gap-2 text-2xs text-muted">
          <Badge>doc {doc.kind}</Badge>
          {block && <Mono>{block.id}</Mono>}
          {sourceRef.char_span && <Mono>chars {sourceRef.char_span.join("–")}</Mono>}
          {pageInfo?.ocr_confidence != null && <Mono>OCR conf {pageInfo.ocr_confidence}</Mono>}
        </p>
      )}
    </div>
  );
}
