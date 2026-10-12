"use client";

/**
 * "Your AI team": every capability the platform knows, as a role, with who serves it (a real agent, a placeholder,
 * or nobody). Developer mode adds the live registry (ids, heartbeats, leases, slots) and the routing table.
 * Nothing is presented as working AI unless the registry says a non-stub agent serves it.
 */
import { useState } from "react";

import { useGlobalEvents } from "@/components/EventStreamProvider";
import { AgentStateChip } from "@/components/StateChip";
import { EmptyState, ErrorState, JsonBlock, LoadingState, Mono, PageHeader, Section, Status, Table, cx, td, th } from "@/components/ui";
import { api } from "@/lib/api";
import { ageMs, formatDateTime, formatDuration } from "@/lib/format";
import { roleOf } from "@/lib/plain";
import { usePreferences } from "@/lib/preferences";
import type { Agent, CapabilityRow } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";
import { useEventTrigger } from "@/lib/useEventStream";
import { useNow } from "@/lib/useNow";

const STALE_HEARTBEAT_MS = 30_000;

function online(a: Agent, now: number): boolean {
  return a.state !== "OFFLINE" && a.state !== "FAILED" && ageMs(a.last_heartbeat, now) < STALE_HEARTBEAT_MS;
}

/** Each role is a slip filed in the team tray; placeholders carry a stamp, not just a colour. */
function Roles({ caps, agents, now }: { caps: readonly CapabilityRow[]; agents: readonly Agent[]; now: number }) {
  return (
    <ul className="hm-tray grid gap-4 p-3 sm:grid-cols-2 sm:p-4">
      {caps.map((c) => {
        const role = roleOf(c.capability);
        const serving = agents.filter((a) => a.capabilities.includes(c.capability));
        const up = serving.filter((a) => online(a, now)).length;
        return (
          <li key={c.capability} className="hm-slip flex flex-col rounded-[3px]">
            <div className="flex-1 px-5 pt-4 pb-3">
              <div className="flex items-start justify-between gap-3">
                <h3 className="font-semibold text-fg">{role.name}</h3>
                {c.status === "stub" && <span className="hm-stamp mt-0.5 text-warning">Placeholder</span>}
                {c.status === "missing" && <span className="hm-stamp mt-0.5 text-danger">Not installed</span>}
              </div>
              <p className="mt-1 text-sm text-fg-2">{role.does}</p>
            </div>
            <div className="border-t border-dotted border-line-strong px-5 py-2.5">
              {serving.length === 0 ? (
                <Status tone="danger" label="Nobody available" />
              ) : (
                <Status tone={up ? "success" : "warning"} label={up ? `Online${serving.length > 1 ? `, ${up} of ${serving.length} workers` : ""}` : "Offline"} />
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function Registry({ agents, now, onSelect, selected }: { agents: readonly Agent[]; now: number; onSelect: (id: string) => void; selected: string | null }) {
  return (
    <Table label="Registered agents" minWidth="52rem">
      <thead>
        <tr>
          <th scope="col" className={th}>Agent</th>
          <th scope="col" className={th}>State</th>
          <th scope="col" className={th}>Capabilities</th>
          <th scope="col" className={th}>Slots</th>
          <th scope="col" className={th}>Heartbeat</th>
          <th scope="col" className={th}>Lease until</th>
        </tr>
      </thead>
      <tbody>
        {agents.map((a) => {
          const age = ageMs(a.last_heartbeat, now);
          const stale = !Number.isFinite(age) || age > STALE_HEARTBEAT_MS;
          return (
            <tr key={a.agent_id} className={cx("hover:bg-hover", selected === a.agent_id && "bg-selected")}>
              <td className={td}>
                <button type="button" onClick={() => onSelect(a.agent_id)} className="text-left">
                  <Mono className="text-fg hover:text-accent-ink">{a.agent_id}</Mono>
                </button>
                <p className="mt-0.5 text-2xs text-muted">
                  Plug-in {a.plugin ?? "none"}, protocol {a.protocol_version}
                  {a.is_stub && ", placeholder"}
                </p>
              </td>
              <td className={td}><AgentStateChip state={a.state} /></td>
              <td className={td}><Mono>{a.capabilities.join(", ")}</Mono></td>
              <td className={cx(td, "font-mono text-xs tabular-nums")}>{a.available_slots}/{a.max_slots}</td>
              <td className={cx(td, "text-xs tabular-nums", stale ? "text-warning" : "text-fg-2")} title={formatDateTime(a.last_heartbeat)}>
                {formatDuration(age)} ago{stale ? " (stale)" : ""}
              </td>
              <td className={cx(td, "font-mono text-2xs text-muted")}>{formatDateTime(a.lease_until)}</td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function Routing({ caps }: { caps: readonly CapabilityRow[] }) {
  return (
    <ol className="space-y-1.5 font-mono text-xs">
      {caps.map((c) => (
        <li key={c.capability} className="flex flex-wrap items-center gap-2">
          <span className="w-36 shrink-0 text-fg">{c.capability}</span>
          <span aria-hidden="true" className="text-muted">→</span>
          <span className="text-fg-2">plug-in {c.plugin ?? "none"}</span>
          <span aria-hidden="true" className="text-muted">→</span>
          <span className={cx(c.status === "real" ? "text-success" : c.status === "stub" ? "text-warning" : "text-danger")}>
            {c.agent ?? "no agent"} ({c.status}{c.priority !== null ? `, priority ${c.priority}` : ""})
          </span>
        </li>
      ))}
    </ol>
  );
}

export function TeamView() {
  const { developer } = usePreferences();
  const agents = useApiQuery("agents", (s) => api.listAgents(s), { intervalMs: 10_000 });
  const caps = useApiQuery("capabilities", (s) => api.listCapabilities(s), { intervalMs: 60_000 });
  const stream = useGlobalEvents();
  useEventTrigger(stream.events, (e) => e.event_type.startsWith("agent."), agents.reload);
  const now = useNow(5_000);
  const [selected, setSelected] = useState<string | null>(null);

  if (agents.loading || caps.loading) return <LoadingState label="Loading your AI team…" />;
  if (agents.error) return <ErrorState error={agents.error} onRetry={agents.reload} />;
  if (caps.error) return <ErrorState error={caps.error} onRetry={caps.reload} />;
  const list = agents.data ?? [];
  const rows = caps.data ?? [];
  const real = rows.filter((c) => c.status === "real").length;
  const stubs = rows.filter((c) => c.status === "stub").length;
  const agent = list.find((a) => a.agent_id === selected);

  return (
    <>
      <PageHeader
        title="Your AI team"
        subtitle="The workers that carry out each kind of step in a plan. You don't assign them: the plan does."
      />
      {stubs > 0 && (
        <p role="note" className="hm-sticky mb-12 max-w-3xl rounded-[2px] px-5 py-4 text-sm leading-relaxed">
          <span className="font-medium">Test environment.</span>{" "}
          {real === 0
            ? "Every member of your AI team is a placeholder: it shows how work flows through the team but does not do real AI work."
            : `${stubs} of ${rows.length} roles are still placeholders: they show how work flows but return sample results. The other ${real} do real work.`}
        </p>
      )}
      <Section
        title="Roles"
        description={`${
          real === 0 ? `All ${stubs} are placeholders.` : stubs === 0 ? `All ${real} do real work.` : `${real} ${real === 1 ? "does" : "do"} real work, ${stubs} ${stubs === 1 ? "is a placeholder" : "are placeholders"}.`
        } ${list.length} worker${list.length === 1 ? "" : "s"} registered.`}
      >
        {rows.length ? <Roles caps={rows} agents={list} now={now} /> : <EmptyState title="No roles found" />}
      </Section>

      {developer && (
        <div className="mt-10 space-y-10">
          <Section title="Registry" description="Live state of every registered agent instance.">
            {list.length ? <Registry agents={list} now={now} onSelect={setSelected} selected={selected} /> : <EmptyState title="No agents registered" />}
            {agent && (
              <div className="hm-clipped mt-6 rounded-[3px] p-5">
                <div className="mb-2 flex items-center justify-between">
                  <Mono className="text-fg">{agent.agent_id}</Mono>
                  <button type="button" className="text-xs text-muted hover:text-fg" onClick={() => setSelected(null)}>
                    Close
                  </button>
                </div>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
                  <div><dt className="text-muted">Current executions</dt><dd className="font-mono">{agent.current_execution_ids.length || "none"}</dd></div>
                  <div><dt className="text-muted">Last heartbeat</dt><dd>{formatDateTime(agent.last_heartbeat)}</dd></div>
                  <div><dt className="text-muted">Lease until</dt><dd>{formatDateTime(agent.lease_until)}</dd></div>
                </dl>
                <div className="mt-2"><JsonBlock value={agent} summary="Raw registry record" /></div>
              </div>
            )}
          </Section>
          <Section title="Capability routing" description="Which plug-in and agent serve each capability (the highest-priority plug-in wins).">
            <Routing caps={rows} />
          </Section>
        </div>
      )}
      {!developer && (
        <p className="mt-8 text-xs text-muted">Turn on Developer mode in the account menu to see agent IDs, heartbeats and routing.</p>
      )}
    </>
  );
}
