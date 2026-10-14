"use client";

/**
 * The plan as a dependency graph (React Flow): steps left to right in the order they can run, coloured by phase,
 * with the critical path outlined and live step states. In edit mode, drag from a step's right handle to another
 * step to make it wait for the first; click a connection to remove it.
 */
import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  useStore,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useEffect, useMemo, useRef } from "react";

import { Status, cx } from "@/components/ui";
import { roleOf } from "@/lib/plain";

import { NODE_H, NODE_W, PHASE_LABEL, layout, stepStatus } from "./logic";
import type { PlanTask } from "./types";

const PHASE_STRIPE: Record<string, string> = {
  research: "border-l-[var(--hm-info)]",
  design: "border-l-[var(--hm-manila)]",
  implement: "border-l-[var(--hm-accent)]",
  test: "border-l-[var(--hm-warning)]",
  document: "border-l-[var(--hm-spine)]",
  review: "border-l-[var(--hm-success)]",
};

interface StepData extends Record<string, unknown> {
  task: PlanTask;
  state?: string;
  critical: boolean;
  selected: boolean;
  editing: boolean;
}

function StepNode({ data }: NodeProps<Node<StepData>>) {
  const { task, state, critical, selected, editing } = data;
  const status = stepStatus(state);
  return (
    <div
      className={cx(
        "flex h-full w-full flex-col justify-between rounded-[5px] border border-l-4 bg-surface px-2.5 py-1.5 text-left shadow-sm",
        PHASE_STRIPE[task.phase] ?? "border-l-[var(--hm-line-strong)]",
        critical ? "border-y-[var(--hm-accent)] border-r-[var(--hm-accent)]" : "border-y-line border-r-line",
        selected && "ring-2 ring-[var(--hm-focus)]",
      )}
      style={{ width: NODE_W, height: NODE_H }}
    >
      <Handle type="target" position={Position.Left} isConnectable={editing} className={cx(!editing && "!opacity-0")} />
      <p className="line-clamp-2 text-xs leading-snug font-medium text-fg" title={task.title}>
        <span className="mr-1 font-mono text-2xs text-muted">{task.id}</span>
        {task.title}
      </p>
      <div className="flex items-center justify-between gap-1 text-2xs text-muted">
        <span className="truncate">
          {roleOf(task.agent_capability).name} · {PHASE_LABEL[task.phase]}
          {task.est_effort != null ? ` · ${task.est_effort} h` : ""}
        </span>
        <Status tone={status.tone} label={status.label} live={status.tone === "progress"} />
      </div>
      <Handle type="source" position={Position.Right} isConnectable={editing} className={cx(!editing && "!opacity-0")} />
    </div>
  );
}

const NODE_TYPES = { step: StepNode };
const MIN_READABLE_ZOOM = 0.55;

/** Once the pane has a size: fit the whole plan when it stays readable, else start at its first steps (pan for more). */
function InitialView({ width, height }: { width: number; height: number }) {
  const paneW = useStore((st) => st.width);
  const paneH = useStore((st) => st.height);
  const rf = useReactFlow();
  const done = useRef(false);
  useEffect(() => {
    if (done.current || paneW === 0 || paneH === 0 || width === 0) return;
    done.current = true;
    const pad = 24;
    const zoom = Math.min(1, Math.max(MIN_READABLE_ZOOM, Math.min((paneW - 2 * pad) / width, (paneH - 2 * pad) / height)));
    const x = width * zoom <= paneW - 2 * pad ? (paneW - width * zoom) / 2 : pad;
    const y = Math.max(pad, (paneH - height * zoom) / 2);
    void rf.setViewport({ x, y, zoom });
  }, [paneW, paneH, width, height, rf]);
  return null;
}

export function PlanGraph({
  tasks,
  states,
  critical,
  selectedId,
  editing,
  colorMode,
  onSelect,
  onConnect,
  onRemoveEdge,
}: {
  tasks: readonly PlanTask[];
  states: Record<string, string>;
  critical: ReadonlySet<string>;
  selectedId: string | null;
  editing: boolean;
  colorMode: "light" | "dark" | "system";
  onSelect: (id: string | null) => void;
  onConnect: (before: string, after: string) => void;
  onRemoveEdge: (before: string, after: string) => void;
}) {
  const placed = useMemo(() => layout(tasks), [tasks]);
  const extent = useMemo(() => ({
    width: Math.max(0, ...placed.map((p) => p.x + NODE_W)),
    height: Math.max(0, ...placed.map((p) => p.y + NODE_H)),
  }), [placed]);
  const nodes: Node<StepData>[] = useMemo(() => {
    const at = new Map(placed.map((p) => [p.id, p]));
    return tasks.map((t) => ({
      id: t.id,
      type: "step",
      position: { x: at.get(t.id)?.x ?? 0, y: at.get(t.id)?.y ?? 0 },
      data: { task: t, state: states[t.id], critical: critical.has(t.id), selected: t.id === selectedId, editing },
      draggable: false,
      ariaLabel: `${t.id}: ${t.title}`,
    }));
  }, [tasks, placed, states, critical, selectedId, editing]);
  const edges: Edge[] = useMemo(
    () =>
      tasks.flatMap((t) =>
        t.depends_on.map((d) => {
          const hot = critical.has(d) && critical.has(t.id);
          const running = stepStatus(states[t.id]).tone === "progress";
          return {
            id: `${d}->${t.id}`,
            source: d,
            target: t.id,
            animated: running,
            markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
            style: { stroke: hot ? "var(--hm-accent)" : "var(--hm-line-strong)", strokeWidth: hot ? 2 : 1.25 },
            ariaLabel: `${t.id} waits for ${d}`,
            interactionWidth: editing ? 18 : 6,
          } satisfies Edge;
        }),
      ),
    [tasks, critical, states, editing],
  );

  return (
    <div className="h-[60vh] min-h-80 w-full overflow-hidden rounded-[5px] border border-line bg-surface-2" data-testid="plan-graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        colorMode={colorMode}
        minZoom={0.2}
        nodesConnectable={editing}
        nodesDraggable={false}
        elementsSelectable
        onNodeClick={(_, n) => onSelect(n.id)}
        onPaneClick={() => onSelect(null)}
        onConnect={(c: Connection) => c.source && c.target && onConnect(c.source, c.target)}
        onEdgeClick={(_, e) => editing && onRemoveEdge(e.source, e.target)}
      >
        <InitialView width={extent.width} height={extent.height} />
        <Background gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
