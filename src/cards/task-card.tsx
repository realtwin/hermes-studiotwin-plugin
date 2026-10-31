// Progress-card shape adapted from Nous Research meshy/src/task-card.tsx (MIT).
// Polling uses the host's shared Query client; no parallel job ledger or generation retry.
import * as sdk from '@hermes/plugin-sdk'
import { cardShell, cardHeader, cardTitle, cardSubtitle, statusBadgeStyle, creditBadgeStyle, nextDrawerStyle, nextSummaryStyle, nextActionChipStyle } from '../lib/ui-tokens'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ImageCard, conceptImages } from './image-card.tsx'
import { VideoCard } from './video-card.tsx'
import { ModelCard } from './model-card.tsx'
import { deliveryUrl, object, submitNext, useMediaScope, type MediaScope, type NextAction } from './next-actions.ts'
export function jobStatus(value: unknown): string {
  const status = String(value ?? '')
    .toLowerCase()
    .replace(/[- ]/g, '_')
  if (['done', 'complete', 'completed', 'succeeded', 'success'].includes(status)) return 'completed'
  if (['submitted', 'pending', 'draft', 'queued'].includes(status)) return 'queued'
  if (['executing', 'in_progress', 'processing', 'running'].includes(status)) return 'running'
  if (['canceled', 'cancelled'].includes(status)) return 'cancelled'
  if (['failed', 'error'].includes(status)) return 'failed'
  throw Error('Unknown job status')
}
const terminal = (status: string) => ['completed', 'failed', 'cancelled'].includes(status)
export interface TaskCardProps {
  ctx: sdk.PluginContext
  id: string
  kind?: 'task' | 'job' | 'concept'
  sessionId?: string | null
  fallback?: ReactNode
  pollInterval?: number
  auto_rotate?: boolean
  webgl_limit?: number
}
function CompletedMedia({
  ctx,
  info,
  scope,
  sessionId,
  auto_rotate,
  webgl_limit,
}: {
  ctx: sdk.PluginContext
  info: Record<string, any>
  scope: MediaScope
  sessionId?: string | null
  auto_rotate?: boolean
  webgl_limit?: number
}) {
  const output = object(info.outputs),
    history = conceptImages(info),
    active = history.find((a: any) => a.active) ?? history.at(-1)
  const asset = output.assetId ?? info.assetId
  const type = String(info.type ?? output.type ?? '')
  if (active || output.imageUrl || output.imageUrls?.[0] || (asset && type === 'image'))
    return (
      <ImageCard
        ctx={ctx}
        scope={scope}
        source={active?.source ?? (asset ? { asset } : { url: output.imageUrl ?? output.imageUrls[0] })}
        before={active?.before}
        history={history}
        provenanceId={info.id ?? info.uuid}
        sessionId={sessionId}
        actions={[]}
      />
    )
  if (output.videoUrl || (asset && ['video', 'image_sequence'].includes(type)))
    return <VideoCard ctx={ctx} scope={scope} source={asset ? { asset } : { url: output.videoUrl }} />
  if (asset && ['3d_model', 'animation'].includes(type))
    return <ModelCard ctx={ctx} source={{ asset }} sessionId={sessionId} auto_rotate={auto_rotate} webgl_limit={webgl_limit} />
  if (typeof output.audioClip === 'string' && /^https?:/.test(output.audioClip))
    return <audio aria-label="Completed audio" controls src={deliveryUrl(output.audioClip)} />
  const links = Object.entries(output).filter(
    ([, value]) => typeof value === 'string' && /^(https?:\/\/|s3:\/\/)/.test(value),
  )
  return (
    <div>
      {links.length ? (
        links.map(([key, value]) =>
          /^https?:/.test(String(value)) ? (
            <a key={key} href={String(value)} target="_blank" rel="noreferrer">
              Download {key}
            </a>
          ) : (
            <p key={key}>
              {key}: {String(value)}
            </p>
          ),
        )
      ) : (
        <p>Completed. No previewable media was reported.</p>
      )}
    </div>
  )
}
export function TaskCard({ ctx, id, kind = 'task', sessionId, fallback, pollInterval = 3000, auto_rotate, webgl_limit }: TaskCardProps) {
  const { scope, stale } = useMediaScope(ctx)
  const [failed, setFailed] = useState(false),
    [cancelled, setCancelled] = useState(false),
    [cancelling, setCancelling] = useState(false),
    [cancelError, setCancelError] = useState('')
  const busy = useRef(false),
    start = useRef(Date.now()),
    [elapsed, setElapsed] = useState(0)
  const query = sdk.useQuery({
    queryKey: ['studiotwin', scope.key, kind, id],
    queryFn: async () => {
      const path =
        kind === 'job'
          ? `/jobs/${encodeURIComponent(id)}`
          : kind === 'concept'
            ? `/concepts/${encodeURIComponent(id)}/status`
            : `/task?id=${encodeURIComponent(id)}`
      const row = object(await scope.rest(path, { timeoutMs: 20000 }))
      const status = jobStatus(kind === 'concept' ? (row.operation?.status ?? row.lifecycleStatus) : row.status)
      if (kind === 'concept' && status === 'completed')
        return { ...object(await scope.rest(`/concepts/${encodeURIComponent(id)}`)), ...row, status }
      return { ...row, status }
    },
    enabled: !stale && !failed && !cancelled,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchInterval: (q) =>
      q.state.data && terminal(q.state.data.status) ? false : q.state.error ? false : pollInterval,
  })
  const info: Record<string, any> | undefined = query.data,
    status = cancelled ? 'cancelled' : (info?.status ?? 'loading')
  const done = status === 'completed'
  const conceptHistory = kind === 'concept' ? conceptImages(info) : []
  const actionsId = (conceptHistory.find((a: any) => a.active) ?? conceptHistory.at(-1))?.source.asset ?? id
  const actions = sdk.useQuery({
    queryKey: ['studiotwin-actions', scope.key, kind, actionsId],
    enabled: done && !stale && !failed,
    queryFn: () =>
      scope.rest<{ actions: NextAction[] }>(
        `/actions?id=${encodeURIComponent(actionsId)}&type=${kind === 'concept' ? 'image' : 'job'}`,
      ),
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
  useEffect(() => {
    if (query.isError) setFailed(true)
  }, [query.isError])
  useEffect(() => {
    if (stale || failed || terminal(status)) return
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - start.current) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [stale, failed, status])
  const cancel = async () => {
    if (busy.current || status !== 'queued' || kind === 'concept') return
    try {
      scope.assert()
      busy.current = true
      setCancelling(true)
      setCancelError('')
      // Never submit generation here. This is one free cancellation of the existing queued job.
      const response = object(await scope.rest('/cancel', { method: 'POST', body: { id } }))
      scope.assert()
      if (['cancelled', 'canceled'].includes(String(response.status).toLowerCase())) setCancelled(true)
      else await query.refetch() // acknowledgement alone is not a terminal status
    } catch {
      if (scope.current())
        setCancelError('Cancellation could not be confirmed. Check the existing job before retrying.')
    } finally {
      busy.current = false
      setCancelling(false)
    }
  }
  if (stale || failed)
    return <>{fallback ?? <p role="alert">Task unavailable. Reopen in the originating profile and connection.</p>}</>
  const pct =
    typeof info?.progress === 'number' && Number.isFinite(info.progress)
      ? Math.max(0, Math.min(100, info.progress))
      : undefined
  return (
    <article
      data-studiotwin-task={status}
      style={{ ...cardShell, maxWidth: 720, color: 'var(--ui-text-primary)' }}
    >
      <header style={cardHeader}>
        {Object.hasOwn(sdk, 'Codicon') && <sdk.Codicon name="pulse" size={16} />}
        <strong style={cardTitle}>StudioTwin {kind}</strong> · <span style={statusBadgeStyle(status)} role="status">{status}</span> · <span style={cardSubtitle}>{elapsed} s elapsed</span>
      </header>
      {!terminal(status) && (
        <>
          <progress
            aria-label="Job progress"
            max="100"
            value={pct}
            style={{ width: 'calc(100% - 28px)', margin: '14px 14px 8px', height: 8, borderRadius: 999, overflow: 'hidden', accentColor: 'var(--ui-accent)', transition: 'all .3s ease' }}
          />
          {pct !== undefined ? <small style={{ ...cardSubtitle, padding: 14 }}>{pct}%</small> : <small style={{ ...cardSubtitle, padding: 14 }}>Progress not reported</small>}
        </>
      )}
      {status === 'queued' && kind !== 'concept' && (
        <sdk.Button disabled={cancelling} onClick={() => void cancel()}>
          Cancel queued job
        </sdk.Button>
      )}
      {cancelError && <p role="alert">{cancelError}</p>}
      {status === 'failed' && (
        <p role="alert">
          Job failed. {typeof info?.error === 'string' ? info.error : 'Inspect the existing job before any paid retry.'}
        </p>
      )}
      {done && info && <CompletedMedia ctx={ctx} info={info} scope={scope} sessionId={sessionId} auto_rotate={auto_rotate} webgl_limit={webgl_limit} />}
      {done && actions.data?.actions?.length ? (
        <details style={nextDrawerStyle}>
          <summary style={nextSummaryStyle}>Next · review and approve in chat</summary>
          {actions.data.actions.map((a) => (
            <sdk.Button
              key={a.id}
              style={nextActionChipStyle}
              onClick={() => {
                try {
                  submitNext(scope, sessionId, a)
                } catch {
                  /* invalidated */
                }
              }}
            >
              {a.label} · <span style={creditBadgeStyle}>{a.cost_label ?? (a.cost == null ? 'estimate first' : `${a.cost} cr`)}</span>
            </sdk.Button>
          ))}
        </details>
      ) : null}
      {done && actions.isError && <p role="status">Next actions unavailable. No generation was submitted.</p>}
    </article>
  )
}
export function registerTaskCards(ctx: sdk.PluginContext) {
  for (const kind of ['task', 'job', 'concept'] as const)
    ctx.register({
      id: `studiotwin-${kind}-directive`,
      area: sdk.TRANSCRIPT_DIRECTIVE_AREA ?? 'transcript.directives',
      data: {
        name: `studiotwin-${kind}`,
        render: (p: sdk.TranscriptDirectiveProps) =>
          p.streaming || !p.attrs.id ? (
            <p>{p.source}</p>
          ) : (
            <TaskCard
              key={`${kind}:${p.attrs.id}`}
              ctx={ctx}
              id={p.attrs.id}
              kind={p.attrs.kind === 'concept' ? 'concept' : kind}
              sessionId={p.sessionId}
              fallback={<p>{p.source}</p>}
            />
          ),
      },
    })
}
