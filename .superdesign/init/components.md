# Shared UI components

Detected: Next.js 16 (App Router, Turbopack), React 19, TypeScript, Tailwind CSS v4 (CSS-first @theme tokens, no tailwind.config), custom component library (no shadcn/MUI). Fonts via next/font/google: Bricolage Grotesque (display), Hanken Grotesk (body), JetBrains Mono (ids). Theme: class `dark` on <html>; tokens in src/app/globals.css.

Primitives live in `frontend/src/components/ui.tsx` (Button keycaps, Section, Card, PageHeader, Field, Dialog, Status, Table, EmptyState, ErrorState, JsonBlock).

### `frontend/src/components/ui.tsx`

```tsx
/**
 * HMAP UI primitives, built on the semantic tokens in globals.css (bg-surface, text-muted, border-line, …).
 * Dependency-free. Feature panels (src/features/*) may use any of these.
 */
"use client";

import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { isApiError } from "@/lib/api";
import { BACKEND_START_HINT } from "@/lib/config";
import type { Tone } from "@/lib/plain";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

/** Focus styling is global (globals.css :focus-visible); kept for components that add it explicitly. */
export const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export const inputClass = cx(
  "block w-full rounded-lg border border-line-strong bg-surface px-3 py-2.5 text-sm text-fg shadow-[inset_0_1px_2px_rgb(var(--hm-shadow)/0.08)]",
  "placeholder:text-muted disabled:cursor-not-allowed disabled:opacity-60",
  "aria-[invalid=true]:border-danger",
);

export const textareaClass = cx(inputClass, "min-h-24 resize-y leading-relaxed");

type ButtonVariant = "primary" | "secondary" | "danger" | "success" | "ghost" | "quiet-danger";

const buttonVariants: Record<ButtonVariant, string> = {
  // keycaps: a raised edge that presses down (globals.css .hm-key)
  primary: "hm-key hm-key-accent bg-accent font-semibold text-on-accent hover:bg-accent-hover",
  secondary: "hm-key border border-line-strong bg-surface text-fg hover:bg-surface-2",
  danger: "hm-key hm-key-danger bg-danger font-semibold text-white hover:brightness-105 dark:text-canvas",
  success: "hm-key bg-success font-semibold text-white dark:text-canvas",
  // flat: secondary actions that should not compete
  ghost: "text-fg-2 hover:bg-hover hover:text-fg",
  "quiet-danger": "text-danger hover:bg-danger-soft",
};

export function Button({
  variant = "secondary",
  size = "md",
  busy = false,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: "sm" | "md"; busy?: boolean }) {
  return (
    <button
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium whitespace-nowrap",
        "disabled:cursor-not-allowed disabled:opacity-55",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-10 px-4 text-sm",
        buttonVariants[variant],
        className,
      )}
      {...rest}
    >
      {busy && <Spinner className="size-3.5" />}
      {children}
    </button>
  );
}

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span role={label ? "status" : undefined} className="inline-flex items-center gap-2">
      <svg className={cx("animate-spin", className ?? "size-4")} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
        <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </svg>
      {label && <span className="text-sm text-muted">{label}</span>}
    </span>
  );
}

/** A titled region separated by spacing and a hairline — the default grouping (not a card). */
export function Section({
  title,
  description,
  actions,
  children,
  className,
  id,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  const auto = useId();
  const headingId = `${id ?? auto}-title`;
  return (
    <section id={id} aria-labelledby={title ? headingId : undefined} className={cx("min-w-0", className)}>
      {(title || actions) && (
        <header className="mb-3 flex flex-wrap items-end justify-between gap-x-4 gap-y-2 border-b border-line pb-2">
          <div className="min-w-0">
            {title && (
              <h2 id={headingId} className="text-sm font-semibold tracking-tight text-fg">
                {title}
              </h2>
            )}
            {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/** Kept for feature panels: a quiet framed surface (use sparingly). */
export function Card({
  title,
  actions,
  children,
  className,
  bodyClassName,
  id,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  id?: string;
}) {
  return (
    <section id={id} aria-labelledby={title && id ? `${id}-title` : undefined} className={cx("rounded-lg border border-line bg-surface", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          {title && (
            <h2 id={id ? `${id}-title` : undefined} className="text-sm font-semibold text-fg">
              {title}
            </h2>
          )}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-xs text-muted">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-fg sm:text-[1.75rem] sm:leading-tight">{title}</h1>
        {subtitle && <div className="mt-1 max-w-2xl text-sm text-fg-2">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center py-12 text-muted">
      <Spinner label={label} />
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="px-4 py-10 text-center">
      <p className="text-sm font-medium text-fg">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-md text-sm text-muted">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/** Explains failures in plain words; technical details (and the start command) are behind a disclosure. */
export function ErrorState({ error, onRetry, title }: { error: unknown; onRetry?: () => void; title?: string }) {
  const network = isApiError(error) && error.kind === "network";
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="border-l-2 border-danger bg-danger-soft px-4 py-3 text-sm text-fg">
      <p className="font-medium">{title ?? (network ? "Can't reach the HMAP server" : "Something went wrong")}</p>
      <p className="mt-1 text-fg-2">
        {network ? "The server isn't responding. It may be starting up or stopped." : message}
      </p>
      {network && (
        <details className="mt-2 text-xs text-muted">
          <summary className="cursor-pointer">Technical details</summary>
          <p className="mt-1 break-words">{message.split(" Start it with:")[0]}</p>
          <p className="mt-1">Start the backend, then retry:</p>
          <pre className="mt-1 overflow-x-auto rounded bg-surface-2 px-2 py-1.5 font-mono">{BACKEND_START_HINT}</pre>
        </details>
      )}
      {onRetry && (
        <Button size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function InlineError({ error, id }: { error: unknown; id?: string }) {
  if (!error) return null;
  return (
    <p id={id} role="alert" className="text-sm text-danger">
      {error instanceof Error ? error.message : String(error)}
    </p>
  );
}

export function Badge({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center rounded px-1.5 py-0.5 text-2xs font-medium whitespace-nowrap",
        className || "bg-surface-2 text-fg-2",
      )}
    >
      {children}
    </span>
  );
}

const TONE_TEXT: Record<Tone, string> = {
  neutral: "text-fg-2",
  progress: "text-accent-ink",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  muted: "text-muted",
};
const TONE_DOT: Record<Tone, string> = {
  neutral: "border border-line-strong",
  progress: "bg-accent",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  muted: "bg-disabled",
};

/** Status as a dot + words (never colour alone). `live` adds a pulse only for real, reported activity. */
export function Status({ tone, label, live = false, title }: { tone: Tone; label: string; live?: boolean; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1.5 text-xs font-medium whitespace-nowrap", TONE_TEXT[tone])}>
      <span aria-hidden="true" className={cx("size-2 shrink-0 rounded-full", TONE_DOT[tone], live && "animate-pulse")} />
      {label}
    </span>
  );
}

export function Mono({ children, title, className }: { children: ReactNode; title?: string; className?: string }) {
  return (
    <code title={title} className={cx("font-mono text-xs text-fg-2", className)}>
      {children}
    </code>
  );
}

export function JsonBlock({ value, summary = "Show raw data", open }: { value: unknown; summary?: string; open?: boolean }) {
  return (
    <details open={open} className="group">
      <summary className="cursor-pointer select-none text-xs font-medium text-accent-ink hover:underline">{summary}</summary>
      <pre className="mt-2 max-h-80 overflow-auto rounded-md bg-surface-2 p-2.5 font-mono text-xs text-fg-2">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

export function Table({ children, label, minWidth = "40rem" }: { children: ReactNode; label: string; minWidth?: string }) {
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} style={{ minWidth }} className="w-full border-collapse text-left text-sm">
        {children}
      </table>
    </div>
  );
}

export const th = "border-b border-line-strong px-3 py-2 text-xs font-medium text-muted";
export const td = "border-b border-line/70 px-3 py-2.5 align-top";

/** Label + control + hint/error, wired for screen readers (aria-describedby / aria-invalid on the control). */
export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
  trailing,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  children: (ids: { describedBy: string | undefined; invalid: boolean }) => ReactNode;
  htmlFor: string;
  trailing?: ReactNode;
}) {
  const hintId = hint ? `${htmlFor}-hint` : undefined;
  const errorId = error ? `${htmlFor}-error` : undefined;
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <label htmlFor={htmlFor} className="text-sm font-medium text-fg">
          {label}
        </label>
        {trailing}
      </div>
      {children({ describedBy: [errorId, hintId].filter(Boolean).join(" ") || undefined, invalid: Boolean(error) })}
      {error ? (
        <p id={errorId} className="mt-1 text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="mt-1 text-xs text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/** Accessible modal on the native <dialog> (focus trap, Esc to close, focus returns to the opener). */
export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      if (typeof d.showModal === "function") d.showModal();
      else d.setAttribute("open", "");
    } else if (!open && d.open) {
      if (typeof d.close === "function") d.close();
      else d.removeAttribute("open");
    }
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className="hm-float m-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl border border-line bg-surface p-0 text-fg"
    >
      <div className="px-5 pt-5 pb-4">
        <h2 id={titleId} className="text-lg font-semibold tracking-tight">
          {title}
        </h2>
        <div className="mt-2 text-sm text-fg-2">{children}</div>
      </div>
      {footer && <div className="flex flex-wrap justify-end gap-2 px-5 pt-1 pb-5">{footer}</div>}
    </dialog>
  );
}

```

