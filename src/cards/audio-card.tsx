// Card/renderer pattern adapted from Nous Research elevenlabs-sound-effects src/card.tsx (MIT).
// Copyright (c) 2026 Nous Research. V07 calls registerAudioCards from the unified entrypoint.
import * as sdk from '@hermes/plugin-sdk'
import type { PluginContext, ToolMediaRendererProps, TranscriptDirectiveProps } from '@hermes/plugin-sdk'
import { useState, type ReactNode } from 'react'
import { AudioViewer } from '../viewers/audio-viewer.tsx'
import { currentScope, type AudioSource } from '../viewers/audio-engine.ts'

export interface AudioCardProps {
  ctx: PluginContext
  source: AudioSource
  sessionId?: string | null
  fallback?: ReactNode
  dataUrl?: string
  prompt?: string
}
export function AudioCard(props: AudioCardProps) {
  // Lifetime ownership, NOT the current scope on each rerender. Switching invalidates, never retargets.
  const [scope] = useState(currentScope)
  return <AudioViewer {...props} scope={scope} />
}
function resultObject(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') { try { value = JSON.parse(value) } catch { return {} } }
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
// Hermes mcp_tool_schema sanitizes the provider's hyphens to underscores.
export const AUDIO_TOOLS = ['mcp__studiotwin__text_to_sound_effect', 'mcp_studiotwin_text_to_sound_effect'] as const
export function ToolMediaAudioCard({ ctx, media }: { ctx: PluginContext; media: ToolMediaRendererProps }) {
  const result = resultObject(media.result)
  if (!(AUDIO_TOOLS as readonly string[]).includes(media.toolName) || media.file.kind !== 'audio' || result.success === false || result.error) return <>{media.fallback}</>
  // Tool-media's attributed file is authoritative. No claiming arbitrary terminal/user files by suffix.
  if (!media.file.path) return <>{media.fallback}</>
  return <AudioCard ctx={ctx} source={{ path: media.file.path }} sessionId={media.sessionId}
    fallback={media.fallback} prompt={typeof media.args.prompt === 'string' ? media.args.prompt : ''} />
}
export function DirectiveAudioCard({ ctx, directive }: { ctx: PluginContext; directive: TranscriptDirectiveProps }) {
  if (directive.streaming) return <p>{directive.source}</p>
  const { path, asset, prompt } = directive.attrs
  if (Boolean(path) === Boolean(asset)) return <p>{directive.source}</p>
  return <AudioCard ctx={ctx} source={path ? { path } : { asset }} prompt={prompt} sessionId={directive.sessionId} fallback={<p>{directive.source}</p>} />
}
export function registerAudioCards(ctx: PluginContext): void {
  if (typeof sdk.TOOL_MEDIA_RENDERER_AREA === 'string') ctx.register({
    id: 'studiotwin-audio-media', area: sdk.TOOL_MEDIA_RENDERER_AREA,
    data: { tools: AUDIO_TOOLS, render: (media: ToolMediaRendererProps) => <ToolMediaAudioCard key={`${media.toolCallId}:${media.file.path}`} ctx={ctx} media={media} /> }
  })
  ctx.register({ id: 'studiotwin-audio-directive', area: sdk.TRANSCRIPT_DIRECTIVE_AREA,
    data: { name: 'studiotwin-audio', render: (directive: TranscriptDirectiveProps) => <DirectiveAudioCard ctx={ctx} directive={directive} /> }
  })
}
