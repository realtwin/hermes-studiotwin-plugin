import { useEffect, useId, useRef, useState } from "react";
import { stageTransition, stageProjection, type StageLifecycleState, type StageEvent } from '../lib/state-machines.ts';
import { modelWebGLPool } from "./webgl-pool.ts";
interface Stage { dispose(): void; snapshot(): string }
/** One residency/outcome state for every pooled viewer. Async work owns its lease. */
export function usePooledStage<S extends Stage>(
  key: string,
  create: (host: HTMLElement) => S,
  load: (s: S, current: () => boolean) => Promise<void | 'audit'>,
  rest: unknown,
  limit = 4,
  onError?: (e: unknown) => void,
  initialPoster?: string,
) {
  const id = useId(), host = useRef<HTMLDivElement>(null), stage = useRef<S | null>(null);
  const [container, setContainer] = useState<HTMLElement | null>(null);
  const [state, setState] = useState<StageLifecycleState>({ phase: 'poster', poster: initialPoster });
  const stateRef = useRef(state);
  const send = (event: StageEvent) => {
    stateRef.current = stageTransition(stateRef.current, event);
    setState(stateRef.current);
  };
  const { live, ready, error } = stageProjection(state);
  useEffect(() => { modelWebGLPool.setLimit(limit) }, [limit]);
  useEffect(() => {
    if (!container || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(rows => {
      if (!rows.some(row => row.isIntersecting)) modelWebGLPool.release(id);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [container, id]);
  useEffect(() => { if (!live) send({ type: 'reset', poster: initialPoster }) }, [key, rest]);
  useEffect(() => {
    if (!live || !host.current) return;
    // A source/backend replacement starts a fresh attempt on the retained lease.
    send({ type: 'reset', poster: initialPoster });
    send({ type: 'start' });
    let alive = true, local: S | null = null;
    const dispose = () => {
      alive = false;
      let poster: string | undefined;
      if (local) {
        try { poster = local.snapshot() } catch {}
        local.dispose();
      }
      if (stage.current === local) stage.current = null;
      send({ type: 'evict', poster });
    };
    modelWebGLPool.acquire(id, dispose);
    const fail = (e: unknown) => {
      if (!alive) return;
      send({ type: 'error' });
      modelWebGLPool.release(id);
      onError?.(e);
    };
    try {
      local = create(host.current);
      stage.current = local;
      void load(local, () => alive).then(result => {
        if (!alive) return;
        send({ type: result === 'audit' ? 'audit' : 'ready' });
        if (result === 'audit') modelWebGLPool.release(id);
      }).catch(fail);
    } catch (e) { fail(e) }
    return () => modelWebGLPool.release(id);
    // Callbacks intentionally belong to an attempt, not every UI control render.
  }, [live, key, rest, id]);
  return {
    host, stage, setContainer, live, ready, error, poster: state.poster, phase: state.phase,
    start() { send({ type: 'start' }) },
    fail(e: unknown) { send({ type: 'error' }); modelWebGLPool.release(id); onError?.(e) },
    touch() { modelWebGLPool.touch(id) },
  };
}
export const panelStyle = {
  border: "1px solid oklch(from var(--ui-stroke-secondary) l 0 h)", borderRadius: 8,
  color: "oklch(from var(--ui-text) l 0 h)", background: "oklch(from var(--ui-bg-secondary) l 0 h)", overflow: "hidden",
};
export const controlStyle = {
  color: "oklch(from var(--ui-text) l 0 h)", background: "oklch(from var(--ui-bg-secondary) l 0 h)",
};
