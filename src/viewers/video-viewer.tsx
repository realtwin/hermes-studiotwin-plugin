import * as sdk from '@hermes/plugin-sdk'
import { stageShell, glassToolbar, glassStatsPill, controlStrip, styledSelect, styledRange, inspectorToggleStyle as filterPillStyle } from '../lib/ui-tokens'
const { Button } = sdk
import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { PluginContext } from '@hermes/plugin-sdk'
import { adjacentFrame, loadVideoTiming } from './video-timing.ts'
import type { VideoLoadState } from '../lib/state-machines.ts'

import {
  deliveryUrl,
  hostPlaybackUrl,
  imageFile,
  mediaQuery,
  saveUrl,
  type MediaScope,
  type MediaSource,
} from '../cards/next-actions.ts'
export interface VideoViewerProps {
  ctx: PluginContext
  scope: MediaScope
  source: MediaSource
  frames?: MediaSource[]
  fps?: number
  resolveUrl?: () => Promise<string>
  fallback?: ReactNode
  onError?: () => void
}
export function VideoViewer({ scope, source, frames, fps, resolveUrl, fallback, onError }: VideoViewerProps) {
  const video = useRef<HTMLVideoElement>(null),
    frameImage = useRef<HTMLImageElement>(null)
  const [state, setState] = useState<VideoLoadState>({ phase: 'loading' })
  const url = state.phase === 'ready_video' ? state.url : undefined
  const urls = state.phase === 'ready_sequence' ? state.urls : undefined
  const [time, setTime] = useState(0),
    [videoDuration, setVideoDuration] = useState(0),
    [playing, setPlaying] = useState(false),
    [loop, setLoop] = useState(false),
    [rate, setRate] = useState(1)
  const [captureError, setCaptureError] = useState('')
  const fail = () => {
    setState({ phase: 'error' })
    setPlaying(false)
    onError?.()
  }
  const sequenceRate = typeof fps === 'number' && Number.isFinite(fps) && fps > 0 ? fps : undefined
  const frameRate = sequenceRate ?? 1 // internal indexing only; never reported as measured timing
  const times = state.phase === 'ready_video' ? state.frameTimes : undefined
  const duration = state.phase === 'ready_sequence' ? state.duration : videoDuration
  const canStep = frames?.length ? !!sequenceRate : !!times?.length
  const frameIndex = Math.min(Math.max(0, Math.round(time * frameRate)), Math.max(0, (urls?.length ?? 0) - 1))
  useEffect(() => {
    let live = true
    setState({ phase: 'loading' })
    setTime(0); setVideoDuration(0); setPlaying(false); setCaptureError('')
    const load = async () => {
      scope.assert()
      if (frames?.length) {
        const files = await Promise.all(frames.map((f) => imageFile(scope, f)))
        if (live) {
          scope.assert()
          setState({ phase: 'ready_sequence', urls: files.map((f) => f.dataUrl), duration: sequenceRate ? files.length / sequenceRate : 0 })
        }
      } else {
        let src: string
        if (resolveUrl)
          src = hostPlaybackUrl(await resolveUrl()) // host-owned, authenticated Range streaming on remote connections too
        else if (source.url) src = deliveryUrl(source.url)
        else {
          // Desktop's UI origin is not the API origin, even for a local gateway. Never guess
          // an unauthenticated /api URL: use resolveUrl for Range, ctx.rest for standalone directives.
          // The latter is buffered, not advertised as Range streaming.
          const f = await scope.rest<{ dataUrl: string }>(mediaQuery(source), { timeoutMs: 180000 })
          src = deliveryUrl(f.dataUrl)
        }
        scope.assert()
        if (live) setState({ phase: 'ready_video', url: src })
      }
    }
    void load().catch(() => {
      if (live) fail()
    })
    const stop = scope.watch(() => {
      video.current?.pause()
      video.current?.removeAttribute('src')
      if (live) {
        setState({ phase: 'error' })
        setPlaying(false)
      }
    })
    return () => {
      live = false
      video.current?.pause()
      stop()
    }
  }, [scope, source.path, source.asset, source.url, frames, resolveUrl, frameRate, sequenceRate])
  useEffect(() => {
    const player = video.current
    return () => {
      player?.pause()
      player?.removeAttribute('src')
    }
  }, [url])
  useEffect(() => {
    if (!url) return
    const controller = new AbortController()
    let live = true
    const timer = setTimeout(() => controller.abort(), 10000)
    const stop = scope.watch(() => controller.abort())
    void loadVideoTiming(url, controller.signal).then((times) => {
      if (live && scope.current() && !controller.signal.aborted) setState(current =>
        current.phase === 'ready_video' && current.url === url ? { ...current, frameTimes: times } : current)
    }).catch(() => { /* optional: playback is still usable without exact timing */ })
      .finally(() => clearTimeout(timer))
    return () => { live = false; controller.abort(); clearTimeout(timer); stop() }
  }, [url, scope])
  useEffect(() => {
    if (!urls?.length || !playing) return
    const timer = setInterval(
      () =>
        setTime((t) => {
          if (t + 1 / frameRate >= duration) {
            if (loop) return 0
            setPlaying(false)
            return (urls.length - 1) / frameRate
          }
          return t + 1 / frameRate
        }),
      1000 / frameRate / rate,
    )
    return () => clearInterval(timer)
  }, [urls, playing, loop, rate, duration, frameRate])
  function seek(value: number) {
    scope.assert()
    const next = Math.max(0, Math.min(value, urls?.length ? (urls.length - 1) / frameRate : duration))
    if (video.current) video.current.currentTime = next
    setTime(next)
  }
  const step = (delta: number) => {
    if (!canStep || video.current?.seeking) return
    video.current?.pause()
    setPlaying(false)
    const target = times ? adjacentFrame(times, video.current?.currentTime ?? time, delta) : time + delta / frameRate
    // Media currentTime is quantized (e.g. 1/6 rounds below its boundary).
    // Seek just inside the sample so the browser decodes the requested frame.
    seek(times && target > 0 ? target + 0.000001 : target)
  }
  const toggle = async () => {
    try {
      scope.assert()
      if (urls?.length) {
        if (!playing && time >= (urls.length - 1) / frameRate) setTime(0)
        setPlaying(!playing)
      } else if (video.current) {
        if (video.current.paused) await video.current.play()
        else video.current.pause()
      }
    } catch {
      setCaptureError('Playback unavailable. Try again after the file has loaded.')
    }
  }
  const capture = () => {
    try {
      scope.assert()
      const target = urls?.length ? frameImage.current : video.current
      if (!target) throw Error('No frame')
      const canvas = document.createElement('canvas')
      canvas.width = target instanceof HTMLVideoElement ? target.videoWidth : target.naturalWidth
      canvas.height = target instanceof HTMLVideoElement ? target.videoHeight : target.naturalHeight
      if (!canvas.width || !canvas.height) throw Error('No decoded frame')
      canvas.getContext('2d')!.drawImage(target, 0, 0)
      saveUrl(scope, canvas.toDataURL('image/png'), `studiotwin-frame-${frameIndex}.png`)
      setCaptureError('')
    } catch {
      setCaptureError('Frame capture unavailable: the source must be decoded and allow cross-origin canvas access.')
    }
  }
  if (state.phase === 'error' || !scope.current()) return <div data-video-state="error">{fallback ?? <p role="alert">Video preview unavailable.</p>}</div>
  return (
    <section data-video-state={state.phase} style={stageShell}>
      {urls?.length ? (
        <img
          ref={frameImage}
          alt={`Frame ${frameIndex + 1}`}
          src={urls[frameIndex]}
          onError={fail}
          style={{ display: 'block', width: '100%', maxHeight: 440, objectFit: 'contain', background: 'oklch(from var(--ui-bg-secondary) l 0 h)' }}
        />
      ) : url ? (
        <video
          ref={video}
          src={url}
          crossOrigin="anonymous"
          playsInline
          preload="metadata"
          loop={loop}
          onError={fail}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
          onLoadedMetadata={(e) =>
            setVideoDuration(Number.isFinite(e.currentTarget.duration) ? e.currentTarget.duration : 0)
          }
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          style={{ display: 'block', width: '100%', maxHeight: 440, background: 'oklch(from var(--ui-bg-secondary) l 0 h)' }}
        />
      ) : (
        <span role="status" style={{ position: 'absolute', left: 12, top: 12 }}>Loading video…</span>
      )}
      <div style={glassToolbar}>
        <Button variant="ghost" size="sm" style={filterPillStyle(playing)} disabled={!!frames?.length && !sequenceRate} onClick={() => void toggle()}>{playing ? 'Pause' : 'Play'}</Button>
        <Button variant="ghost" size="sm" style={filterPillStyle(false)} disabled={!canStep} onClick={() => step(-1)}>-1f</Button>
        <Button variant="ghost" size="sm" style={filterPillStyle(false)} disabled={!canStep} onClick={() => step(1)}>+1f</Button>
        <Button variant="ghost" size="sm" style={filterPillStyle(loop)} aria-pressed={loop} onClick={() => setLoop(!loop)}>
          Loop
        </Button>
        <label style={controlStrip}>
          Playback rate{' '}
          <select
            aria-label="Playback rate"
            style={styledSelect}
            value={rate}
            onChange={(e) => {
              const next = Number(e.target.value)
              setRate(next)
              if (video.current) video.current.playbackRate = next
            }}
          >
            {[0.25, 0.5, 1, 2].map((r) => (
              <option key={r} value={r}>
                {r}x
              </option>
            ))}
          </select>
        </label>
        <Button variant="ghost" size="sm" style={filterPillStyle(false)} onClick={capture}>Capture PNG</Button>
      </div>
      <input
        aria-label="Timeline"
        disabled={!!frames?.length && !sequenceRate}
        type="range"
        min="0"
        max={duration || 0}
        step={urls?.length && sequenceRate ? 1 / sequenceRate : 'any'}
        value={time}
        onChange={(e) => seek(Number(e.target.value))}
        style={{ ...styledRange, display: 'block', width: 'calc(100% - 32px)', margin: '16px' }}
      />
      <small style={{ ...glassStatsPill, display: 'block', margin: '0 16px 16px', fontVariantNumeric: 'tabular-nums', lineHeight: 1.7 }}>
        {time.toFixed(2)} / {duration.toFixed(2)} s
        {urls?.length && sequenceRate ? ` · ${sequenceRate} fps (sequence timing) · ${urls.length} frames` :
          times ? ` · ${times.length} frames · source presentation timestamps` :
          ' · Exact frame timing unavailable; frame stepping disabled.'}
      </small>
      {captureError && <p role="alert">{captureError}</p>}
    </section>
  )
}
