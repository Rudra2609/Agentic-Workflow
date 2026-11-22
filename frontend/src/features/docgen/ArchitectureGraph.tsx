"use client";

/**
 * The architecture as a graph (React Flow, the same library as the plan graph): components left to right in import
 * order, libraries and compose services in the last column. Every solid arrow is an import in the code; dashed =
 * "uses this library".
 */
import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { useMemo } from "react";

import { cx } from "@/components/ui";

import { NODE_H, NODE_W, layoutGraph } from "./logic";
import type { GraphEdge, GraphNode } from "./types";

const KIND_CLASS: Record<GraphNode["kind"], string> = {
  component: "border-line bg-surface",
  library: "border-dashed border-line-strong bg-surface-2",
  service: "border-[var(--hm-info)] bg-surface-2",
};

export function ArchitectureGraph({
  nodes,
  edges,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
}) {
  const flow = useMemo(() => {
    const pos = layoutGraph(nodes, edges);
    const ns: Node[] = nodes.map((n) => ({
      id: n.id,
      position: pos.get(n.id) ?? { x: 0, y: 0 },
      draggable: true,
      data: {
        label: (
          <div className="flex flex-col text-left" title={n.label}>
            <span
              className={cx(
                "truncate text-xs font-medium text-fg",
                n.entry && "underline",
              )}
            >
              {n.label}
            </span>
            <span className="text-2xs text-muted">
              {n.kind === "component"
                ? `${n.modules ?? 0} module(s) · ${n.lines ?? 0} lines`
                : n.kind}
            </span>
          </div>
        ),
      },
      style: { width: NODE_W, height: NODE_H, padding: "4px 8px" },
      className: cx("rounded-md border !shadow-sm", KIND_CLASS[n.kind]),
    }));
    const es: Edge[] = edges.map((e, i) => ({
      id: `e${i}`,
      source: e.from,
      target: e.to,
      animated: false,
      style:
        e.kind === "uses"
          ? { strokeDasharray: "4 3", opacity: 0.6 }
          : undefined,
      markerEnd: { type: MarkerType.ArrowClosed },
      label: e.count > 1 ? String(e.count) : undefined,
    }));
    return { ns, es };
  }, [nodes, edges]);

  return (
    <div
      className="h-[28rem] w-full rounded-md border border-line"
      aria-label="Architecture graph"
    >
      <ReactFlow
        nodes={flow.ns}
        edges={flow.es}
        fitView
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
