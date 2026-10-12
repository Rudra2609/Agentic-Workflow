"use client";

import { AgentStateChip } from "@/components/StateChip";
import { EmptyState, ErrorState, LoadingState, Mono, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import type { FeaturePageProps } from "@/lib/features";
import { useApiQuery } from "@/lib/useApiQuery";

/** Example stand-alone feature page (sidebar entry "Echo", served at /features/echo). */
export function EchoPage({ route }: FeaturePageProps) {
  const agents = useApiQuery("echo-agents", (signal) => api.listAgents(signal), { intervalMs: 10_000 });
  const echoAgents = (agents.data ?? []).filter((a) => a.capabilities.includes("echo"));
  return (
    <>
      <PageHeader
        title="Echo"
        subtitle={
          <>
            Example feature page served at <Mono>/features/{route}</Mono>, registered only by{" "}
            <Mono>src/features/echo/index.ts</Mono>.
          </>
        }
      />
      <Section title="Agents serving echo" description="The echo agent copies a step's objective into its result. Handy for a live smoke test.">
        {agents.loading ? (
          <LoadingState />
        ) : agents.error ? (
          <ErrorState error={agents.error} onRetry={agents.reload} />
        ) : echoAgents.length === 0 ? (
          <div className="hm-tray">
            <EmptyState title="No agent serves echo right now" />
          </div>
        ) : (
          <ul className="hm-tray space-y-3 p-3 sm:p-4">
            {echoAgents.map((a) => (
              <li key={a.agent_id} className="hm-slip flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[3px] px-5 py-3.5">
                <Mono className="min-w-0 flex-1 truncate text-fg">{a.agent_id}</Mono>
                {a.state !== "OFFLINE" && a.state !== "FAILED" && (
                  <span className="text-xs text-muted tabular-nums">
                    {a.available_slots} of {a.max_slots} slot{a.max_slots === 1 ? "" : "s"} free
                  </span>
                )}
                <AgentStateChip state={a.state} />
                {a.is_stub && <span className="hm-stamp text-warning">Placeholder</span>}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}
