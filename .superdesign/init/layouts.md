# Layouts

- `src/app/layout.tsx`: root html, fonts, theme init script, Preferences + Toast providers.
- `src/app/(app)/layout.tsx`: signed-in shell (AuthProvider -> EventStream -> AppShell sidebar).
- `src/app/(auth)/layout.tsx`: sign-in split layout with the 3D HierarchyStack hero.
- `src/components/AppShell.tsx`: sidebar nav (My projects, AI team, Activity, Issues, Tools), system status, user menu, mobile top bar.

### `frontend/src/app/layout.tsx`

```tsx
import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Hanken_Grotesk, JetBrains_Mono } from "next/font/google";
import type { ReactNode } from "react";

import { ToastProvider } from "@/components/Toast";
import { PREFERENCES_INIT_SCRIPT, PreferencesProvider } from "@/lib/preferences";

import "./globals.css";

// Bricolage Grotesque: characterful headings. Hanken Grotesk: calm, readable UI text. JetBrains Mono: real ids only.
const display = Bricolage_Grotesque({ subsets: ["latin"], variable: "--font-display-face", display: "swap" });
const body = Hanken_Grotesk({ subsets: ["latin"], variable: "--font-body", display: "swap" });
const code = JetBrains_Mono({ subsets: ["latin"], variable: "--font-code", display: "swap" });

export const metadata: Metadata = {
  title: { default: "HMAP", template: "%s · HMAP" },
  description: "Describe a goal, review the plan, and let your AI team do the work.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#e8ece5" },
    { media: "(prefers-color-scheme: dark)", color: "#111814" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${display.variable} ${body.variable} ${code.variable}`}>
      <head>
        {/* theme + mode before first paint: no flash of the wrong theme */}
        <script dangerouslySetInnerHTML={{ __html: PREFERENCES_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen font-sans text-sm">
        <PreferencesProvider>
          <ToastProvider>{children}</ToastProvider>
        </PreferencesProvider>
      </body>
    </html>
  );
}

```

### `frontend/src/app/(app)/layout.tsx`

```tsx
import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { EventStreamProvider } from "@/components/EventStreamProvider";
import { LoadingState } from "@/components/ui";
import { AuthProvider } from "@/lib/auth";

/** Every page in this group needs a signed-in user (the API enforces it; this decides what to render). */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AuthProvider fallback={<LoadingState label="Opening your workspace…" />}>
      <EventStreamProvider>
        <AppShell>{children}</AppShell>
      </EventStreamProvider>
    </AuthProvider>
  );
}

```

### `frontend/src/app/(auth)/layout.tsx`

```tsx
import type { ReactNode } from "react";

import { HmapMark } from "@/components/AppShell";
import { AuthBackdrop, HierarchyStack } from "@/components/AuthBackdrop";

/**
 * Sign-in pages. Desktop: the hierarchy stack (the one bold element) with a plain, specific headline; the form on a
 * lifted card. Mobile: the mark and the form only.
 */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="relative isolate min-h-screen overflow-hidden">
      <AuthBackdrop />
      <div className="mx-auto grid min-h-screen max-w-7xl lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <aside className="hidden flex-col px-12 py-10 lg:flex">
          <div className="flex items-center gap-2">
            <HmapMark className="size-8" />
            <span className="font-display text-xl font-semibold tracking-tight">hmap</span>
          </div>
          <div className="my-auto">
            <h1 className="max-w-[15ch] text-[3.25rem] leading-[1.02] font-bold tracking-[-0.03em] text-balance text-fg">
              Your goal goes in at the top.
            </h1>
            <p className="mt-5 max-w-[46ch] text-[1.0625rem] leading-relaxed text-fg-2">
              A manager agent turns it into a plan you can check, then hands each step down to a specialist —
              researcher, developer, tester, writer, reviewer. Follow every step as it happens, and stop it whenever
              you want.
            </p>
            <HierarchyStack />
          </div>
          <p className="text-xs text-muted">IT-314 Group 23. Runs on this computer.</p>
        </aside>

        <main id="main" className="flex flex-col items-center justify-center px-4 py-10 sm:px-8">
          <div className="mb-8 flex items-center gap-2 lg:hidden">
            <HmapMark className="size-8" />
            <span className="font-display text-xl font-semibold tracking-tight">hmap</span>
          </div>
          <div className="hm-float w-full max-w-[25rem] rounded-3xl border border-line bg-surface p-7 sm:p-9">{children}</div>
        </main>
      </div>
    </div>
  );
}

