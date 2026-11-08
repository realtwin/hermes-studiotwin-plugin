import { useEffect, useId, useRef, useState } from "react";
import { modelWebGLPool } from "./webgl-pool.ts";
interface Stage {
  dispose(): void;
  snapshot(): string;
}
/** Outcome is independent from residency: eviction must never erase a decoder failure. */
export function usePooledStage<S extends Stage>(
  key: string,
  create: (host: HTMLElement) => S,
  load: (s: S) => Promise<void>,
  rest: unknown,
  limit = 4,
  onError?: (e: unknown) => void,
) {
  const id = useId(),
    host = useRef<HTMLDivElement>(null),
    stage = useRef<S | null>(null);
  const [container, setContainer] = useState<HTMLElement | null>(null),
    [live, setLive] = useState(false),
    [ready, setReady] = useState(false),
    [error, setError] = useState(false),
    [poster, setPoster] = useState<string>();
  useEffect(() => {
    modelWebGLPool.setLimit(limit);
  }, [limit]);
  useEffect(() => {
    if (!container) return;
    const o = new IntersectionObserver((rows) => {
      if (!rows.some((r) => r.isIntersecting)) modelWebGLPool.release(id);
    });
    o.observe(container);
    return () => o.disconnect();
  }, [container, id]);
  useEffect(() => {
    setError(false);
  }, [key, rest]);
  useEffect(() => {
    setReady(false);
    if (!live || !host.current) return;
    let alive = true,
      s: S | null = null;
    const dispose = () => {
      alive = false;
      if (s) {
        try {
          setPoster(s.snapshot());
        } catch {}
        s.dispose();
      }
      if (stage.current === s) stage.current = null;
      setLive(false);
      setReady(false);
    };
    modelWebGLPool.acquire(id, dispose);
    const fail = (e: unknown) => {
      if (alive) {
        modelWebGLPool.release(id);
        setError(true);
        onError?.(e);
      }
    };
    try {
      s = create(host.current);
      stage.current = s;
      void load(s)
        .then(() => {
          if (alive) setReady(true);
        })
        .catch(fail);
    } catch (e) {
      fail(e);
    }
    return () => modelWebGLPool.release(id);
  }, [live, key, rest, id]);
  return {
    host,
    stage,
    setContainer,
    live,
    ready,
    error,
    poster,
    start() {
      setError(false);
      setLive(true);
    },
    touch() {
      modelWebGLPool.touch(id);
    },
  };
}
export const panelStyle = {
  border: "1px solid oklch(from var(--ui-stroke-secondary) l 0 h)",
  borderRadius: 8,
  color: "oklch(from var(--ui-text) l 0 h)",
  background: "oklch(from var(--ui-bg-secondary) l 0 h)",
  overflow: "hidden",
};
export const controlStyle = {
  color: "oklch(from var(--ui-text) l 0 h)",
  background: "oklch(from var(--ui-bg-secondary) l 0 h)",
};
