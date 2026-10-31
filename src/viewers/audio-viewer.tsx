// Waveform/transport adapted from Nous Research elevenlabs-sound-effects src/ui.tsx (MIT).
// Copyright (c) 2026 Nous Research. Canvas rendition and StudioTwin backend adapter are local.
import { Badge, Button, host, type PluginContext } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState, type ReactNode } from 'react'
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
      const accent = getComputedStyle(canvas).getPropertyValue('--ui-accent').trim()
      const muted = getComputedStyle(canvas).getPropertyValue('--ui-text-tertiary').trim()
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
    style={{ display: 'block', width: '100%', height: 64, cursor: 'pointer', touchAction: 'manipulation' }}
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
  const [ready, setReady] = useState<Ready | null>(null)
  const [error, setError] = useState(false)
  const [loop, setLoop] = useState(false)
  const [busy, setBusy] = useState(false)
  const [, tick] = useState(0)
  const player = useRef<AudioPlayer | null>(null)
  const key = JSON.stringify(source)
  useEffect(() => {
    let live = true
    setReady(null); setError(false); setLoop(false)
    let transport: AudioPlayer | null = null
    const fail = () => { if (live) { transport?.dispose(); player.current = null; setError(true) } }
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
        setReady({ buffer, wave: peaks(buffer), payload })
      } catch { fail() }
    })()
    return () => { live = false; off(); transport?.dispose(); player.current = null }
  }, [ctx, key, scope, dataUrl]) // key keeps a newly allocated but equal source from re-decoding.
  const playing = player.current?.playing ?? false
  useEffect(() => {
    if (!ready || error || !playing) return
    let frame = 0
    const draw = () => { tick(t => t + 1); frame = requestAnimationFrame(draw) }
    frame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(frame)
  }, [ready, error, playing])
  if (error) return <>{fallback ?? <p role="alert" style={{ color: 'var(--ui-red)' }}>Audio unavailable in this profile. Use the original file/player.</p>}</>
  if (!ready) return <p role="status" style={{ color: 'var(--ui-text-tertiary)' }}>Loading StudioTwin audio…</p>
  const position = player.current?.position() ?? 0
  const progress = position / ready.buffer.duration
  const guarded = async (fn: () => Promise<void>) => {
    try { assertScope(scope); await fn() } catch { setError(true); player.current?.dispose() }
    tick(t => t + 1)
  }
  return <section aria-label="StudioTwin sound effect" style={{ padding: 12, borderRadius: 12, border: '1px solid var(--ui-stroke-secondary)', background: 'var(--ui-bg-card)', color: 'var(--ui-text-primary)', maxWidth: 640 }}>
    <div style={{ fontWeight: 500, overflowWrap: 'anywhere' }}>{prompt || ready.payload.name}</div>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, color: 'var(--ui-text-secondary)', marginTop: 8 }}>
      <Badge>{ready.buffer.duration.toFixed(3)} s</Badge>
      <Badge>{ready.payload.mime.replace('audio/', '').toUpperCase()}</Badge>
      <Badge title="Decoded playback sample rate; Web Audio may resample the source">{ready.buffer.sampleRate} Hz</Badge>
      <Badge>{ready.payload.bytes.toLocaleString()} B</Badge>
    </div>
    <Waveform data={ready.wave} progress={progress} onSeek={f => void guarded(() => player.current?.seek(f * ready.buffer.duration) ?? Promise.resolve())} />
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
      <Button size="sm" aria-label={playing ? 'Pause' : 'Play'} onClick={() => void guarded(async () => {
        if (player.current?.playing) player.current.pause()
        else await player.current?.play(ready.buffer, loop, player.current.position())
      })}>{playing ? 'Pause' : 'Play'}</Button>
      <Button size="sm" variant="outline" aria-label="Loop audition" aria-pressed={loop} onClick={() => {
        if (!scopeMatches(scope)) { setError(true); return }
        player.current?.setLoop(!loop); setLoop(!loop)
      }}>Loop</Button>
      <span style={{ color: 'var(--ui-text-tertiary)', fontVariantNumeric: 'tabular-nums' }}>{position.toFixed(2)} / {ready.buffer.duration.toFixed(2)} s</span>
      <details><summary>Download / Convert</summary><div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {AUDIO_FORMATS.map(format => <Button key={format} size="sm" variant="outline" disabled={busy} aria-label={`Download ${format.toUpperCase()}`} onClick={() => {
          setBusy(true)
          void guarded(async () => {
            const payload = await fetchAudio(ctx, source, scope, format)
            assertScope(scope); await saveAudio(payload)
          }).finally(() => setBusy(false))
        }}>{format === 'original' ? 'Original' : `.${format}`}</Button>)}
      </div></details>
      <details><summary>Next</summary><div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {nextActions(source, prompt).map(action => <Button key={action.id} size="sm" variant="ghost" title={action.message} onClick={() => {
          if (!submitNext(scope, sessionId, action)) host.notify({ kind: 'warning', message: 'Open the originating chat and profile/connection to use this action.' })
        }}>{action.label} · {action.cost}</Button>)}
      </div></details>
    </div>
    <p style={{ marginBottom: 0, color: 'var(--ui-text-tertiary)', fontSize: 12 }}>Gapless loop audition · WAV/OGG recommended for engine loops</p>
  </section>
}
