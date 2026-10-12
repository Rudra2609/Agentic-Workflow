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
