"use client";

/**
 * Application shell: persistent sidebar (desktop) / top bar + menu (mobile), user menu, quiet system status, and
 * the workspace summary (the signed-in user's projects + dead letters) shared by the sidebar counts and pages.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { StreamStatus } from "@/lib/eventStream";
import { FEATURE_PAGES } from "@/lib/featureRegistry";
import { NEEDS_ATTENTION_STATES } from "@/lib/plain";
import { usePreferences, type Theme } from "@/lib/preferences";
import type { DeadLetter, Project } from "@/lib/types";
import { useApiQuery, type QueryState } from "@/lib/useApiQuery";
import { useEventTrigger } from "@/lib/useEventStream";

import { useGlobalEvents } from "./EventStreamProvider";
import { cx } from "./ui";

// ------------------------------------------------------------------ workspace summary (real counts only)

interface WorkspaceSummary {
  projects: QueryState<Project[]>;
  deadLetters: QueryState<DeadLetter[]>;
  needsAttention: number;
  openIssues: number;
}

const WorkspaceContext = createContext<WorkspaceSummary | null>(null);

export function useWorkspace(): WorkspaceSummary {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside <AppShell>");
  return ctx;
}

function WorkspaceProvider({ children }: { children: ReactNode }) {
  const projects = useApiQuery("workspace:projects", (signal) => api.listProjects(signal), { intervalMs: 30_000 });
  const deadLetters = useApiQuery("workspace:dead-letters", (signal) => api.listDeadLetters(signal), {
    intervalMs: 60_000,
  });
  const stream = useGlobalEvents();
  useEventTrigger(
    stream.events,
    (e) => e.event_type.startsWith("project.") || e.event_type.startsWith("approval.") || e.event_type === "task.dead_lettered",
    () => {
      projects.reload();
      deadLetters.reload();
    },
    400,
  );
  const list = projects.data ?? [];
  const needsAttention = list.filter((p) => NEEDS_ATTENTION_STATES.has(p.state)).length;
  const openIssues = list.filter((p) => p.state === "FAILED").length + (deadLetters.data?.length ?? 0);
  return (
    <WorkspaceContext.Provider value={{ projects, deadLetters, needsAttention, openIssues }}>
      {children}
    </WorkspaceContext.Provider>
  );
}

// ------------------------------------------------------------------ navigation

interface NavItem {
  href: string;
  label: string;
  count?: number;
  countLabel?: string;
}

function useNav(): { workspace: NavItem[]; tools: NavItem[] } {
  const { needsAttention, openIssues } = useWorkspace();
  return {
    workspace: [
      { href: "/", label: "My projects", count: needsAttention, countLabel: `${needsAttention} need your attention` },
      { href: "/team", label: "AI team" },
      { href: "/activity", label: "Activity" },
      { href: "/issues", label: "Issues", count: openIssues, countLabel: `${openIssues} open issues` },
    ],
    tools: FEATURE_PAGES.map((f) => ({ href: `/features/${f.route}`, label: f.title })),
  };
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/" || pathname.startsWith("/projects/");
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavList({ items, pathname, onNavigate }: { items: NavItem[]; pathname: string; onNavigate?: () => void }) {
  return (
    <ul className="space-y-1.5">
      {items.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cx(
                "hm-tab flex items-center justify-between px-3 py-2 text-sm",
                !active && "text-fg-2 hover:text-fg",
              )}
            >
              <span>{item.label}</span>
              {item.count ? (
                <span
                  className={cx(
                    "grid size-5 place-items-center rounded-full text-2xs font-semibold",
                    active ? "bg-on-accent text-accent" : "bg-accent-soft text-accent-ink",
                  )}
                  title={item.countLabel}
                >
                  <span className="sr-only">{item.countLabel}</span>
                  <span aria-hidden="true">{item.count}</span>
                </span>
              ) : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function NavGroups({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  const { workspace, tools } = useNav();
  return (
    <nav aria-label="Main" className="space-y-5">
      <div>
        <p className="mb-2 pl-4 text-xs font-medium text-muted">Workspace</p>
        <NavList items={workspace} pathname={pathname} onNavigate={onNavigate} />
      </div>
      {tools.length > 0 && (
        <div>
          <p className="mb-2 pl-4 text-xs font-medium text-muted">Tools</p>
          <NavList items={tools} pathname={pathname} onNavigate={onNavigate} />
        </div>
      )}
    </nav>
  );
}

// ------------------------------------------------------------------ status + user menu

const STREAM_TEXT: Record<StreamStatus, string> = {
  idle: "Live updates: starting",
  connecting: "Live updates: connecting…",
  open: "Live updates: on",
  reconnecting: "Live updates: reconnecting…",
  closed: "Live updates: off",
};

function SystemStatus() {
  const health = useApiQuery("health", (signal) => api.health(signal), { intervalMs: 15_000 });
  const stream = useGlobalEvents();
  const apiOk = !!health.data && !health.error;
  const streamOk = stream.status === "open";
  const dot = (ok: boolean, pending: boolean) =>
    cx("inline-block size-1.5 shrink-0 rounded-full", ok ? "bg-success" : pending ? "bg-warning" : "bg-danger");
  return (
    <div className="space-y-1 px-2.5 text-2xs text-muted" aria-live="polite">
      <p className="flex items-center gap-2" title={health.data ? `Message bus: ${health.data.bus}` : undefined}>
        <span aria-hidden="true" className={dot(apiOk, health.loading)} />
        {health.loading ? "Server: checking…" : apiOk ? "Server: online" : "Server: unreachable"}
      </p>
      <p className="flex items-center gap-2" title={stream.error ?? undefined}>
        <span aria-hidden="true" className={dot(streamOk, stream.status === "connecting" || stream.status === "idle")} />
        {STREAM_TEXT[stream.status]}
        {stream.status === "reconnecting" && stream.attempt > 1 ? ` (try ${stream.attempt})` : ""}
      </p>
    </div>
  );
}

const THEMES: { id: Theme; label: string }[] = [
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
  { id: "system", label: "System" },
];

export function ThemeChoice() {
  const { theme, setTheme } = usePreferences();
  return (
    <div role="radiogroup" aria-label="Colour theme" className="inline-flex rounded-md border border-line p-0.5">
      {THEMES.map((t) => (
        <button
          key={t.id}
          type="button"
          role="radio"
          aria-checked={theme === t.id}
          onClick={() => setTheme(t.id)}
          className={cx(
            "rounded px-2 py-0.5 text-xs",
            theme === t.id ? "bg-surface-2 font-medium text-fg" : "text-muted hover:text-fg",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function DeveloperSwitch() {
  const { developer, setMode } = usePreferences();
  const id = useId();
  return (
    <label htmlFor={id} className="flex cursor-pointer items-center justify-between gap-3 text-sm">
      <span>
        Developer mode
        <span className="block text-2xs text-muted">Show IDs, raw events and technical details</span>
      </span>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={developer}
        onClick={() => setMode(developer ? "simple" : "developer")}
        className={cx("relative h-5 w-9 shrink-0 rounded-full shadow-[inset_0_1px_3px_rgb(var(--hm-shadow)/0.35)] transition-colors", developer ? "bg-accent" : "bg-line-strong")}
      >
        <span
          aria-hidden="true"
          className={cx("absolute top-0.5 left-0.5 size-4 rounded-full bg-surface shadow transition-transform", developer && "translate-x-4")}
        />
      </button>
    </label>
  );
}

function UserMenu() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const menuId = useId();
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const initials = user.name
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2.5 rounded-md border border-line bg-surface px-2 py-2 text-left shadow-[2px_2px_5px_rgb(var(--hm-shadow)/0.06)] hover:bg-surface-2"
      >
        <span aria-hidden="true" className="grid size-8 shrink-0 place-items-center rounded-md bg-accent text-2xs font-semibold text-on-accent">
          {initials || "?"}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-fg">{user.name}</span>
          <span className="block truncate text-2xs text-muted">{user.email}</span>
        </span>
        <span className="sr-only">Account menu</span>
      </button>
      {open && (
        <div
          id={menuId}
          className="hm-float absolute right-0 bottom-full left-0 z-30 mb-2 space-y-3 rounded-[4px] border border-line bg-surface p-3 md:right-auto md:w-72"
        >
          <div className="space-y-1.5">
            <p className="text-xs text-muted">Appearance</p>
            <ThemeChoice />
          </div>
          <DeveloperSwitch />
          <div className="-mx-3 border-t border-line" />
          <div className="flex flex-col">
            <Link href="/settings" onClick={() => setOpen(false)} className="rounded px-1.5 py-1 text-sm text-fg-2 hover:bg-hover hover:text-fg">
              Settings
            </Link>
            <button type="button" onClick={() => void signOut()} className="rounded px-1.5 py-1 text-left text-sm text-fg-2 hover:bg-hover hover:text-fg">
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** The HMAP mark: three stacked plates — a goal handed down a hierarchy. */
export function HmapMark({ className }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 32 32" className={className}>
      <path d="M16 20.5 4 14.5l12-6 12 6-12 6Z" fill="var(--hm-line-strong)" transform="translate(0 6)" />
      <path d="M16 20.5 4 14.5l12-6 12 6-12 6Z" fill="var(--hm-fg-2)" transform="translate(0 2)" />
      <path d="M16 20.5 4 14.5l12-6 12 6-12 6Z" fill="var(--hm-accent)" transform="translate(0 -2)" />
    </svg>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2 rounded-md px-2 py-1">
      <HmapMark className="size-7" />
      <span className="font-display text-lg tracking-tight text-fg">hmap</span>
    </Link>
  );
}