```

### `frontend/src/components/AppShell.tsx`

```tsx
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
    <ul className="space-y-px">
      {items.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cx(
                "relative flex items-center justify-between rounded-md px-2.5 py-1.5 text-sm transition-colors",
                active ? "bg-selected font-medium text-fg" : "text-fg-2 hover:bg-hover hover:text-fg",
              )}
            >
              {active && <span aria-hidden="true" className="absolute top-1.5 bottom-1.5 -left-2 w-0.5 rounded-full bg-accent" />}
              <span>{item.label}</span>
              {item.count ? (
                <span className="rounded bg-surface-2 px-1.5 font-mono text-2xs text-fg-2" title={item.countLabel}>
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
        <p className="mb-1.5 px-2.5 text-xs text-muted">Workspace</p>
        <NavList items={workspace} pathname={pathname} onNavigate={onNavigate} />
      </div>
      {tools.length > 0 && (
        <div>
          <p className="mb-1.5 px-2.5 text-xs text-muted">Tools</p>
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
        className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-hover"
      >
        <span aria-hidden="true" className="grid size-7 shrink-0 place-items-center rounded-full bg-accent-soft text-2xs font-semibold text-accent-ink">
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
          className="hm-float absolute right-0 bottom-full left-0 z-30 mb-2 space-y-3 rounded-xl border border-line bg-surface p-3 md:right-auto md:w-72"
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
      <span className="font-display text-lg font-semibold tracking-tight text-fg">hmap</span>
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
        <aside className="hidden w-60 shrink-0 flex-col gap-6 bg-sidebar px-3 py-4 md:sticky md:top-0 md:flex md:h-screen">
          <Brand />
          <NavGroups pathname={pathname} />
          <div className="mt-auto space-y-3">
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

        <main id="main" className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </WorkspaceProvider>
  );
}

```

### `frontend/src/components/AuthBackdrop.tsx`

```tsx
"use client";

/**
 * The sign-in hero: HMAP's hierarchy as three floating plates in CSS 3D space. Your goal enters on the top plate (you
 * and the Manager), is broken down on the middle plate (Analyst, Planner) and handed to the specialists on the bottom
 * plate. Task blocks fall through the layers; the stack tilts toward the pointer. Decorative (aria-hidden); still under
 * prefers-reduced-motion.
 */
import { useEffect, useRef, type CSSProperties } from "react";

interface Plate {
  z: number;
  title: string;
  seats: string[];
  top?: boolean;
}

const GAP = 118;
const PLATES: Plate[] = [
  { z: 0, title: "Specialists", seats: ["Researcher", "Developer", "Tester", "Writer", "Reviewer"] },
  { z: GAP, title: "Planning", seats: ["Analyst", "Planner"] },
  { z: GAP * 2, title: "Your goal", seats: ["You", "Manager"], top: true },
];

// blocks fall from the top plate, pause on the middle one, land on a specialist
const DROPS = [
  { x: 36, y: 132, delay: "0s" },
  { x: 150, y: 150, delay: "-2s" },
  { x: 236, y: 132, delay: "-4s" },
];

function PlateView({ plate }: { plate: Plate }) {
  return (
    <div className={plate.top ? "hm-plate hm-plate-top" : "hm-plate"} style={{ transform: `translateZ(${plate.z}px)` }}>
      <div className="flex h-full flex-col p-4">
        <p className={plate.top ? "font-display text-[15px] font-semibold text-on-accent" : "font-display text-[15px] font-semibold text-fg"}>
          {plate.title}
        </p>
        <div className="mt-auto flex flex-wrap gap-1.5">
          {plate.seats.map((s) => (
            <span key={s} className="hm-seat px-2 py-1 text-[11px] font-medium text-fg">
              {s}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export function HierarchyStack() {
  const stage = useRef<HTMLDivElement>(null);
  const stack = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = stage.current;
    const target = stack.current;
    if (!el || !target || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const dx = (e.clientX - (r.left + r.width / 2)) / r.width;   // -0.5 … 0.5
      const dy = (e.clientY - (r.top + r.height / 2)) / r.height;
      target.style.setProperty("--hm-tilt-z", `${-38 + dx * 14}deg`);
      target.style.setProperty("--hm-tilt-x", `${58 - dy * 10}deg`);
    };
    const onLeave = () => {
      target.style.removeProperty("--hm-tilt-z");
      target.style.removeProperty("--hm-tilt-x");
    };
    window.addEventListener("pointermove", onMove);
    document.addEventListener("pointerleave", onLeave);
    return () => {
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  return (
    <div ref={stage} aria-hidden="true" className="hm-stage relative mx-auto mt-6 h-[460px] w-full max-w-[540px] select-none">
      <div className="absolute top-[70%] left-1/2 h-[220px] w-[300px] -translate-x-1/2 -translate-y-1/2">
        <div ref={stack} className="hm-stack relative h-full w-full">
          {/* floor shadow */}
          <div className="absolute inset-[-12%] rounded-[40px] bg-[radial-gradient(closest-side,rgb(var(--hm-shadow)/0.28),transparent)] blur-md" style={{ transform: "translateZ(-30px)" }} />
          {PLATES.map((p) => (
            <PlateView key={p.title} plate={p} />
          ))}
          {DROPS.map((d) => (
            <div
              key={d.x}
              className="hm-drop absolute size-5 rounded-[6px] bg-accent shadow-[0_3px_0_var(--hm-accent-edge)]"
              style={{ left: d.x, top: d.y, animationDelay: d.delay, "--from": `${GAP * 2 + 40}px`, "--mid": `${GAP + 14}px`, "--to": "14px" } as CSSProperties}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

/** A quiet paper texture for the whole sign-in page (no glows, no gradients as decoration). */
export function AuthBackdrop() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 -z-10 opacity-60 [background-image:radial-gradient(var(--hm-line-strong)_0.8px,transparent_1px)] [background-size:18px_18px] [mask-image:linear-gradient(to_right,black,transparent_70%)]"
    />
  );
}

```

### `frontend/src/components/EventStreamProvider.tsx`

```tsx
"use client";

import { createContext, useContext, type ReactNode } from "react";

import { useEventStream, type EventStream } from "@/lib/useEventStream";

const EventStreamContext = createContext<EventStream | null>(null);

/** One app-wide, unfiltered live feed (Events page, Agents page, sidebar status). */
export function EventStreamProvider({ children }: { children: ReactNode }) {
  const stream = useEventStream({ cap: 2000 });
  return <EventStreamContext.Provider value={stream}>{children}</EventStreamContext.Provider>;
}

export function useGlobalEvents(): EventStream {
  const ctx = useContext(EventStreamContext);
  if (!ctx) throw new Error("useGlobalEvents must be used inside <EventStreamProvider>");
  return ctx;
}

```