### `frontend/src/components/StateChip.tsx`

```tsx
/** Colour-coded state chips for tasks, projects, executions and agents. */
import { humanize } from "@/lib/format";
import type { AgentState, ExecutionStatus, ProjectState, TaskState } from "@/lib/types";

import { cx } from "./ui";

export type Tone = "neutral" | "info" | "progress" | "success" | "warning" | "danger" | "muted";

export const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-fg-2",
  info: "bg-info-soft text-info",
  progress: "bg-accent-soft text-accent-ink",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  muted: "bg-surface-2 text-muted",
};

const DOT_CLASSES: Record<Tone, string> = {
  neutral: "bg-fg-2",
  info: "bg-info",
  progress: "bg-accent",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  muted: "bg-disabled",
};

export const TASK_STATE_TONES: Record<TaskState, Tone> = {
  CREATED: "neutral",
  READY: "info",
  ASSIGNED: "info",
  ACCEPTED: "progress",
  RUNNING: "progress",
  RESULT_SUBMITTED: "progress",
  REVIEWING: "progress",
  COMPLETED: "success",
  BLOCKED: "warning",
  CANCELLED: "muted",
  RETRY_SCHEDULED: "warning",
  DEAD_LETTERED: "danger",
  FAILED: "danger",
  NEEDS_REVISION: "warning",
};

export const PROJECT_STATE_TONES: Record<ProjectState, Tone> = {
  CREATED: "neutral",
  INGESTING: "progress",
  PLANNING: "progress",
  AWAITING_APPROVAL: "warning",
  EXECUTING: "progress",
  REVIEWING: "progress",
  COMPLETED: "success",
  FAILED: "danger",
  CANCELLED: "muted",
};

export const EXECUTION_STATUS_TONES: Record<ExecutionStatus, Tone> = {
  PENDING: "info",
  ACTIVE: "progress",
  SUCCEEDED: "success",
  FAILED: "danger",
  TIMED_OUT: "warning",
  SUPERSEDED: "muted",
  CANCELLED: "muted",
  DEAD_LETTERED: "danger",
};

export const AGENT_STATE_TONES: Record<AgentState, Tone> = {
  STARTING: "info",
  REGISTERING: "info",
  AVAILABLE: "success",
  BUSY: "progress",
  DRAINING: "warning",
  OFFLINE: "muted",
  RECOVERING: "warning",
  FAILED: "danger",
};

const ACTIVE_STATES = new Set(["RUNNING", "ACTIVE", "BUSY", "INGESTING", "PLANNING", "EXECUTING", "REVIEWING"]);

function toneOf<S extends string>(map: Record<S, Tone>, state: string): Tone {
  return (map as Record<string, Tone>)[state] ?? "neutral";
}

export function StateChip({ state, tone, kind }: { state: string; tone: Tone; kind: string }) {
  return (
    <span
      data-state={state}
      data-tone={tone}
      title={`${kind} state: ${state}`}
      className={cx(
        "inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-2xs font-medium whitespace-nowrap",
        TONE_CLASSES[tone],
      )}
    >
      <span
        aria-hidden="true"
        className={cx("size-1.5 rounded-full", DOT_CLASSES[tone], ACTIVE_STATES.has(state) && "animate-pulse")}
      />
      {humanize(state)}
    </span>
  );
}

export function TaskStateChip({ state }: { state: TaskState | string }) {
  return <StateChip kind="Task" state={state} tone={toneOf(TASK_STATE_TONES, state)} />;
}

export function ProjectStateBadge({ state }: { state: ProjectState | string }) {
  return <StateChip kind="Project" state={state} tone={toneOf(PROJECT_STATE_TONES, state)} />;
}

export function ExecutionStatusChip({ status }: { status: ExecutionStatus | string }) {
  return <StateChip kind="Execution" state={status} tone={toneOf(EXECUTION_STATUS_TONES, status)} />;
}

export function AgentStateChip({ state }: { state: AgentState | string }) {
  return <StateChip kind="Agent" state={state} tone={toneOf(AGENT_STATE_TONES, state)} />;
}

```

