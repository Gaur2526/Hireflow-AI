"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/** Load once on mount, expose a `reload` that keeps the previous data visible. */
export function useAsync<T>(
  loader: () => Promise<T>,
  deps: React.DependencyList = [],
): AsyncState<T> & { reload: () => Promise<void>; setData: (value: T) => void } {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    error: null,
    loading: true,
  });
  const mounted = useRef(true);
  // Keep the latest loader in a ref so `run` stays stable across renders
  // without capturing a stale closure. Written in an effect, never in render.
  const loaderRef = useRef(loader);
  useEffect(() => {
    loaderRef.current = loader;
  });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: true }));
    try {
      const data = await loaderRef.current();
      if (mounted.current) setState({ data, error: null, loading: false });
    } catch (error) {
      if (mounted.current) {
        setState((prev) => ({
          ...prev,
          error: error instanceof Error ? error.message : String(error),
          loading: false,
        }));
      }
    }
  }, []);

  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const setData = useCallback((value: T) => {
    setState({ data: value, error: null, loading: false });
  }, []);

  return { ...state, reload: run, setData };
}

/**
 * Re-run `loader` on an interval while `active` is true.
 *
 * Used by the live call dashboard: calls in flight refresh every few seconds,
 * and polling stops on its own once every call reaches a terminal state.
 */
export function usePolling(
  loader: () => Promise<void>,
  { active, intervalMs = 5000 }: { active: boolean; intervalMs?: number },
) {
  const loaderRef = useRef(loader);
  useEffect(() => {
    loaderRef.current = loader;
  });

  useEffect(() => {
    if (!active) return;
    let cancelled = false;

    const id = setInterval(() => {
      if (!cancelled && document.visibilityState === "visible") {
        void loaderRef.current();
      }
    }, intervalMs);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [active, intervalMs]);
}
