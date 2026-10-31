import * as sdk from '@hermes/plugin-sdk'
import { useState, type ReactNode } from 'react'
import { VideoViewer } from '../viewers/video-viewer.tsx'
import { object, useMediaScope, type MediaScope, type MediaSource } from './next-actions.ts'
export interface VideoCardProps {
  ctx: sdk.PluginContext
  source: MediaSource
  frames?: MediaSource[]
  fps?: number
  resolveUrl?: () => Promise<string>
  fallback?: ReactNode
  scope?: MediaScope
  sessionId?: string | null
}
export function VideoCard(props: VideoCardProps) {
  const { scope, stale } = useMediaScope(props.ctx, props.scope)
  const [failed, setFailed] = useState(false)
  if (stale || failed)
    return <>{props.fallback ?? <p>Video unavailable. Reopen in the originating profile and connection.</p>}</>
  return (
    <article
      style={{
        padding: 8,
        maxWidth: 720,
        border: '1px solid var(--ui-stroke-secondary)',
        borderRadius: 10,
        color: 'var(--ui-text-primary)',
      }}
    >
      <strong>StudioTwin Video / Sequence</strong>
      <VideoViewer {...props} scope={scope} onError={() => setFailed(true)} />
    </article>
  )
}
// Claim only package producing tools. Terminal render_preview outputs are opened by directive, not hijacked.
export const VIDEO_TOOLS = [
  'image_to_3d_mesh',
  'tripo_image_to_3d_mesh',
  'text_to_motion',
  'text_to_motion_kimodo',
  'text_to_motion_edit',
  'text_to_motion_control',
  'environment_map_to_world',
].flatMap((n) => [n.replace(/_/g, '-'), `mcp__studiotwin__${n}`, `mcp_studiotwin_${n}`])
export function registerVideoCards(ctx: sdk.PluginContext) {
  if (typeof sdk.TOOL_MEDIA_RENDERER_AREA === 'string')
    ctx.register({
      id: 'studiotwin-video-media',
      area: sdk.TOOL_MEDIA_RENDERER_AREA,
      data: {
        tools: VIDEO_TOOLS,
        render: (p: sdk.ToolMediaRendererProps) => {
          const result = object(p.result)
          if (!VIDEO_TOOLS.includes(p.toolName) || p.file.kind !== 'video' || result.error || result.success === false)
            return p.fallback
          return (
            <VideoCard
              key={p.toolCallId + p.file.path}
              ctx={ctx}
              source={{ path: p.file.path }}
              resolveUrl={p.file.resolveUrl}
              fallback={p.fallback}
              sessionId={p.sessionId}
            />
          )
        },
      },
    })
  ctx.register({
    id: 'studiotwin-video-directive',
    area: sdk.TRANSCRIPT_DIRECTIVE_AREA,
    data: {
      name: 'studiotwin-video',
      render: (p: sdk.TranscriptDirectiveProps) => {
        const { path, asset, url, frames: rawFrames, fps } = p.attrs
        let frames: MediaSource[] | undefined
        try {
          if (rawFrames) {
            const parsed = JSON.parse(rawFrames)
            if (
              !Array.isArray(parsed) ||
              !parsed.every((f) => f && typeof f === 'object' && [f.path, f.asset, f.url].filter(Boolean).length === 1)
            )
              return <p>{p.source}</p>
            frames = parsed
          }
        } catch {
          return <p>{p.source}</p>
        }
        if (p.streaming || (!frames?.length && [path, asset, url].filter(Boolean).length !== 1))
          return <p>{p.source}</p>
        return (
          <VideoCard
            key={JSON.stringify(p.attrs)}
            ctx={ctx}
            source={{ path, asset, url }}
            frames={frames}
            fps={fps ? Number(fps) : undefined}
            sessionId={p.sessionId}
            fallback={<p>{p.source}</p>}
          />
        )
      },
    },
  })
}
