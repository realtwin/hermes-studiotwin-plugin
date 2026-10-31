import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import * as sdk from '@hermes/plugin-sdk'
import type { PluginContext } from '@hermes/plugin-sdk'
const { Button } = sdk
import { createModelStage, type ModelStage, type ShadingMode } from './model-stage.ts'
import { fetchModel, type ModelSource } from './model-source.ts'
import type { ModelStats } from './model-data.ts'
import { modelWebGLPool } from './webgl-pool.ts'
import { AnimationControls, type RigAudit } from './animation-viewer.tsx'
export interface ModelViewerProps {
  rest: PluginContext['rest']
  source: ModelSource
  height?: number | string
  webgl_limit?: number
  poster?: string
  fallback?: ReactNode
  onError?: (error: unknown) => void
  audit?: RigAudit
  downloads?: { label: string; source: ModelSource }[]
  onDownload?: (source: ModelSource) => Promise<void>
}
export function ModelViewer({
  rest,
  source,
  height = 320,
  webgl_limit = 4,
  poster,
  fallback,
  onError,
  audit,
  downloads,
  onDownload
}: ModelViewerProps) {
  const id = useId(),
    canvasHost = useRef<HTMLDivElement>(null),
    stage = useRef<ModelStage | null>(null)
  // The fallback/audit branches remove the viewer section. Track the actual
  // element so recovery observes its replacement, not a detached section.
  const [container, setContainer] = useState<HTMLElement | null>(null)
  const [live, setLive] = useState(false),
    [ready, setReady] = useState(false),
    [error, setError] = useState(false),
    [thumbnail, setThumbnail] = useState(poster)
  const [stats, setStats] = useState<ModelStats | null>(null),
    [mode, setMode] = useState<ShadingMode>('textured'),
    [spin, setSpin] = useState(false),
    [grid, setGrid] = useState(true)
  const [loadedAudit, setLoadedAudit] = useState<RigAudit | null>(null)
  const sourceKey = JSON.stringify(source)
  useEffect(() => setLoadedAudit(null), [sourceKey])
  useEffect(() => {
    modelWebGLPool.setLimit(webgl_limit)
  }, [webgl_limit])
  useEffect(() => {
    const el = container
    if (!el || typeof IntersectionObserver === 'undefined') return
    const o = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) modelWebGLPool.release(id)
    })
    o.observe(el)
    return () => o.disconnect()
  }, [id, container])
  // Disposal changes live, not the outcome of the last attempt. Only a new
  // source/backend or an explicit retry should clear a failed preview.
  useEffect(() => setError(false), [rest, sourceKey])
  useEffect(() => {
    setReady(false)
    setStats(null)
    if (!live || !canvasHost.current) return
    let alive = true,
      s: ModelStage | null = null
    const dispose = () => {
      alive = false
      if (s) {
        try {
          setThumbnail(s.snapshot())
        } catch {}
        s.dispose()
      }
      if (stage.current === s) stage.current = null
      setLive(false)
      setReady(false)
    }
    // Reserve BEFORE creating a renderer. Eviction disposes synchronously, so cap is never exceeded.
    modelWebGLPool.acquire(id, dispose)
    try {
      s = createModelStage(canvasHost.current)
      stage.current = s
      s.setGrid(grid)
      s.setAutoRotate(spin)
    } catch (e) {
      modelWebGLPool.release(id)
      setError(true)
      onError?.(e)
      return
    }
    const local = s
    void fetchModel(rest, source)
      .then(async (f) => {
        if (!alive) return
        if ((source.name || f.name).toLowerCase().endsWith('.json')) {
          const doc = JSON.parse(new TextDecoder().decode(f.buffer))
          if (
            typeof doc.riggable === 'boolean' &&
            Number.isInteger(doc.joints) &&
            doc.joints >= 0 &&
            Array.isArray(doc.warnings) &&
            doc.warnings.every((w: unknown) => typeof w === 'string')
          ) {
            modelWebGLPool.release(id)
            setLoadedAudit(doc as RigAudit)
            return
          }
        }
        const stats = await local.load(f.buffer, source.name || f.name)
        if (alive) {
          local.setShading(mode)
          setStats(stats)
          setReady(true)
        }
      })
      .catch((e) => {
        if (alive) {
          modelWebGLPool.release(id)
          setError(true)
          onError?.(e)
        }
      })
    return () => {
      modelWebGLPool.release(id)
    }
  }, [live, rest, sourceKey, id])
  useEffect(() => {
    stage.current?.setShading(mode)
  }, [mode])
  useEffect(() => {
    stage.current?.setGrid(grid)
  }, [grid])
  useEffect(() => {
    stage.current?.setAutoRotate(spin)
  }, [spin])
  if (error && fallback !== undefined) return <>{fallback}</>
  if (loadedAudit)
    return (
      <section style={{ padding: 12, color: 'var(--ui-text)', background: 'var(--ui-bg-secondary)' }}>
        <strong>Rig audit: {loadedAudit.riggable ? 'passed' : 'needs attention'}</strong> · {loadedAudit.joints} joints
        <ul>
          {loadedAudit.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      </section>
    )
  const controller = ready ? stage.current?.animation() : null
  return (
    <section
      ref={setContainer}
      data-studiotwin-model-viewer
      style={{
        border: '1px solid var(--ui-stroke-secondary)',
        borderRadius: 8,
        overflow: 'hidden',
        color: 'var(--ui-text)',
        background: 'var(--ui-bg-secondary)'
      }}
      onPointerDown={() => modelWebGLPool.touch(id)}
    >
      <div style={{ position: 'relative', height }}>
        <div ref={canvasHost} style={{ position: 'absolute', inset: 0 }} />
        {!live && (
          <button
            type="button"
            onClick={() => {
              setError(false)
              setLive(true)
            }}
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              border: 0,
              background: 'var(--ui-bg-secondary)',
              color: 'var(--ui-text-secondary)',
              cursor: 'pointer'
            }}
          >
            {thumbnail && (
              <img src={thumbnail} alt="Model preview" style={{ width: '100%', height: '80%', objectFit: 'contain' }} />
            )}
            <span>{error ? 'Preview failed. Retry 3D' : 'Click to load 3D'}</span>
          </button>
        )}
        {live && !ready && (
          <span role="status" style={{ position: 'absolute', left: 12, top: 12 }}>
            Loading model…
          </span>
        )}
      </div>
      {ready && (
        <>
          <div
            role="toolbar"
            aria-label="Model controls"
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 8,
              padding: 8,
              borderTop: '1px solid var(--ui-stroke-secondary)'
            }}
          >
            <label>
              Shading{' '}
              <select
                aria-label="Shading mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as ShadingMode)}
                style={{ color: 'var(--ui-text)', background: 'var(--ui-bg-secondary)' }}
              >
                {(['textured', 'wireframe', 'clay', 'normals'] as const).map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </label>
            <Button size="sm" aria-pressed={spin} onClick={() => setSpin(!spin)}>
              Auto-rotate
            </Button>
            <Button size="sm" aria-pressed={grid} onClick={() => setGrid(!grid)}>
              Grid
            </Button>
            <Button size="sm" onClick={() => stage.current?.reset()}>
              Reset camera
            </Button>
            {onDownload && (
              <select
                aria-label="Download format"
                defaultValue=""
                onChange={(e) => {
                  const row = downloads?.[Number(e.target.value)]
                  if (row)
                    void onDownload(row.source).catch((err) => {
                      setError(true)
                      onError?.(err)
                    })
                  e.target.value = ''
                }}
                style={{ color: 'var(--ui-text)', background: 'var(--ui-bg-secondary)' }}
              >
                <option value="">Download…</option>
                {downloads?.map((d, i) => (
                  <option key={i} value={i}>
                    {d.label}
                  </option>
                ))}
              </select>
            )}
          </div>
          {stats && (
            <div data-model-stats style={{ padding: 8, fontSize: 12, color: 'var(--ui-text-secondary)' }}>
              {stats.vertices} vertices · {stats.triangles} triangles · {stats.meshes} meshes · {stats.bones}{' '}
              bones/joints · {stats.clips.length} clips
            </div>
          )}
          {controller && controller.clips.length > 0 && (
            <AnimationControls controller={controller} invalidate={() => stage.current?.invalidate()} audit={audit} />
          )}
          {audit && !controller?.clips.length && (
            <div title={audit.warnings.join('\n')}>
              Rig audit: {audit.riggable ? 'passed' : 'needs attention'} · {audit.joints} joints
            </div>
          )}
        </>
      )}
    </section>
  )
}
