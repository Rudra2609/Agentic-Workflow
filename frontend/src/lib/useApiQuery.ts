"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface QueryState<T> {
  data: T | undefined;
  error: unknown;
  /** True only until the first response (refetches keep showing the previous data). */
  loading: boolean;
  /** True while any request is in flight. */
  fetching: boolean;
  reload: () => void;
}

/**
 * Minimal data loader: fetch on mount / when `key` changes, optional polling, stale responses ignored,
 * previous data kept during refetches. `fetcher` may change identity freely (the latest one is used).
 */
export function useApiQuery<T>(
  key: string | null,
  fetcher: (signal: AbortSignal) => Promise<T>,
  options: { intervalMs?: number } = {},
): QueryState<T> {
  const { intervalMs } = options;
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [fetching, setFetching] = useState(false);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    let active = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- marks the request start; cheap and intended
    setFetching(true);
    fetcherRef
      .current(controller.signal)
      .then((value) => {
        if (!active) return;
        setData(value);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active || controller.signal.aborted) return;
        setError(err);
      })
      .finally(() => {
        if (!active) return;
        setFetching(false);
        setLoadedKey(key);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [key, tick]);

  useEffect(() => {
    if (key === null || !intervalMs) return;
    const id = setInterval(() => {
      if (typeof document === "undefined" || document.visibilityState !== "hidden") setTick((t) => t + 1);
    }, intervalMs);
    return () => clearInterval(id);
  }, [key, intervalMs]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const loading = key !== null && loadedKey !== key;
  return { data: loading ? undefined : data, error: loading ? null : error, loading, fetching, reload };
}
