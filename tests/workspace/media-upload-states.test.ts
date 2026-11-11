// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { PluginContext } from '@hermes/plugin-sdk'
import type { MediaScope } from '../../src/cards/next-actions.ts'

vi.mock('../../src/viewers/audio-engine.ts', async importOriginal => {
  const original = await importOriginal<typeof import('../../src/viewers/audio-engine.ts')>()
  return { ...original, fetchAudio: vi.fn(), decodeAudio: vi.fn(), saveAudio: vi.fn(), peaks: () => [0.5],
    AudioPlayer: class {
      playing = false
      load() {} dispose() { this.playing = false } position() { return 0 }
      async play() { this.playing = true } pause() { this.playing = false } setLoop() {}
    } }
})
vi.mock('../../src/viewers/video-timing.ts', async importOriginal => ({
  ...await importOriginal<typeof import('../../src/viewers/video-timing.ts')>(), loadVideoTiming: vi.fn(async () => [0, 0.5, 1]),
}))
import { fetchAudio, decodeAudio, saveAudio } from '../../src/viewers/audio-engine.ts'
import { AudioViewer } from '../../src/viewers/audio-viewer.tsx'
import { VideoViewer } from '../../src/viewers/video-viewer.tsx'
import { UploadDrawer } from '../../src/pages/upload-drawer.tsx'

function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const audioPayload = { name: 'sound.wav', mime: 'audio/wav', bytes: 10, dataUrl: 'data:audio/wav;base64,YQ==' }
const audioProps = { ctx: {} as PluginContext, source: { path: 'sound.wav' }, scope: { profile: '', connection: null } }
function scopeWith(rest = vi.fn(async () => ({}))) {
  return { assert: vi.fn(), current: () => true, watch: () => () => {}, rest } as unknown as MediaScope
}
function state(container: HTMLElement, name: string) { return container.querySelector(`[data-${name}-state]`)?.getAttribute(`data-${name}-state`) }

