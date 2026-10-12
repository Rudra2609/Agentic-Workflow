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