// ------------------------------------------------------------------ shell

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- close the mobile menu on navigation
    setMenuOpen(false);
  }, [pathname]);

  return (
    <WorkspaceProvider>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:shadow">
        Skip to content
      </a>
      <div className="flex min-h-screen flex-col md:flex-row">
        {/* desktop sidebar */}
        <aside className="hm-spine hidden w-64 shrink-0 flex-col gap-7 py-5 pr-4 pl-3 md:sticky md:top-0 md:flex md:h-screen">
          <div className="pl-5">
            <Brand />
          </div>
          <div className="pl-2">
            <NavGroups pathname={pathname} />
          </div>
          <div className="mt-auto space-y-3 pl-5">
            <SystemStatus />
            <UserMenu />
          </div>
        </aside>

        {/* mobile top bar */}
        <header className="sticky top-0 z-20 flex items-center justify-between bg-sidebar px-3 py-2 md:hidden">
          <Brand />
          <button
            type="button"
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
            onClick={() => setMenuOpen((o) => !o)}
            className="rounded-md px-2.5 py-1.5 text-sm text-fg-2 hover:bg-hover"
          >
            {menuOpen ? "Close" : "Menu"}
          </button>
        </header>
        {menuOpen && (
          <div id="mobile-nav" className="space-y-5 border-b border-line bg-sidebar px-3 pt-2 pb-4 md:hidden">
            <NavGroups pathname={pathname} onNavigate={() => setMenuOpen(false)} />
            <SystemStatus />
            <UserMenu />
          </div>
        )}

        <main id="main" className="min-w-0 flex-1 p-2 sm:p-4 md:py-6 md:pr-6 md:pl-0">
          {/* the working sheet lying on the desk */}
          <div className="hm-sheet min-h-[calc(100vh-3rem)] rounded-[3px] px-4 py-7 sm:px-8 lg:px-14 lg:py-12">
            <div className="mx-auto max-w-6xl">{children}</div>
          </div>
        </main>
      </div>
    </WorkspaceProvider>
  );
}