### `frontend/src/components/Tabs.tsx`

```tsx
"use client";

import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

import { cx, focusRing } from "./ui";

export interface TabItem {
  id: string;
  label: ReactNode;
  render: () => ReactNode;
}

/** WAI-ARIA tabs (arrow keys / Home / End move between tabs). Only the selected panel is rendered. */
export function Tabs({
  tabs,
  selected,
  onSelect,
  label,
}: {
  tabs: readonly TabItem[];
  selected: string;
  onSelect: (id: string) => void;
  label: string;
}) {
  const base = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const current = tabs.find((t) => t.id === selected) ?? tabs[0];

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const i = tabs.findIndex((t) => t.id === current?.id);
    let next = -1;
    if (e.key === "ArrowRight") next = (i + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    if (next < 0) return;
    e.preventDefault();
    const tab = tabs[next]!;
    onSelect(tab.id);
    refs.current[tab.id]?.focus();
  }

  return (
    <div>
      <div
        role="tablist"
        aria-label={label}
        onKeyDown={onKeyDown}
        className="flex flex-wrap gap-4 border-b border-line"
      >
        {tabs.map((t) => {
          const active = t.id === current?.id;
          return (
            <button
              key={t.id}
              ref={(el) => {
                refs.current[t.id] = el;
              }}
              type="button"
              role="tab"
              id={`${base}-tab-${t.id}`}
              aria-selected={active}
              aria-controls={`${base}-panel-${t.id}`}
              tabIndex={active ? 0 : -1}
              onClick={() => onSelect(t.id)}
              className={cx(
                "-mb-px border-b-2 py-2 text-sm",
                active ? "border-accent font-medium text-fg" : "border-transparent text-muted hover:text-fg",
                focusRing,
              )}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      {current && (
        <div
          role="tabpanel"
          id={`${base}-panel-${current.id}`}
          aria-labelledby={`${base}-tab-${current.id}`}
          tabIndex={0}
          className={cx("pt-4", focusRing)}
        >
          {current.render()}
        </div>
      )}
    </div>
  );
}

```

