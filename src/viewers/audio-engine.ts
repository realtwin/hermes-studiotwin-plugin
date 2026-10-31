// Adapted from Nous Research elevenlabs-sound-effects src/audio.ts + sound.ts (MIT).
// Copyright (c) 2026 Nous Research. No provider credentials or local filesystem access in the UI.
import { host, type PluginContext } from '@hermes/plugin-sdk'

export type AudioSource = { path: string; asset?: never } | { asset: string; path?: never }
export interface AudioPayload { name: string; mime: string; bytes: number; dataUrl: string }
export const AUDIO_FORMATS = ['original', 'wav', 'mp3', 'ogg', 'flac'] as const
export type AudioFormat = typeof AUDIO_FORMATS[number]
export interface Scope { readonly profile: string; readonly connection: string | null }
export const currentScope = (): Scope => Object.freeze({
  profile: host.state?.profile?.get() ?? '', connection: host.state?.connectionId?.get() ?? null
})
export const scopeMatches = (scope: Scope) => {
  const now = currentScope()
  return now.profile === scope.profile && now.connection === scope.connection
}
export function assertScope(scope: Scope): void {
  if (!scopeMatches(scope)) throw Error('Audio card belongs to another profile/connection scope')
}
export function onScopeChange(fn: () => void): () => void {
  const offs = [host.state?.profile?.subscribe(fn), host.state?.connectionId?.subscribe(fn)]
  return () => offs.forEach(off => off?.())
}
export function fileQuery(source: AudioSource, format: AudioFormat): string {
  if (!AUDIO_FORMATS.includes(format)) throw Error('Unsupported audio format')
  if (Boolean(source.path) === Boolean(source.asset)) throw Error('Exactly one audio path or asset is required')
  if (source.asset && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(source.asset)) throw Error('Invalid asset UUID')
  const query = new URLSearchParams(source.path ? { path: source.path } : { asset: source.asset! })
  query.set('format', format)
  return `/file?${query}`
}
export async function fetchAudio(ctx: PluginContext, source: AudioSource, scope: Scope, format: AudioFormat = 'original'): Promise<AudioPayload> {
  assertScope(scope) // Before ctx.rest: it resolves the current backend, not a bound transport.
  const response = await ctx.rest<AudioPayload>(fileQuery(source, format), { timeoutMs: 60_000 })
  assertScope(scope) // No retry or second-format fallback that could retarget after the await.
  if (!response || !/^data:audio\/[^;,]+;base64,/.test(response.dataUrl) || !Number.isFinite(response.bytes)) throw Error('Invalid audio response')
  return response
}
export function audioBytes(dataUrl: string): ArrayBuffer {
  const match = /^data:audio\/[^;,]+;base64,([A-Za-z0-9+/=\s]+)$/.exec(dataUrl)
  if (!match) throw Error('Audio must be an audio data URL')
  const raw = atob(match[1])
  return Uint8Array.from(raw, c => c.charCodeAt(0)).buffer
}
export async function decodeAudio(dataUrl: string, context: AudioContext): Promise<AudioBuffer> {
  const buffer = await context.decodeAudioData(audioBytes(dataUrl))
  if (!(buffer.duration > 0)) throw Error('Empty audio')
  return buffer
}
/** Max |sample| across ALL samples and channels. Proportional buckets retain the remainder. */
export function peaks(buffer: AudioBuffer, buckets = 120): number[] {
  if (!Number.isInteger(buckets) || buckets < 1 || buckets > 8192) throw Error('Invalid waveform bucket count')
  const out = new Array<number>(buckets).fill(0)
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const data = buffer.getChannelData(c)
    for (let i = 0; i < data.length; i++) {
      const bucket = Math.min(buckets - 1, Math.floor(i * buckets / data.length))
      if (Number.isFinite(data[i])) out[bucket] = Math.max(out[bucket], Math.min(1, Math.abs(data[i])))
    }
  }
  return out
}
/** AudioBufferSourceNode.loop, not HTML audio.loop: no decoder restart/gap at the seam. */
export class AudioPlayer {
  private source: AudioBufferSourceNode | null = null
  private buffer: AudioBuffer | null = null
  private startedAt = 0
  private offset = 0
  private epoch = 0
  private disposed = false
  loop = false
  constructor(readonly context: AudioContext) {}
  get playing() { return this.source !== null }
  position(): number {
    if (!this.buffer) return 0
    const t = this.offset + (this.source ? this.context.currentTime - this.startedAt : 0)
    return this.loop ? t % this.buffer.duration : Math.min(t, this.buffer.duration)
  }
  async play(buffer: AudioBuffer, loop = this.loop, from = this.offset): Promise<void> {
    const epoch = ++this.epoch
    await this.context.resume()
    if (this.disposed || epoch !== this.epoch) return
    this.stopSource()
    this.buffer = buffer; this.loop = loop
    const node = this.context.createBufferSource()
    node.buffer = buffer; node.loop = loop; node.connect(this.context.destination)
    this.offset = Math.max(0, from >= buffer.duration ? 0 : from)
    this.startedAt = this.context.currentTime
    node.onended = () => {
      if (this.source === node) { this.source = null; this.offset = 0; node.disconnect() }
    }
    this.source = node
    node.start(0, this.offset)
  }
  pause(): void { this.offset = this.position(); ++this.epoch; this.stopSource() }
  setLoop(loop: boolean): void {
    this.offset = this.position(); this.startedAt = this.context.currentTime
    this.loop = loop
    if (this.source) this.source.loop = loop // In-place toggle preserves the running audition.
  }
  seek(seconds: number): Promise<void> {
    if (!this.buffer) return Promise.resolve()
    if (this.playing) return this.play(this.buffer, this.loop, seconds)
    this.offset = Math.max(0, Math.min(seconds, this.buffer.duration)); return Promise.resolve()
  }
  private stopSource() {
    const node = this.source; this.source = null
    if (node) { node.onended = null; try { node.stop() } finally { node.disconnect() } }
  }
  dispose() { if (this.disposed) return; this.disposed = true; ++this.epoch; this.stopSource(); void this.context.close() }
}
export interface NextAction { id: string; label: string; cost: string; message: string }
export function nextActions(source: AudioSource, prompt = ''): NextAction[] {
  const ref = source.path ? JSON.stringify(source.path) : `StudioTwin asset ${source.asset}`
  const local = (id: string, label: string, command: string): NextAction => ({
    id, label, cost: '0 credits · local ffmpeg',
    message: `For ${ref}, run the bundled skills/studiotwin/scripts/sfx_tool.py ${command}. ` +
      'Cost: 0 credits (local processing). Resolve/download this existing asset first if needed; never regenerate it. ' +
      'Use a new output path, never overwrite the input. Report measured results and output paths.'
  })
  return [
    local('loopcheck', 'Check Loop Seam', 'loopcheck <local-input>'),
    local('loopfix', 'Crossfade Loop (loopfix)', 'loopfix <local-input> --out <new-loop.wav> --crossfade-ms 20'),
    local('normalize', 'Normalize Loudness (-16 LUFS)', 'process <local-input> --out <new-normalized.wav> --loudness -16'),
    { id: 'variation', label: 'Generate Variation', cost: 'input-dependent credits · estimate first',
      message: `Generate one variation of ${ref}${prompt ? ` (original prompt: ${JSON.stringify(prompt)})` : ''} using StudioTwin text-to-sound-effect. ` +
        'Cost: input-dependent credits, currently unknown. Read the live tool schema, estimate the exact inputs with ' +
        'studiotwin_estimate_cost, and ask me to approve the cost before submitting once. Do not automatically retry.' }
  ]
}
export function submitNext(scope: Scope, sessionId: string | null | undefined, action: NextAction): boolean {
  // No active-composer fallback on older hosts: that could target a different chat.
  return scopeMatches(scope) && sessionId !== undefined && Boolean(host.composer?.submit(sessionId ?? 'new', action.message))
}
export async function saveAudio(payload: AudioPayload): Promise<void> {
  const blob = new Blob([audioBytes(payload.dataUrl)], { type: payload.mime })
  const url = URL.createObjectURL(blob)
  const link = Object.assign(document.createElement('a'), { href: url, download: payload.name.split(/[\\/]/).pop() || 'sound' })
  try { link.click() } finally { URL.revokeObjectURL(url) }
}
