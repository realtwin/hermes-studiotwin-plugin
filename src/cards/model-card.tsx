import * as sdk from '@hermes/plugin-sdk'
import { useEffect, useState, type ReactNode } from 'react'
import { ModelViewer } from '../viewers/model-viewer.tsx'
import { bindModelScope, fetchModel, type ModelSource, type ModelScopeState } from '../viewers/model-source.ts'
import { canRender } from '../viewers/model-formats.ts'
import type { RigAudit } from '../viewers/animation-viewer.tsx'
const MODEL_TOOLS = [
  'image-to-3d-mesh',
  'tripo-image-to-3d-mesh',
  'tripo-retopology',
  'blender-auto-rig',
  'tripo-auto-rig',
  'tripo-rig-check',
  'text-to-motion',
  'text-to-motion-kimodo',
  'text-to-motion-edit',
  'text-to-motion-control',
  'motion-stitch-single',
  'environment-map-to-world'
]
export function modelTool(name: string) {
  const clean = name
    .replace(/^mcp__studiotwin__/, '')
    .replace(/^mcp_studiotwin_/, '')
    .replace(/^studiotwin_/, '')
    .replace(/_/g, '-')
  return MODEL_TOOLS.includes(clean)
}
export function nextModelActions(source: ModelSource) {
  const ref = source.asset ? `asset ${JSON.stringify(source.asset)}` : `file ${JSON.stringify(source.path)}`
  return [
    ['Retopologize', 'tripo-retopology'],
    ['Check Rig', 'tripo-rig-check'],
    ['Auto-Rig', 'blender-auto-rig'],
    ['Animate', 'text-to-motion'],
    ['Blender Handoff', 'blender_handoff.py']
  ].map(([label, tool]) => ({
    label,
    message: `StudioTwin ${ref}: ${label} using ${tool}. Read the live schema, check input compatibility${source.path ? ' and ask before uploading this local file' : ''}, estimate the exact inputs and ask me to approve any credits before submitting. ${tool === 'blender_handoff.py' ? 'Use a new factory-startup Blender process and a new output directory; never attach to my open scene.' : ''}`
  }))
}
export interface ModelCardProps {
  ctx: sdk.PluginContext
  source: ModelSource
  sessionId?: string | null
  fallback?: ReactNode
  title?: string
  webgl_limit?: number
  scopeState?: ModelScopeState
  audit?: RigAudit
  downloads?: { label: string; source: ModelSource }[]
}
export function ModelCard({
  ctx,
  source,
  sessionId,
  fallback,
  title,
  webgl_limit,
  scopeState = sdk.host.state,
  audit,
  downloads
}: ModelCardProps) {
  // Captured for this mounted card. Never silently rebind an old transcript card to a newly selected profile.
  const [scope] = useState(() => bindModelScope(ctx.rest, scopeState))
  const [failed, setFailed] = useState(false),
    [stale, setStale] = useState(!scope.current())
  useEffect(() => scope.watch(() => setStale(true)), [scope])
  const fail = () => setFailed(true)
  if (failed) return <>{fallback ?? <span role="alert">StudioTwin model preview unavailable.</span>}</>
  const send = (text: string) => {
    try {
      scope.assert()
      if (!sessionId || !sdk.host.composer?.submit(sessionId, text))
        sdk.host.notify({ kind: 'warning', message: 'Open the originating chat to continue this workflow.' })
    } catch {
      setStale(true)
    }
  }
  const download = async (s: ModelSource) => {
    const f = await fetchModel(scope.rest, s)
    scope.assert()
    const url = URL.createObjectURL(new Blob([f.buffer]))
    const a = document.createElement('a')
    a.href = url
    a.download = f.name
    a.click()
    // Browser owns the completed download; retain the object URL until a future task to avoid early revocation.
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const rows = downloads?.length
    ? downloads
    : [{ label: source.name || source.path?.split(/[\\/]/).pop() || 'Original format', source }]
  return (
    <article
      data-studiotwin-model-card
      style={{
        maxWidth: 720,
        padding: 8,
        border: '1px solid var(--ui-stroke-secondary)',
        borderRadius: 10,
        color: 'var(--ui-text)',
        margin: '6px 0'
      }}
    >
      <header style={{ display: 'flex', gap: 8, alignItems: 'center', paddingBottom: 8 }}>
        <strong style={{ flex: 1 }}>{title || source.name || 'StudioTwin 3D / Motion'}</strong>
        <sdk.Button size="sm" disabled={stale} onClick={() => void download(source).catch(fail)}>
          Download
        </sdk.Button>
        <sdk.Button
          size="sm"
          disabled={stale}
          onClick={() =>
            send(
              `Save StudioTwin ${JSON.stringify(source)} to my project. Ask me for the destination and do not overwrite existing files.`
            )
          }
        >
          Save to project
        </sdk.Button>
      </header>
      {stale ? (
        <p role="status">Select the originating profile and connection, then reopen this card.</p>
      ) : (
        <ModelViewer
          rest={scope.rest}
          source={source}
          webgl_limit={webgl_limit}
          fallback={fallback}
          onError={fail}
          audit={audit}
          downloads={rows}
          onDownload={download}
        />
      )}
      <details>
        <summary>Next · review and approve in chat</summary>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, paddingTop: 8 }}>
          {nextModelActions(source).map((a) => (
            <sdk.Button key={a.label} size="sm" disabled={stale} onClick={() => send(a.message)}>
              {a.label}
            </sdk.Button>
          ))}
        </div>
      </details>
    </article>
  )
}
/** V07 calls this registration helper; no package-wide plugin entrypoint is owned by V02. */
export function registerModelCards(ctx: sdk.PluginContext, options: { webgl_limit?: number } = {}) {
  const disposers: (() => void)[] = []
  if (typeof sdk.TOOL_MEDIA_RENDERER_AREA === 'string')
    disposers.push(
      ctx.register({
        id: 'studiotwin-model-media',
        area: sdk.TOOL_MEDIA_RENDERER_AREA,
        data: {
          tools: ['mcp__studiotwin__*'],
          render: (props: sdk.ToolMediaRendererProps) => {
            if (
              !modelTool(props.toolName) ||
              !(canRender(props.file.name) || props.file.name.toLowerCase().endsWith('.json'))
            )
              return props.fallback
            return (
              <ModelCard
                ctx={ctx}
                source={{ path: props.file.path, name: props.file.name }}
                sessionId={props.sessionId}
                fallback={props.fallback}
                {...options}
              />
            )
          }
        }
      })
    )
  disposers.push(
    ctx.register({
      id: 'studiotwin-model-directive',
      area: sdk.TRANSCRIPT_DIRECTIVE_AREA,
      data: {
        name: 'studiotwin-model',
        render: (props: sdk.TranscriptDirectiveProps) => {
          const { path, asset, name, title } = props.attrs
          if (props.streaming || Boolean(path) === Boolean(asset))
            return (
              <span style={{ color: 'var(--ui-text-secondary)' }}>
                StudioTwin: waiting for one model path or asset UUID.
              </span>
            )
          return (
            <ModelCard
              ctx={ctx}
              source={{ ...(path ? { path } : { asset }), name }}
              title={title}
              sessionId={props.sessionId}
              {...options}
            />
          )
        }
      }
    })
  )
  return () => disposers.forEach((d) => d())
}
