import * as sdk from '@hermes/plugin-sdk'
const { Button } = sdk
import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { PluginContext } from '@hermes/plugin-sdk'
import { adjacentFrame, loadVideoTiming } from './video-timing.ts'

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
  const [url, setUrl] = useState<string>(),
    [urls, setUrls] = useState<string[]>([]),
    [failed, setFailed] = useState(false)
  const [time, setTime] = useState(0),
    [duration, setDuration] = useState(0),
    [playing, setPlaying] = useState(false),
    [loop, setLoop] = useState(false),
    [rate, setRate] = useState(1)
  const [captureError, setCaptureError] = useState('')
  const fail = () => {
    setFailed(true)
    onError?.()
  }
  const sequenceRate = typeof fps === 'number' && Number.isFinite(fps) && fps > 0 ? fps : undefined
  const frameRate = sequenceRate ?? 1 // internal indexing only; never reported as measured timing
  const [timing, setTiming] = useState<{ url: string; times: number[] }>()
  const times = timing && timing.url === url ? timing.times : undefined
  const canStep = frames?.length ? !!sequenceRate : !!times?.length
  const frameIndex = Math.min(Math.max(0, Math.round(time * frameRate)), Math.max(0, urls.length - 1))
  useEffect(() => {
    let live = true
    const load = async () => {
      scope.assert()
      if (frames?.length) {
        const files = await Promise.all(frames.map((f) => imageFile(scope, f)))
        if (live) {
          scope.assert()
          setUrls(files.map((f) => f.dataUrl))
          setDuration(sequenceRate ? files.length / sequenceRate : 0)
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
        if (live) setUrl(src)
      }
    }
    void load().catch(() => {
      if (live) fail()
    })
    const stop = scope.watch(() => {
      video.current?.pause()
      video.current?.removeAttribute('src')
      if (live) {
        setFailed(true)
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
      if (live && scope.current() && !controller.signal.aborted) setTiming({ url, times })
    }).catch(() => { /* optional: playback is still usable without exact timing */ })
      .finally(() => clearTimeout(timer))
    return () => { live = false; controller.abort(); clearTimeout(timer); stop() }
  }, [url, scope])
  useEffect(() => {
    if (!urls.length || !playing) return
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
    const next = Math.max(0, Math.min(value, urls.length ? (urls.length - 1) / frameRate : duration))
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
      if (urls.length) {
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
      const target = urls.length ? frameImage.current : video.current
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
  if (failed || !scope.current()) return <>{fallback ?? <p role="alert">Video preview unavailable.</p>}</>
  return (
    <section style={{ color: 'var(--ui-text-primary)' }}>
      {urls.length ? (
        <img
          ref={frameImage}
          alt={`Frame ${frameIndex + 1}`}
          src={urls[frameIndex]}
          onError={fail}
          style={{ width: '100%', maxHeight: 440, objectFit: 'contain' }}
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
            setDuration(Number.isFinite(e.currentTarget.duration) ? e.currentTarget.duration : 0)
          }
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          style={{ width: '100%', maxHeight: 440 }}
        />
      ) : (
        <p role="status">Loading video…</p>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        <Button disabled={!!frames?.length && !sequenceRate} onClick={() => void toggle()}>{playing ? 'Pause' : 'Play'}</Button>
        <Button disabled={!canStep} onClick={() => step(-1)}>-1f</Button>
        <Button disabled={!canStep} onClick={() => step(1)}>+1f</Button>
        <Button aria-pressed={loop} onClick={() => setLoop(!loop)}>
          Loop
        </Button>
        <label>
          Playback rate{' '}
          <select
            aria-label="Playback rate"
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
        <Button onClick={capture}>Capture PNG</Button>
      </div>
      <input
        aria-label="Timeline"
        disabled={!!frames?.length && !sequenceRate}
        type="range"
        min="0"
        max={duration || 0}
        step={urls.length && sequenceRate ? 1 / sequenceRate : 'any'}
        value={time}
        onChange={(e) => seek(Number(e.target.value))}
        style={{ width: '100%', accentColor: 'var(--ui-accent)' }}
      />
      <small>
        {time.toFixed(2)} / {duration.toFixed(2)} s
        {urls.length && sequenceRate ? ` · ${sequenceRate} fps (sequence timing) · ${urls.length} frames` :
          times ? ` · ${times.length} frames · source presentation timestamps` :
          ' · Exact frame timing unavailable; frame stepping disabled.'}
      </small>
      {captureError && <p role="alert">{captureError}</p>}
    </section>
  )
}
