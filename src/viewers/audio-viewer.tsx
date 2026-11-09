import { inspectorButtonStyle, inspectorChipStyle } from '../lib/ui-tokens.ts';
// Waveform/transport adapted from Nous Research elevenlabs-sound-effects src/ui.tsx (MIT).
// Copyright (c) 2026 Nous Research. Canvas rendition and StudioTwin backend adapter are local.
import * as sdk from '@hermes/plugin-sdk'
import { cardShell, cardHeader, cardTitle, cleanDisplayName, nextDrawerStyle, nextSummaryStyle, nextActionChipStyle, creditBadgeStyle, glassToolbar, glassStatsPill, controlStrip, cardSubtitle, inspectorToggleStyle as filterPillStyle } from '../lib/ui-tokens'
import type { PluginContext } from '@hermes/plugin-sdk'
const { Badge, Button, host } = sdk
import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { AudioViewerState } from '../lib/state-machines.ts'
import {
  AUDIO_FORMATS, AudioPlayer, assertScope, decodeAudio, fetchAudio, nextActions, onScopeChange,
  peaks, saveAudio, scopeMatches, submitNext, type AudioPayload, type AudioSource, type Scope
} from './audio-engine.ts'

export function Waveform({ data, progress, onSeek }: { data: number[]; progress: number; onSeek: (fraction: number) => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const draw = () => {
      const bounds = canvas.getBoundingClientRect()
      const ratio = window.devicePixelRatio || 1
      const width = Math.max(1, bounds.width), height = Math.max(1, bounds.height)
      canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio)
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0); ctx.clearRect(0, 0, width, height)
      const accent = `oklch(from ${getComputedStyle(canvas).getPropertyValue('--ui-text-primary').trim()} l 0 h)`
      const muted = `oklch(from ${getComputedStyle(canvas).getPropertyValue('--ui-text-tertiary').trim() || accent} l 0 h)`
      const top = Math.max(.05, ...data)
      for (let i = 0; i < data.length; i++) {
        const bar = Math.max(2, data[i] / top * (height - 4))
        ctx.fillStyle = i / data.length < progress ? accent : muted
        ctx.fillRect(i * width / data.length, (height - bar) / 2, Math.max(1, width / data.length - 1), bar)
      }
    }
    const observer = new ResizeObserver(draw)
    observer.observe(canvas); draw()
    // Themes generally change on an ancestor (class/style), not on the canvas itself.
    const theme = new MutationObserver(draw)
    for (let parent: Element | null = canvas; parent; parent = parent.parentElement) theme.observe(parent, { attributes: true, attributeFilter: ['class', 'style', 'data-theme'] })
    return () => { observer.disconnect(); theme.disconnect() }
  }, [data, progress])
  return <canvas ref={canvasRef} role="slider" tabIndex={0} aria-label="Waveform; click or use arrow keys to seek"
    aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}
    style={{ display: 'block', width: '100%', height: 88, cursor: 'pointer', touchAction: 'manipulation', borderRadius: 6 }}
    onClick={event => {
      const r = event.currentTarget.getBoundingClientRect()
      if (r.width > 0) onSeek(Math.min(1, Math.max(0, (event.clientX - r.left) / r.width)))
    }}
    onKeyDown={event => {
      if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
        event.preventDefault()
        onSeek(event.key === 'Home' ? 0 : event.key === 'End' ? 1 : Math.min(1, Math.max(0, progress + (event.key === 'ArrowRight' ? .05 : -.05))))
      }
    }} />
}

