import * as sdk from '@hermes/plugin-sdk'
import { cardShell, cardHeader, cardTitle, creditBadgeStyle, filterPillStyle, nextDrawerStyle, nextSummaryStyle, nextActionChipStyle } from '../lib/ui-tokens'
import { studiotwinToolAliases } from './tool-names.ts'
import { useEffect, useState, type ReactNode } from 'react'
import { ImageViewer } from '../viewers/image-viewer.tsx'
import {
  imageActions,
  object,
  submitNext,
  useMediaScope,
  type MediaScope,
  type MediaSource,
  type NextAction,
} from './next-actions.ts'
export interface ImageCardProps {
  ctx: sdk.PluginContext
  source: MediaSource
  before?: MediaSource
  sessionId?: string | null
  fallback?: ReactNode
  title?: string
  provenanceId?: string
  history?: { source: MediaSource; active?: boolean; before?: MediaSource }[]
  scope?: MediaScope
  actions?: NextAction[]
}
export function ImageCard(props: ImageCardProps) {
  const { scope, stale } = useMediaScope(props.ctx, props.scope)
  const [failed, setFailed] = useState(false)
  const [lineage, setLineage] = useState<{ label: string; parents: unknown[] }>({ label: '', parents: [] }),
    [version, setVersion] = useState(-1)
  const source = version >= 0 ? props.history![version].source : props.source
  const before = version >= 0 ? props.history![version].before : props.before
  useEffect(() => {
    let live = true
    const id = source.asset ?? props.provenanceId
    setLineage({ label: '', parents: [] })
    if (id)
      scope
        .rest<{ made_from?: string | null; parents?: unknown[] }>('/provenance?id=' + encodeURIComponent(id))
        .then((row) => {
          if (live)
            setLineage({
              label: typeof row.made_from === 'string' ? row.made_from : '',
              parents: Array.isArray(row.parents) ? row.parents : [],
            })
        })
        .catch(() => undefined)
    return () => {
      live = false
    }
  }, [scope, source.asset, props.provenanceId])
  if (stale || failed)
    return (
      <>{props.fallback ?? <p role="status">Image unavailable. Reopen in the originating profile and connection.</p>}</>
    )
  return (
    <article
      style={{ ...cardShell, maxWidth: 720, color: 'var(--ui-text-primary)' }}
    >
      <header style={cardHeader}>
        {Object.hasOwn(sdk, 'Codicon') && <sdk.Codicon name="file-media" size={16} />}
        <strong style={cardTitle}>{props.title ?? 'StudioTwin Image / Concept'}</strong>{' '}
        <span style={creditBadgeStyle}>Image / Concept</span>
        {(lineage.label || lineage.parents.length > 0) && (
          <span style={creditBadgeStyle} title={JSON.stringify(lineage.parents)}>
            {lineage.label || `Made from · ${lineage.parents.length} sources`}
          </span>
        )}
      </header>
      {props.history && props.history.length > 0 && (
        <nav aria-label="Concept versions">
          {props.history.map((item, i) => (
            <sdk.Button style={filterPillStyle(version === i)} key={i} aria-pressed={version === i} onClick={() => setVersion(i)}>
              Version {i + 1}
              {item.active ? ' · Active asset' : ''}
            </sdk.Button>
          ))}
        </nav>
      )}
      <ImageViewer
        key={JSON.stringify(source)}
        source={source}
        before={before}
        scope={scope}
        fallback={props.fallback}
        title={props.title}
        onError={() => setFailed(true)}
      />
      {props.actions?.length !== 0 && (
        <details style={nextDrawerStyle}>
          <summary style={nextSummaryStyle}>Next · review and approve in chat</summary>
          {(props.actions ?? imageActions(source)).map((a) => (
            <sdk.Button
              key={a.id}
              style={nextActionChipStyle}
              onClick={() => {
                try {
                  submitNext(scope, props.sessionId, a)
                } catch {
                  /* scope watcher disables this card */
                }
              }}
            >
              {a.label} · <span style={creditBadgeStyle}>{a.cost_label ?? (a.cost == null ? 'estimate first' : `${a.cost} cr`)}</span>
            </sdk.Button>
          ))}
        </details>
      )}
    </article>
  )
}
const NAMES = [
  'openai-gpt-image-2-v4-fn',
  'openai-gpt-image-1-v1-fn',
  'concept-lab-img-fn',
  'studiotwin_conceptlab_create_and_generate',
  'studiotwin_conceptlab_generate',
  'studiotwin_conceptlab_edit',
  'studiotwin_conceptlab_get',
  'studiotwin_conceptlab_get_status',
]
export const IMAGE_TOOLS = studiotwinToolAliases(NAMES)
export function conceptImages(value: unknown) {
  const row = object(value),
    concept = object(row.concept ?? row)
  const assets = Array.isArray(concept.assets) ? concept.assets.filter((a: any) => typeof a?.assetId === 'string') : []
  return assets.map((a: any, i: number) => ({
    source: { asset: a.assetId } as MediaSource,
    active: a.isActive === true,
    before: a.operation?.sourceAssetId
      ? { asset: a.operation.sourceAssetId }
      : i > 0
        ? { asset: assets[i - 1].assetId }
        : undefined,
  }))
}
export function registerImageCards(ctx: sdk.PluginContext) {
  if (typeof sdk.TOOL_MEDIA_RENDERER_AREA === 'string')
    ctx.register({
      id: 'studiotwin-image-media',
      area: sdk.TOOL_MEDIA_RENDERER_AREA,
      data: {
        tools: IMAGE_TOOLS,
        render: (p: sdk.ToolMediaRendererProps) => {
          const result = object(p.result)
          if (!IMAGE_TOOLS.includes(p.toolName) || p.file.kind !== 'image' || result.error || result.success === false)
            return p.fallback
          const history = conceptImages(result),
            active = history.find((a: any) => a.active) ?? history.at(-1)
          const parent = p.args.sourceAssetId ?? p.args.referenceAssetId ?? p.args.imageUrl
          const provenanceId = result.assetId ?? result.jobId ?? result.uuid ?? result.conceptId
          const before =
            active?.before ??
            (typeof parent === 'string' ? (/^https?:/.test(parent) ? { url: parent } : { asset: parent }) : undefined)
          return (
            <ImageCard
              key={p.toolCallId + p.file.path}
              ctx={ctx}
              source={active?.source ?? { path: p.file.path }}
              history={history}
              before={before}
              provenanceId={typeof provenanceId === 'string' ? provenanceId : undefined}
              sessionId={p.sessionId}
              fallback={p.fallback}
            />
          )
        },
      },
    })
  ctx.register({
    id: 'studiotwin-image-directive',
    area: sdk.TRANSCRIPT_DIRECTIVE_AREA ?? 'transcript.directives',
    data: {
      name: 'studiotwin-image',
      render: (p: sdk.TranscriptDirectiveProps) => {
        const { path, asset, url, before, title } = p.attrs
        if (p.streaming || [path, asset, url].filter(Boolean).length !== 1) return <p>{p.source}</p>
        return (
          <ImageCard
            key={JSON.stringify(p.attrs)}
            ctx={ctx}
            source={{ path, asset, url }}
            before={before ? (/^https?:/.test(before) ? { url: before } : { asset: before }) : undefined}
            title={title}
            sessionId={p.sessionId}
            fallback={<p>{p.source}</p>}
          />
        )
      },
    },
  })
}