### `frontend/src/components/Toast.tsx`

```tsx
"use client";

/** Short confirmations ("Saved", "Project archived"). Announced politely to screen readers; auto-dismissed. */
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { cx } from "./ui";

interface ToastItem {
  id: number;
  message: string;
  tone: "neutral" | "danger";
}

const ToastContext = createContext<((message: string, tone?: ToastItem["tone"]) => void) | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);
  const push = useCallback((message: string, tone: ToastItem["tone"] = "neutral") => {
    const id = next.current++;
    setItems((cur) => [...cur.slice(-2), { id, message, tone }]);
    setTimeout(() => setItems((cur) => cur.filter((t) => t.id !== id)), 4000);
  }, []);
  const value = useMemo(() => push, [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div aria-live="polite" role="status" className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4">
        {items.map((t) => (
          <div
            key={t.id}
            className={cx(
              "pointer-events-auto rounded-md px-3.5 py-2 text-sm shadow-lg",
              t.tone === "danger" ? "bg-danger text-white dark:text-canvas" : "bg-fg text-canvas",
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): (message: string, tone?: "neutral" | "danger") => void {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

```

### `frontend/src/components/ErrorBoundary.tsx`

```tsx
"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

/** Isolates a feature panel: if a member's panel throws, only that panel shows an error. */
export class ErrorBoundary extends Component<{ name: string; children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`Feature panel "${this.props.name}" crashed`, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div role="alert" className="border-l-2 border-danger bg-danger-soft p-4 text-sm text-fg">
          <p className="font-semibold">The “{this.props.name}” panel crashed.</p>
          <p className="mt-1 break-words">{this.state.error.message}</p>
          <button
            type="button"
            className="mt-2 rounded border border-line-strong px-2 py-1 text-xs hover:bg-hover"
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

```