export interface AudioViewerProps {
  ctx: PluginContext
  source: AudioSource
  scope: Scope
  sessionId?: string | null
  dataUrl?: string
  prompt?: string
  fallback?: ReactNode
}
type Ready = { buffer: AudioBuffer; wave: number[]; payload: AudioPayload }
export function AudioViewer({ ctx, source, scope, sessionId, dataUrl, prompt = '', fallback }: AudioViewerProps) {
  const [state, setState] = useState<AudioViewerState<Ready>>({ phase: 'loading', convertingFormat: null })
  const ready = state.phase === 'ready' ? state.data : null
  const [loop, setLoop] = useState(false)
  const [, tick] = useState(0)
  const player = useRef<AudioPlayer | null>(null)
  const key = JSON.stringify(source)
  useEffect(() => {
    let live = true
    setState({ phase: 'loading', convertingFormat: null }); setLoop(false)
    let transport: AudioPlayer | null = null
    const fail = () => { if (live) { transport?.dispose(); player.current = null; setState({ phase: 'error', convertingFormat: null }) } }
    const off = onScopeChange(() => { if (!scopeMatches(scope)) fail() })
    void (async () => {
      try {
        assertScope(scope)
        const context = new AudioContext()
        transport = new AudioPlayer(context); player.current = transport
        const payload = dataUrl ? { dataUrl, mime: /^data:([^;]+)/.exec(dataUrl)?.[1] ?? '', name: 'sound', bytes: 0 } : await fetchAudio(ctx, source, scope)
        if (!live) return
        assertScope(scope)
        const buffer = await decodeAudio(payload.dataUrl, context)
        if (!live) return
        assertScope(scope)
        if (dataUrl) payload.bytes = atob(dataUrl.split(',')[1]).length
        transport.load(buffer)
        setState({ phase: 'ready', data: { buffer, wave: peaks(buffer), payload }, convertingFormat: null })
      } catch { fail() }
    })()
    return () => { live = false; off(); transport?.dispose(); player.current = null }
  }, [ctx, key, scope, dataUrl]) // key keeps a newly allocated but equal source from re-decoding.
  const playing = player.current?.playing ?? false
  useEffect(() => {
    if (!ready || !playing) return
    let frame = 0
    const draw = () => { tick(t => t + 1); frame = requestAnimationFrame(draw) }
    frame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(frame)
  }, [ready, playing])
  if (state.phase === 'error') return <div data-audio-state={state.phase} data-audio-playing={String(playing)}>{fallback ?? <p role="alert" style={{ color: 'var(--ui-red)' }}>Audio unavailable in this profile. Use the original file/player.</p>}</div>
  if (!ready) return <p data-audio-state={state.phase} data-audio-playing={String(playing)} role="status" style={{ color: 'oklch(from var(--ui-text-tertiary) l 0 h)' }}>Loading StudioTwin audio…</p>
  const position = player.current?.position() ?? 0
  const progress = position / ready.buffer.duration
  const guarded = async (fn: () => Promise<void>) => {
    try { assertScope(scope); await fn() } catch { setState({ phase: 'error', convertingFormat: null }); player.current?.dispose() }
    tick(t => t + 1)
  }
  return <section data-audio-state={state.phase} data-audio-playing={String(playing)} aria-label="StudioTwin sound effect" style={{ ...cardShell, maxWidth: 640 }}>
    <header style={cardHeader}>
      {Object.hasOwn(sdk, 'Codicon') && <sdk.Codicon name="unmute" size={16} />}
      <strong style={cardTitle}>{cleanDisplayName(prompt || ready.payload.name).title}</strong>
      <span style={creditBadgeStyle}>Audio SFX</span>
    </header>
    <div style={{ padding: '0 14px 14px' }}>
    {cleanDisplayName(prompt || ready.payload.name).shortId && <div style={{ ...cardSubtitle, marginTop: 10 }}>{ready.payload.name}</div>}
    <div style={{ ...controlStrip, flexWrap: 'wrap', marginTop: 12 }}>
      <Badge variant="muted" style={inspectorChipStyle}>{ready.buffer.duration.toFixed(3)} s</Badge>
      <Badge variant="muted" style={inspectorChipStyle}>{ready.payload.mime.replace('audio/', '').toUpperCase()}</Badge>
      <Badge variant="muted" style={inspectorChipStyle} title="Decoded playback sample rate; Web Audio may resample the source">{ready.buffer.sampleRate} Hz</Badge>
      <Badge variant="muted" style={inspectorChipStyle}>{ready.payload.bytes.toLocaleString()} B</Badge>
    </div>
    <div style={{ padding: 10, borderRadius: 10, margin: '16px 0', border: '1px solid oklch(from var(--ui-stroke-secondary) l 0 h)', background: 'color-mix(in srgb, oklch(from var(--ui-bg) l 0 h) 70%, oklch(from var(--ui-bg-secondary) l 0 h))' }}>
      <Waveform data={ready.wave} progress={progress} onSeek={f => void guarded(() => player.current?.seek(f * ready.buffer.duration) ?? Promise.resolve())} />
    </div>
    <div style={glassToolbar}>
      <Button variant="ghost" size="sm" style={filterPillStyle(playing)} aria-label={playing ? 'Pause' : 'Play'} onClick={() => void guarded(async () => {
        if (player.current?.playing) player.current.pause()
        else await player.current?.play(ready.buffer, loop, player.current.position())
      })}>{playing ? 'Pause' : 'Play'}</Button>
      <Button size="sm" style={filterPillStyle(loop)} variant="outline" aria-label="Loop audition" aria-pressed={loop} onClick={() => {
        if (!scopeMatches(scope)) { setState({ phase: 'error', convertingFormat: null }); return }
        player.current?.setLoop(!loop); setLoop(!loop)
      }}>Loop</Button>
      <span style={{ ...glassStatsPill, fontVariantNumeric: 'tabular-nums' }}>{position.toFixed(2)} / {ready.buffer.duration.toFixed(2)} s</span>
      <details><summary style={{ ...filterPillStyle(false), cursor: 'pointer' }}>Download / Convert</summary><div style={{ ...controlStrip, flexWrap: 'wrap', marginTop: 8 }}>
        {AUDIO_FORMATS.map(format => <Button style={inspectorButtonStyle} key={format} size="sm" variant="outline" disabled={state.convertingFormat !== null} aria-label={`Download ${format.toUpperCase()}`} onClick={() => {
          setState(current => current.phase === 'ready' ? { ...current, convertingFormat: format } : current)
          void guarded(async () => {
            const payload = await fetchAudio(ctx, source, scope, format)
            assertScope(scope); await saveAudio(payload)
          }).finally(() => setState(current => current.phase === 'ready' ? { ...current, convertingFormat: null } : current))
        }}>{format === 'original' ? 'Original' : `.${format}`}</Button>)}
      </div></details>
    </div>
    <details style={{ ...nextDrawerStyle, margin: '10px 0' }}><summary style={nextSummaryStyle}>Next</summary><div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
      {nextActions(source, prompt).map(action => <Button style={nextActionChipStyle} key={action.id} size="sm" variant="ghost" title={action.message} onClick={() => {
        if (!submitNext(scope, sessionId, action)) host.notify({ kind: 'warning', message: 'Open the originating chat and profile/connection to use this action.' })
      }}>{action.label} · <span style={creditBadgeStyle}>{action.cost}</span></Button>)}
    </div></details>
    <p style={{ ...cardSubtitle, marginBottom: 0 }}>Gapless loop audition · WAV/OGG recommended for engine loops</p>
    </div>
  </section>
}
