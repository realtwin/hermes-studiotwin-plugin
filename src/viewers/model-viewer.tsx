import { inspectorButtonStyle } from '../lib/ui-tokens.ts';
import { useEffect, useRef, useState, type ReactNode } from 'react'
import * as sdk from '@hermes/plugin-sdk'
import { stageShell, glassToolbar, glassStatsPill, controlStrip, styledSelect, posterTile, inspectorToggleStyle as filterPillStyle } from '../lib/ui-tokens'
import type { PluginContext } from '@hermes/plugin-sdk'
const { Button } = sdk
import { createModelStage, type ShadingMode } from './model-stage.ts'
import { fetchModel, type ModelSource } from './model-source.ts'
import type { ModelStats } from './model-data.ts'
import { usePooledStage } from './env-lifecycle.ts'
import { multiviewTransition, type MultiviewState, type MultiviewEvent } from '../lib/state-machines.ts'
import { bindModelScope } from './model-source.ts'
import type { MultiviewCapture } from './model-stage.ts'
import { multiviewFilename, stageMultiview, reskinPrompt } from './multiview-reference.ts'
import { AnimationControls, parseRigAudit, type RigAudit } from './animation-viewer.tsx'
export interface ModelViewerProps {
  rest: PluginContext['rest']
  source: ModelSource
  height?: number | string
  webgl_limit?: number
  auto_rotate?: boolean
  poster?: string
  fallback?: ReactNode
  onError?: (error: unknown) => void
  audit?: RigAudit
  downloads?: { label: string; source: ModelSource }[]
  onDownload?: (source: ModelSource) => Promise<void>
  sessionId?: string | null
  onReskin?: (prompt: string) => void
  onMultiviewCaptured?: (capture: MultiviewCapture, source: ModelSource) => void | Promise<void>
  envSource?: ModelSource
  environments?: { label: string; source: ModelSource }[]
}
export function ModelViewer({
  rest,
  source,
  height = 320,
  webgl_limit = 4,
  auto_rotate = true,
  poster,
  fallback,
  onError,
  audit,
  downloads,
  onDownload,
  sessionId,
  onReskin,
  onMultiviewCaptured,
  envSource,
  environments
}: ModelViewerProps) {

  const [stats, setStats] = useState<ModelStats | null>(null),
    [mode, setMode] = useState<ShadingMode>('textured'),
    [spinOverride, setSpin] = useState<boolean | null>(null),
    [grid, setGrid] = useState(true)
  const spin = spinOverride ?? auto_rotate
  const [loadedAudit, setLoadedAudit] = useState<RigAudit | null>(null)
  const sourceKey = JSON.stringify(source)
  const [views, setViews] = useState<4 | 6>(4), [pass, setPass] = useState<ShadingMode>('clay')
  const [yawOffsetDeg, setYawOffsetDeg] = useState(0)
  const [multiview, setMultiview] = useState<MultiviewState<MultiviewCapture>>({ phase: 'idle' })
  const multiviewRef = useRef(multiview), owner = useRef(0)
  const sendMultiview = (event: MultiviewEvent<MultiviewCapture>) => {
    multiviewRef.current = multiviewTransition(multiviewRef.current, event)
    setMultiview(multiviewRef.current)
  }
  const capture = 'capture' in multiview ? multiview.capture : null
  const sheetPath = multiview.phase === 'staged' ? multiview.sheetPath : ''
  const captureError = 'message' in multiview ? multiview.message : ''
  const capturing = multiview.phase === 'capturing' || multiview.phase === 'staging'
  const v = usePooledStage(sourceKey, h => {
    const local = createModelStage(h)
    local.setGrid(grid); local.setAutoRotate(spin)
    return local
  }, async (local, current) => {
    setStats(null); setLoadedAudit(null)
    const f = await fetchModel(rest, source)
    if (!current()) return
    if ((source.name || f.name).toLowerCase().endsWith('.json')) {
      const parsedAudit = parseRigAudit(JSON.parse(new TextDecoder().decode(f.buffer)))
      if (parsedAudit) { setLoadedAudit(parsedAudit); return 'audit' }
    }
    const result = await local.load(f.buffer, source.name || f.name)
    if (current()) { local.setShading(mode); setStats(result) }
  }, rest, webgl_limit, onError, poster)
  const { host: canvasHost, stage, setContainer, live, ready, error, poster: thumbnail } = v
  const [environmentChoice, setEnvironmentChoice] = useState<string | null>(null), [showEnvironment, setShowEnvironment] = useState(false)
  const [environmentError, setEnvironmentError] = useState('')
  const chosenEnvironment = environmentChoice === null ? envSource : environmentChoice === '' ? undefined : environments?.[Number(environmentChoice)]?.source
  const envKey = JSON.stringify(chosenEnvironment)
  useEffect(() => {
    owner.current++
    sendMultiview({ type: 'reset' })
    return () => { owner.current++ }
  }, [rest, sourceKey])
  useEffect(() => {
    if (!ready || !stage.current) return
    const local = stage.current, scope = bindModelScope(rest, sdk.host.state)
    let active = true
    setEnvironmentError('')
    // Clear immediately so a superseded image decode cannot install its texture late.
    local.clearEnvironment()
    if (chosenEnvironment) void fetchModel(scope.rest, chosenEnvironment).then(async file => {
      if (active) await local.setEnvironment(file.buffer, chosenEnvironment.name || file.name, showEnvironment)
    }).catch(() => { if (active) setEnvironmentError('Environment could not be loaded. Choose another panorama.') })
    return () => { active = false; local.clearEnvironment() }
  }, [ready, rest, envKey, showEnvironment])
  const captureReference = async () => {
    const local = stage.current
    if (!local || ['capturing', 'staging'].includes(multiviewRef.current.phase)) return
    const scope = bindModelScope(rest, sdk.host.state), generation = owner.current
    const current = () => generation === owner.current && scope.current()
    sendMultiview({ type: 'start' })
    try {
      const result = await local.captureMultiview({ views, shading: pass, yawOffsetDeg })
      if (!current()) return
      sendMultiview({ type: 'captured', capture: result })
      const saved = await stageMultiview(scope.rest, source, result, sessionId)
      if (!current()) return
      await onMultiviewCaptured?.(result, source)
      if (current()) sendMultiview({ type: 'staged', sheetPath: saved.path })
    } catch {
      if (current()) sendMultiview({ type: 'error', message: 'Capture or local staging could not be confirmed. The sheet can still be downloaded if available. Nothing was generated in the cloud.' })
    }
  }
  useEffect(() => setLoadedAudit(null), [sourceKey])
  useEffect(() => {
    stage.current?.setShading(mode)
  }, [mode])
  useEffect(() => {
    stage.current?.setGrid(grid)
  }, [grid])
  useEffect(() => {
    stage.current?.setAutoRotate(spin)
  }, [spin])
  if (error && fallback !== undefined) return <section data-stage-state={v.phase}>{fallback}</section>
  if (v.phase === 'audit' && loadedAudit)
    return (
      <section data-stage-state={v.phase} style={{ padding: 12, color: 'oklch(from var(--ui-text) l 0 h)', background: 'oklch(from var(--ui-bg-secondary) l 0 h)' }}>
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
      data-stage-state={v.phase}
      style={stageShell}
      onPointerDown={v.touch}
    >
      <div style={{ position: 'relative', height }}>
        <div ref={canvasHost} style={{ position: 'absolute', inset: 0 }} />
        {!live && (
          <button
            type="button"
            onClick={v.start}
            style={{
              ...posterTile,
              position: 'absolute',
              inset: 0,
              width: '100%',
              cursor: 'pointer'
            }}
          >
            {thumbnail && (
              <img src={thumbnail} alt="Model preview" style={{ width: '100%', height: '80%', objectFit: 'contain' }} />
            )}
            <span style={filterPillStyle(true)}><sdk.Codicon name="play" />{error ? 'Preview failed. Retry 3D' : 'Click to load 3D'}</span>
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
            style={glassToolbar}
          >
            <label style={controlStrip}>
              Shading{' '}
              <select
                aria-label="Shading mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as ShadingMode)}
                style={styledSelect}
              >
                {(['textured', 'wireframe', 'clay', 'normals'] as const).map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </label>
            <Button variant="ghost" size="sm" style={filterPillStyle(spin)} aria-pressed={spin} onClick={() => setSpin(!spin)}>
              Auto-rotate
            </Button>
            <Button variant="ghost" size="sm" style={filterPillStyle(grid)} aria-pressed={grid} onClick={() => setGrid(!grid)}>
              Grid
            </Button>
            <Button variant="ghost" size="sm" style={filterPillStyle(false)} onClick={() => stage.current?.reset()}>
              <sdk.Codicon name="refresh" />
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
                      v.fail(err)
                    })
                  e.target.value = ''
                }}
                style={styledSelect}
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
          <div role="group" aria-label="Multiview" data-multiview-state={multiview.phase} style={{ ...controlStrip, padding: 12, flexWrap: 'wrap' }}>
            <strong>Multiview</strong>
            <select aria-label="Multiview views" style={styledSelect} value={views} disabled={capturing} onChange={e => setViews(Number(e.target.value) as 4 | 6)}>
              <option value="4">4 Views</option><option value="6">6 Views</option>
            </select>
            <select aria-label="Multiview pass" style={styledSelect} value={pass} disabled={capturing} onChange={e => setPass(e.target.value as ShadingMode)}>
              {(['clay', 'normals', 'textured', 'wireframe'] as const).map(p => <option key={p} value={p}>{p[0].toUpperCase() + p.slice(1)}</option>)}
            </select>
            <select aria-label="Multiview yaw offset" style={styledSelect} value={yawOffsetDeg} disabled={capturing} onChange={e => setYawOffsetDeg(Number(e.target.value))}>
              <option value="0">0° (+Z)</option><option value="90">90° (+X)</option><option value="180">180° (-Z)</option><option value="-90">-90° (-X)</option>
            </select>
            <Button variant="outline" style={inspectorButtonStyle} size="sm" aria-label="Capture Multiview" disabled={capturing} onClick={() => void captureReference()}>{multiview.phase === 'capturing' ? 'Capturing views…' : multiview.phase === 'staging' ? 'Staging sheet…' : 'Capture Multiview'}</Button>
            {capturing && <span role="status">{multiview.phase === 'capturing' ? 'Capturing views…' : 'Staging sheet…'}</span>}
            {multiview.phase === 'staged' && <span role="status">Ready for Reskin</span>}
            <Button variant="outline" style={inspectorButtonStyle} size="sm" disabled={!sheetPath || capturing || !onReskin} onClick={() => { if (sheetPath) onReskin?.(reskinPrompt(source, sheetPath)) }}>Reskin 3D in Chat</Button>
          </div>
          {(envSource || environments?.length) && <div style={{ ...controlStrip, padding: 12, flexWrap: 'wrap' }}>
            <label>Environment IBL{' '}<select aria-label="Environment IBL" style={styledSelect} value={environmentChoice ?? (envSource ? 'provided' : '')} onChange={e => setEnvironmentChoice(e.target.value === 'provided' ? null : e.target.value)}>
              <option value="">Studio lighting</option>
              {envSource && <option value="provided">{envSource.name || 'Provided panorama'}</option>}
              {environments?.map((env, i) => <option value={i} key={i}>{env.label}</option>)}
            </select></label>
            <label><input type="checkbox" checked={showEnvironment} onChange={e => setShowEnvironment(e.target.checked)} /> Show environment background</label>
          </div>}
          {environmentError && <p role="alert">{environmentError}</p>}
          {capture && <section aria-label="Multiview Reference Preview" data-multiview-state={multiview.phase} style={{ padding: 12 }}>
            <img src={capture.sheetDataUrl} alt="Multiview Reference Preview" style={{ width: '100%', maxWidth: 440, maxHeight: 280, objectFit: 'contain' }} />
            <div style={{ ...controlStrip, flexWrap: 'wrap' }}>{capture.views.map(v => <span key={v.name} style={glassStatsPill}>{v.label}</span>)}
              <Button variant="outline" style={inspectorButtonStyle} size="sm" onClick={() => {
                const a = document.createElement('a'); a.href = capture.sheetDataUrl; a.download = multiviewFilename(source, capture); a.click()
              }}>Download Sheet</Button>
            </div>
            {sheetPath && <p style={{ overflowWrap: 'anywhere', color: 'oklch(from var(--ui-text-secondary) l 0 h)' }}>Locally staged · Made from this 3D model · {sheetPath}</p>}
          </section>}
          {captureError && <p role="alert" style={{ padding: 12 }}>{captureError}</p>}
          {stats && (
            <div data-model-stats style={{ ...glassStatsPill, margin: 12, lineHeight: 1.8 }}>
              {stats.vertices} vertices · {stats.triangles} triangles · {stats.meshes} meshes · {stats.bones}{' '}
              bones/joints · {stats.clips.length} clips
              {stats.bones > 0 && (
                <div>Rig inspection (local): {stats.bones} joints · {stats.skinnedMeshes} skinned meshes · {stats.clips.length} clips</div>
              )}
            </div>
          )}
          {controller && controller.clips.length > 0 && (
            <AnimationControls controller={controller} invalidate={() => stage.current?.invalidate()} audit={audit} />
          )}
          {audit && !controller?.clips.length && (
            <div>
              Rig audit: {audit.riggable ? 'passed' : 'needs attention'} · {audit.joints} joints
              {audit.warnings.map((w, i) => <div key={i}>{w}</div>)}
            </div>
          )}
        </>
      )}
    </section>
  )
}
