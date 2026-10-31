import { createFile, type Movie } from 'mp4box'

// Read presentation timestamps, not average frame rates: reordered and variable-rate
// samples must seek in presentation order. Deliberately decline fragmented movies,
// multiple video tracks and complex edit lists rather than promising exact steps.
export function mp4FrameTimes(buffer: ArrayBuffer): number[] {
  const file = createFile()
  let movie: Movie | undefined
  file.onReady = (info) => { movie = info }
  file.onError = () => { throw Error('Unreadable MP4 timing') }
  const input = Object.assign(buffer, { fileStart: 0 })
  file.appendBuffer(input)
  file.flush()
  if (!movie || movie.isFragmented || movie.videoTracks.length !== 1) throw Error('Unsupported video timing')
  const track = movie.videoTracks[0]
  const edits = track.edits ?? []
  if (edits.length > 1 || edits.some(e => e.media_time < 0 || e.media_rate_integer !== 1 || e.media_rate_fraction !== 0))
    throw Error('Unsupported edit timeline')
  const offset = edits[0]?.media_time ?? 0
  const end = edits[0] ? edits[0].segment_duration / track.movie_timescale : track.duration / track.timescale
  const samples = file.getTrackSamplesInfo(track.id)
  if (!samples.length || samples.length !== track.nb_samples || samples.length > 250000) throw Error('Incomplete video timing')
  const times = samples.map(s => (s.cts - offset) / track.timescale)
    .filter(t => t >= 0 && t < end).sort((a, b) => a - b)
  if (!times.length || times[0] !== 0 || times.some((t, i) => !Number.isFinite(t) || (i > 0 && t <= times[i - 1])))
    throw Error('Ambiguous video timing')
  return times
}

// Optional inspection only: native playback remains streamed by the host. Do not
// buffer an unbounded video just to enable stepping. CORS/host-only schemes, large
// files and unsupported formats retain playback but disclose unavailable timing.
export async function loadVideoTiming(url: string, signal: AbortSignal): Promise<number[]> {
  const limit = 32 * 1024 * 1024
  const response = await fetch(url, { signal })
  if (!response.ok || !response.body) throw Error('Timing inspection unavailable')
  const reader = response.body.getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    if (Number(response.headers.get('content-length')) > limit) throw Error('Video too large for timing inspection')
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > limit) throw Error('Video too large for timing inspection')
      chunks.push(value)
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
  const data = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) { data.set(chunk, offset); offset += chunk.length }
  return mp4FrameTimes(data.buffer)
}

export function adjacentFrame(times: number[], time: number, delta: number): number {
  // currentTime is quantized by browsers; count a boundary within 1us as that frame.
  let low = 0, high = times.length
  while (low < high) {
    const mid = (low + high) >>> 1
    if (times[mid] <= time + 0.000001) low = mid + 1
    else high = mid
  }
  return times[Math.max(0, Math.min(times.length - 1, low - 1 + delta))]
}
