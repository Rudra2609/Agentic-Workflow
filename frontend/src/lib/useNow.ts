"use client";

import { useEffect, useState } from "react";

/** Current time in ms, re-rendering every `intervalMs` (for client-side ages such as heartbeat age). */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