beforeEach(() => {
  vi.mocked(fetchAudio).mockReset().mockResolvedValue(audioPayload)
  vi.mocked(decodeAudio).mockReset().mockResolvedValue({ duration: 2, sampleRate: 48000 } as AudioBuffer)
  vi.mocked(saveAudio).mockReset().mockResolvedValue(undefined)
  vi.stubGlobal('AudioContext', class {})
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(cleanup)

it('audio exposes loading then ready, with transport playing separate from load state', async () => {
  const pending = deferred<typeof audioPayload>()
  vi.mocked(fetchAudio).mockReturnValueOnce(pending.promise)
  const { container } = render(createElement(AudioViewer, audioProps))
  expect(state(container, 'audio')).toBe('loading')
  expect(screen.getByRole('status').textContent).toContain('Loading StudioTwin audio…')
  expect(container.querySelector('[data-audio-playing]')?.getAttribute('data-audio-playing')).toBe('false')
  await act(async () => pending.resolve(audioPayload))
  expect(state(container, 'audio')).toBe('ready')
  fireEvent.click(screen.getByRole('button', { name: 'Play' }))
  await waitFor(() => expect(container.querySelector('[data-audio-playing]')?.getAttribute('data-audio-playing')).toBe('true'))
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
  await waitFor(() => expect(container.querySelector('[data-audio-playing]')?.getAttribute('data-audio-playing')).toBe('false'))
  expect(state(container, 'audio')).toBe('ready')
})

it('audio conversion remains ready, blocks duplicate conversions, then clears busy', async () => {
  const { container } = render(createElement(AudioViewer, audioProps))
  await screen.findByRole('button', { name: 'Play' })
  const pending = deferred<typeof audioPayload>()
  vi.mocked(fetchAudio).mockReturnValueOnce(pending.promise)
  fireEvent.click(screen.getByRole('button', { name: 'Download WAV' }))
  expect(state(container, 'audio')).toBe('ready')
  expect((screen.getByRole('button', { name: 'Download MP3' }) as HTMLButtonElement).disabled).toBe(true)
  await act(async () => pending.resolve(audioPayload))
  expect(saveAudio).toHaveBeenCalledWith(audioPayload)
  expect((screen.getByRole('button', { name: 'Download MP3' }) as HTMLButtonElement).disabled).toBe(false)
})

it('audio load failure exposes error and a new source restarts loading without stale data', async () => {
  vi.mocked(fetchAudio).mockRejectedValueOnce(Error('decode failed'))
  const { container, rerender } = render(createElement(AudioViewer, { ...audioProps, fallback: createElement('p', null, 'Original player') }))
  await screen.findByText('Original player')
  expect(state(container, 'audio')).toBe('error')
  const pending = deferred<typeof audioPayload>()
  vi.mocked(fetchAudio).mockReturnValueOnce(pending.promise)
  rerender(createElement(AudioViewer, { ...audioProps, source: { path: 'new.wav' } }))
  expect(state(container, 'audio')).toBe('loading')
  await act(async () => pending.resolve(audioPayload))
  expect(state(container, 'audio')).toBe('ready')
})

it('video exposes loading then ready_video and resets loading on source replacement', async () => {
  const first = deferred<string>(), second = deferred<string>(), scope = scopeWith()
  const props = { ctx: {} as PluginContext, scope, source: { path: 'movie.mp4' }, resolveUrl: () => first.promise }
  const { container, rerender } = render(createElement(VideoViewer, props))
  expect(state(container, 'video')).toBe('loading')
  expect(screen.getByRole('status').textContent).toBe('Loading video…')
  await act(async () => first.resolve('https://example.com/one.mp4'))
  expect(state(container, 'video')).toBe('ready_video')
  expect(container.querySelector('video')).not.toBeNull()
  rerender(createElement(VideoViewer, { ...props, source: { path: 'two.mp4' }, resolveUrl: () => second.promise }))
  expect(state(container, 'video')).toBe('loading')
  expect(container.querySelector('video')).toBeNull()
  await act(async () => second.resolve('https://example.com/two.mp4'))
  expect(state(container, 'video')).toBe('ready_video')
})

it('video sequence uses ready_sequence and derives duration from sequence timing', async () => {
  const rest = vi.fn(async () => ({ dataUrl: 'data:image/png;base64,YQ==' }))
  const { container } = render(createElement(VideoViewer, { ctx: {} as PluginContext, scope: scopeWith(rest), source: { path: 'sequence' }, frames: [{ path: 'one.png' }, { path: 'two.png' }], fps: 2 }))
  await screen.findByAltText('Frame 1')
  expect(state(container, 'video')).toBe('ready_sequence')
  expect(screen.getByLabelText('Timeline').getAttribute('max')).toBe('1')
  expect(container.querySelector('video')).toBeNull()
})

it('video resolution and decode failures expose error and preserve fallbacks', async () => {
  const onError = vi.fn(), scope = scopeWith()
  const props = { ctx: {} as PluginContext, scope, source: { path: 'bad.mp4' }, onError, fallback: createElement('p', null, 'Original video') }
  const { container, rerender } = render(createElement(VideoViewer, { ...props, resolveUrl: async () => { throw Error('offline') } }))
  await screen.findByText('Original video')
  expect(state(container, 'video')).toBe('error')
  rerender(createElement(VideoViewer, { ...props, source: { url: 'https://example.com/good.mp4' } }))
  await waitFor(() => expect(container.querySelector('video')).not.toBeNull())
  fireEvent.error(container.querySelector('video')!)
  expect(state(container, 'video')).toBe('error')
  expect(screen.getByText('Original video')).toBeDefined()
  expect(onError).toHaveBeenCalledTimes(2)
})

function uploadFile(name = 'reference.png') {
  const file = new File(['bytes'], name, { type: 'image/png' })
  Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode('bytes').buffer })
  return file
}
it.each([false, true])('upload exposes idle, uploading filename/destination, then succeeded (cloud=%s)', async cloud => {
  const pending = deferred<Record<string, unknown>>()
  const rest = vi.fn(() => pending.promise), onUploaded = vi.fn()
  const { container } = render(createElement(UploadDrawer, { scope: scopeWith(rest), configured: true, onUploaded }))
  expect(state(container, 'upload')).toBe('idle')
  if (cloud) fireEvent.click(screen.getByRole('checkbox', { name: 'Cloud upload' }))
  fireEvent.change(screen.getByLabelText('Reference file'), { target: { files: [uploadFile()] } })
  expect(state(container, 'upload')).toBe('uploading')
  const status = screen.getByRole('status').textContent!
  expect(status).toContain('Uploading reference…')
  expect(status).toContain('reference.png')
  expect(status.toLowerCase()).toContain(cloud ? 'cloud' : 'local')
  expect((screen.getByLabelText('Reference file') as HTMLInputElement).disabled).toBe(true)
  await waitFor(() => expect(rest).toHaveBeenCalledWith('/upload', expect.objectContaining({ method: 'POST', body: expect.objectContaining({ filename: 'reference.png', cloud }) })))
  await act(async () => pending.resolve({ path: '/staged/reference.png', uuid: '11111111-1111-4111-8111-111111111111' }))
  expect(state(container, 'upload')).toBe('succeeded')
  expect(screen.queryByRole('status')).toBeNull()
  expect(onUploaded).toHaveBeenCalledTimes(1)
})

it('upload failure clears prior success and supports retry without stale result', async () => {
  const rest = vi.fn().mockResolvedValueOnce({ path: '/staged/reference.png' }).mockRejectedValueOnce(Error('secret backend error')).mockResolvedValueOnce({ path: '/staged/retry.png' })
  const { container } = render(createElement(UploadDrawer, { scope: scopeWith(rest), configured: true }))
  const choose = () => fireEvent.change(screen.getByLabelText('Reference file'), { target: { files: [uploadFile()] } })
  choose()
  await screen.findByText('/staged/reference.png')
  choose()
  await screen.findByRole('alert')
  expect(state(container, 'upload')).toBe('failed')
  expect(screen.queryByText('/staged/reference.png')).toBeNull()
  expect(screen.getByRole('alert').textContent).not.toContain('secret')
  choose()
  await screen.findByText('/staged/retry.png')
  expect(state(container, 'upload')).toBe('succeeded')
  expect(screen.queryByRole('alert')).toBeNull()
})
