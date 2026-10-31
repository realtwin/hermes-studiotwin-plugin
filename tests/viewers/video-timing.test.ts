import { readFileSync } from 'node:fs'
import { describe, expect, it, vi, afterEach } from 'vitest'
import { adjacentFrame, loadVideoTiming, mp4FrameTimes } from '../../src/viewers/video-timing.ts'

function fixture(name: string) {
  const bytes = readFileSync(name === 'testsrc-32.mp4' ? `tests/fixtures/media/video/${name}` : `tests/fixtures/video-timing/${name}`)
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)
}
afterEach(() => vi.unstubAllGlobals())
describe('source presentation timing', () => {
  it.each([[6, 'testsrc-32.mp4'], [10, 'testsrc-32-10fps.mp4']] as const)('reads %i fps from sample timestamps and edit offsets, without caller fps', (fps, name) => {
    const times = mp4FrameTimes(fixture(name))
    expect(times).toHaveLength(fps)
    times.forEach((time, i) => expect(time).toBeCloseTo(i / fps, 8))
  })
  it('steps variable presentation intervals, clamps ends, and reverses from a scrubbed position', () => {
    const times = [0, 0.04, 0.14, 0.19]
    expect(adjacentFrame(times, 0, -1)).toBe(0)
    expect(adjacentFrame(times, 0.04, 1)).toBe(0.14)
    expect(adjacentFrame(times, 0.15, -1)).toBe(0.04)
    expect(adjacentFrame(times, 0.19, 1)).toBe(0.19)
    expect(adjacentFrame([0, 1 / 6, 2 / 6], 0.166666, 1)).toBe(2 / 6)
  })
  it('does not invent timing for an unsupported container', () => {
    expect(() => mp4FrameTimes(new ArrayBuffer(0))).toThrow()
  })
  it('bounds optional timing downloads even without content-length and cancels the reader', async () => {
    const cancel = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async () => new Response(new ReadableStream({
      start(c) { c.enqueue(new Uint8Array(32 * 1024 * 1024 + 1)) }, cancel,
    }))))
    await expect(loadVideoTiming('https://example.test/video', new AbortController().signal)).rejects.toThrow('too large')
    expect(cancel).toHaveBeenCalled()
  })
  it('rejects HTTP and advertised oversize responses without reading the body', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 403 })))
    await expect(loadVideoTiming('/video', new AbortController().signal)).rejects.toThrow('unavailable')
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { headers: { 'content-length': String(33 * 1024 * 1024) } })))
    await expect(loadVideoTiming('/video', new AbortController().signal)).rejects.toThrow('too large')
  })
})
