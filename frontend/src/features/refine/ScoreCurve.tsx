"use client";

import { cx } from "@/components/ui";

import { bestIndex, curvePath, curvePoints, iterationLabel, percent } from "./logic";

/** The score of each iteration as a small line chart (SVG, theme colours). The best iteration is a filled dot;
 * the chart has a text alternative for screen readers. */
export function ScoreCurve({
  scores,
  width = 280,
  height = 96,
  compact = false,
  target,
  className,
}: {
  scores: readonly number[];
  width?: number;
  height?: number;
  compact?: boolean;
  target?: number;
  className?: string;
}) {
  const pad = compact ? 3 : 10;
  const pts = curvePoints(scores, width, height, pad);
  const best = bestIndex(scores);
  const label = scores.length
    ? `Score by round: ${scores.map((s, i) => `${iterationLabel(i)} ${percent(s)}`).join(", ")}${best !== null ? `. Best: ${iterationLabel(best)}.` : ""}`
    : "No scores yet";
  const targetY = target !== undefined ? pad + (1 - target) * (height - 2 * pad) : null;
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={cx("max-w-full overflow-visible", className)}
    >
      <title>{label}</title>
      {!compact && (
        <>
          <line x1={pad} x2={width - pad} y1={pad} y2={pad} className="stroke-line" strokeDasharray="2 3" />
          <line x1={pad} x2={width - pad} y1={height - pad} y2={height - pad} className="stroke-line" />
          {targetY !== null && (
            <line x1={pad} x2={width - pad} y1={targetY} y2={targetY} className="stroke-success" strokeOpacity={0.6} strokeDasharray="4 3" />
          )}
        </>
      )}
      {pts.length > 1 && <path d={curvePath(pts)} fill="none" className="stroke-accent" strokeWidth={compact ? 1.5 : 2} strokeLinejoin="round" />}
      {pts.map((p) => (
        <g key={p.index}>
          <circle cx={p.x} cy={p.y} r={compact ? 2 : p.index === best ? 4.5 : 3.5} className={p.index === best ? "fill-accent" : "fill-surface stroke-accent"} strokeWidth={1.5} />
          {!compact && (
            <text x={p.x} y={Math.max(9, p.y - 8)} textAnchor="middle" className="fill-fg-2 text-[10px] tabular-nums">
              {percent(p.score)}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}
