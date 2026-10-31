// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { chromium } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createElement } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { PluginContext } from '@hermes/plugin-sdk'

const owner = vi.hoisted(() => ({ profile: 'alpha', connection: 'local', listeners: new Set<() => void>(), submit: vi.fn((_session: string, _text: string) => true) }))
vi.mock('@hermes/plugin-sdk', async () => {
  const { createElement } = await import('react')
  return {
    host: { state: {
      profile: { get: () => owner.profile, subscribe: (fn: () => void) => { owner.listeners.add(fn); return () => owner.listeners.delete(fn) } },
      connectionId: { get: () => owner.connection, subscribe: (fn: () => void) => { owner.listeners.add(fn); return () => owner.listeners.delete(fn) } }
    }, composer: { submit: owner.submit }, notify: vi.fn() },
    TOOL_MEDIA_RENDERER_AREA: 'transcript.toolMedia', TRANSCRIPT_DIRECTIVE_AREA: 'transcript.directives',
    Button: ({ size, variant, ...props }: Record<string, unknown>) => createElement('button', props),
    Badge: (props: Record<string, unknown>) => createElement('span', props)
  }
})
import { AudioCard, DirectiveAudioCard, ToolMediaAudioCard, registerAudioCards } from '../../src/cards/audio-card.tsx'
import { AudioPlayer, peaks, currentScope, fetchAudio, nextActions, submitNext } from '../../src/viewers/audio-engine.ts'

const fixture = (name: string) => readFileSync(`${process.cwd()}/tests/fixtures/media/audio/${name}`)
const payload = () => ({ name: 'tone.wav', mime: 'audio/wav', bytes: fixture('tone-48k.wav').length, dataUrl: `data:audio/wav;base64,${fixture('tone-48k.wav').toString('base64')}` })
// Test Web Audio adapter: actual fixture decoding uses local ffmpeg, not a fabricated waveform.
// Browser decodeAudioData / canvas are separately exercised by the browser smoke probe.
function pcm(bytes: ArrayBuffer): AudioBuffer {
  const raw = execFileSync('ffmpeg', ['-v', 'error', '-i', 'pipe:0', '-f', 'f32le', '-ac', '1', '-ar', '48000', 'pipe:1'], { input: Buffer.from(bytes), stdio: ['pipe', 'pipe', 'pipe'] })
  const data = new Float32Array(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength))
  return { length: data.length, duration: data.length / 48000, sampleRate: 48000, numberOfChannels: 1, getChannelData: () => data } as unknown as AudioBuffer
}
class TestContext {
  currentTime = 0
  destination = {}
  nodes: Array<Record<string, any>> = []
  decodeAudioData = vi.fn(async (bytes: ArrayBuffer) => pcm(bytes))
  resume = vi.fn(async () => {})
  close = vi.fn(async () => {})
  createBufferSource() {
    const node = { loop: false, buffer: null, onended: null, connect: vi.fn(), disconnect: vi.fn(), start: vi.fn(), stop: vi.fn() }
    this.nodes.push(node); return node
  }
}
function context(rest = vi.fn(async () => payload())) { return { rest, register: vi.fn(() => vi.fn()), onDispose: vi.fn() } as unknown as PluginContext }
function switchScope(profile = 'beta', connection = 'remote') { owner.profile = profile; owner.connection = connection; owner.listeners.forEach(fn => fn()) }

beforeEach(() => {
  owner.profile = 'alpha'; owner.connection = 'local'; owner.submit.mockClear()
  vi.stubGlobal('AudioContext', TestContext)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ clearRect: vi.fn(), fillRect: vi.fn(), setTransform: vi.fn() } as any)
})
afterEach(() => { cleanup(); owner.listeners.clear() })

describe('waveform and gapless playback', () => {
  it.each(['tone-48k.wav', 'tone-44k.mp3'])('extracts measured peaks from real %s bytes', name => {
    const bytes = fixture(name)
    const buffer = pcm(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength))
    const wave = peaks(buffer, 63)
    expect(buffer.duration).toBeCloseTo(name.endsWith('.mp3') ? .3396 : .25, 3) // MP3 fixture disables Xing padding metadata.
    expect(wave).toHaveLength(63); expect(Math.max(...wave)).toBeGreaterThan(.1)
    expect(wave.every(n => n >= 0 && n <= 1)).toBe(true)
  })
  it('does not drop single-sample transients, the last sample, or a short channel', () => {
    const data = new Float32Array(11); data[10] = .9; data[1] = .8
    const buffer = { length: 11, numberOfChannels: 1, getChannelData: () => data } as unknown as AudioBuffer
    expect(peaks(buffer, 3)).toEqual([expect.closeTo(.8), 0, expect.closeTo(.9)])
    expect(peaks(buffer, 20)).toHaveLength(20)
    expect(() => peaks(buffer, 0)).toThrow()
  })
  it('cancels pending AudioContext.resume playback when disposed during a switch/unmount', async () => {
    const ctx = new TestContext()
    let resume!: () => void
    ctx.resume = vi.fn(() => new Promise<void>(resolve => { resume = resolve }))
    const player = new AudioPlayer(ctx as unknown as AudioContext)
    const pending = player.play(pcm(fixture('tone-48k.wav').buffer.slice(0)), true)
    player.dispose(); resume(); await pending
    expect(ctx.nodes).toHaveLength(0)
    expect(ctx.close).toHaveBeenCalledTimes(1)
    player.dispose(); expect(ctx.close).toHaveBeenCalledTimes(1)
  })
  it('loops with an AudioBufferSourceNode, toggles without restarting, seeks, pauses and disposes', async () => {
    const ctx = new TestContext(); const player = new AudioPlayer(ctx as unknown as AudioContext)
    const buffer = pcm(fixture('tone-48k.wav').buffer.slice(0))
    await player.play(buffer, true, .1)
    expect(ctx.nodes[0].loop).toBe(true)
    ctx.currentTime = .5
    expect(player.position()).toBeCloseTo(.1)
    player.setLoop(false); expect(ctx.nodes).toHaveLength(1); expect(ctx.nodes[0].loop).toBe(false)
    player.pause(); expect(ctx.nodes[0].stop).toHaveBeenCalled()
    await player.play(buffer, false, .05); expect(ctx.nodes[1].start).toHaveBeenCalledWith(0, .05)
    player.dispose(); expect(ctx.nodes[1].disconnect).toHaveBeenCalled(); expect(ctx.close).toHaveBeenCalled()
  })
})

describe('scope and Next actions', () => {
  it('converts through /file for path or asset and refuses an old card after either scope switch', async () => {
    const ctx = context(); const scope = currentScope()
    await fetchAudio(ctx, { path: '/cache/sfx one.wav' }, scope, 'flac')
    expect(ctx.rest).toHaveBeenCalledWith('/file?path=%2Fcache%2Fsfx+one.wav&format=flac', expect.anything())
    await fetchAudio(ctx, { asset: '11111111-1111-4111-8111-111111111111' }, scope, 'mp3')
    switchScope('alpha', 'remote')
    await expect(fetchAudio(ctx, { path: '/cache/sfx.wav' }, scope)).rejects.toThrow(/scope/i)
    expect(ctx.rest).toHaveBeenCalledTimes(2)
  })
  it('discards an in-flight response after a profile switch, with no fallback request', async () => {
    let resolve!: (v: unknown) => void
    const ctx = context(vi.fn(() => new Promise(r => { resolve = r })) as any)
    const pending = fetchAudio(ctx, { path: '/cache/a.wav' }, currentScope(), 'ogg')
    switchScope(); resolve(payload())
    await expect(pending).rejects.toThrow(/scope/i); expect(ctx.rest).toHaveBeenCalledTimes(1)
  })
  it('quotes zero-credit local operations and honest input-dependent generation costs, targeting only the owner chat', () => {
    const actions = nextActions({ path: '/cache/a "x".wav' }, 'wind')
    expect(actions.map(a => a.id)).toEqual(['loopcheck', 'loopfix', 'normalize', 'variation'])
    expect(actions[0].message).toContain('0 credits'); expect(actions[1].message).toContain('sfx_tool.py')
    expect(actions[2].message).toContain('--loudness -16')
    expect(actions[3].message).toContain('studiotwin_estimate_cost'); expect(actions[3].cost).toMatch(/input-dependent/)
    const scope = currentScope()
    expect(submitNext(scope, 'original-chat', actions[0])).toBe(true)
    expect(owner.submit).toHaveBeenCalledWith('original-chat', actions[0].message)
    switchScope(); expect(submitNext(scope, 'original-chat', actions[3])).toBe(false)
    expect(owner.submit).toHaveBeenCalledTimes(1)
  })
})

describe('rendered audio card', () => {
  it.each(['mouse', 'keyboard'])('honors cold %s seek visibly and on first playback without autoplay', async input => {
    const create = vi.spyOn(TestContext.prototype, 'createBufferSource')
    render(createElement(AudioCard, { ctx: context(), source: { path: '/cache/a.wav' }, sessionId: 's' }))
    await screen.findByRole('button', { name: 'Play' })
    const wave = screen.getByRole('slider')
    expect(create).not.toHaveBeenCalled()
    if (input === 'mouse') {
      vi.spyOn(wave, 'getBoundingClientRect').mockReturnValue({ left: 10, width: 200 } as DOMRect)
      fireEvent.click(wave, { clientX: 110 })
    } else fireEvent.keyDown(wave, { key: 'ArrowRight' })
    const percent = input === 'mouse' ? 50 : 5
    const offset = .25 * percent / 100
    await waitFor(() => expect(wave.getAttribute('aria-valuenow')).toBe(String(percent)))
    expect(screen.getByText(`${offset.toFixed(2)} / 0.25 s`)).toBeTruthy()
    expect(create).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Play' }))
    await screen.findByRole('button', { name: 'Pause' })
    expect(create.mock.results[0].value.start).toHaveBeenCalledWith(0, offset)
  })
  it('loads, draws a theme canvas, exposes badges, audition and format downloads', async () => {
    render(createElement(AudioCard, { ctx: context(), source: { path: '/cache/a.wav' }, sessionId: 's', fallback: 'fallback' }))
    await screen.findByRole('button', { name: 'Play' })
    expect(screen.getByText('48000 Hz')).toBeTruthy()
    const wave = screen.getByRole('slider', { name: /Waveform/ })
    expect(wave.tagName).toBe('CANVAS')
    fireEvent.click(screen.getByRole('button', { name: 'Loop audition' }))
    expect(screen.getByRole('button', { name: 'Loop audition' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: 'Play' }))
    await screen.findByRole('button', { name: 'Pause' })
    expect(screen.getByRole('button', { name: 'Download FLAC' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Check Loop Seam/ }))
    expect(owner.submit.mock.calls[0][0]).toBe('s')
  })
  it.each(['fetch', 'decode'])('renders props.fallback on %s error', async kind => {
    const rest = kind === 'fetch' ? vi.fn(async () => { throw Error('fetch') }) : vi.fn(async () => ({ ...payload(), dataUrl: 'data:audio/wav;base64,YmFk' }))
    render(createElement(AudioCard, { ctx: context(rest), source: { path: '/cache/a.wav' }, sessionId: 's', fallback: createElement('p', null, 'Built-in audio') }))
    await screen.findByText('Built-in audio')
  })
  it('stops and renders fallback when its owning scope changes', async () => {
    const ctx = context()
    render(createElement(AudioCard, { ctx, source: { path: '/cache/a.wav' }, sessionId: 's', fallback: 'Built-in audio' }))
    await screen.findByRole('button', { name: 'Play' })
    switchScope(); await screen.findByText('Built-in audio')
    expect(ctx.rest).toHaveBeenCalledTimes(1)
  })
  it('loads an asset UUID directive through the backend and not local fetch', async () => {
    const ctx = context()
    render(createElement(DirectiveAudioCard, { ctx, directive: { attrs: { asset: '11111111-1111-4111-8111-111111111111' }, sessionId: 'directive-owner', streaming: false, source: '::studiotwin-audio' } }))
    await screen.findByRole('button', { name: 'Play' })
    expect(ctx.rest).toHaveBeenCalledWith('/file?asset=11111111-1111-4111-8111-111111111111&format=original', expect.anything())
  })
  it('renders the canonical tool-media card, but never claims terminal-produced audio', async () => {
    const media = { toolName: 'mcp__studiotwin__text_to_sound_effect', toolCallId: 'c', args: { prompt: 'wind' }, result: '{"success":true}', sessionId: 'owner', fallback: 'Built-in audio', file: { path: '/cache/a.wav', name: 'a.wav', kind: 'audio' as const, mime: 'audio/wav', resolveUrl: vi.fn() } }
    const view = render(createElement(ToolMediaAudioCard, { ctx: context(), media }))
    await screen.findByRole('button', { name: 'Play' })
    view.rerender(createElement(ToolMediaAudioCard, { ctx: context(), media: { ...media, toolName: 'terminal' } }))
    await screen.findByText('Built-in audio'); expect(media.file.resolveUrl).not.toHaveBeenCalled()
  })
  it('never saves an in-flight conversion after the originating profile changes', async () => {
    let resolve!: (value: unknown) => void
    const rest = vi.fn().mockResolvedValueOnce(payload()).mockImplementationOnce(() => new Promise(r => { resolve = r }))
    const create = vi.fn(); vi.stubGlobal('URL', Object.assign(class {}, { createObjectURL: create, revokeObjectURL: vi.fn() }))
    render(createElement(AudioCard, { ctx: context(rest), source: { path: '/cache/a.wav' }, sessionId: 's', fallback: 'Built-in audio' }))
    await screen.findByRole('button', { name: 'Play' })
    fireEvent.click(screen.getByRole('button', { name: 'Download FLAC' }))
    expect(rest).toHaveBeenCalledTimes(2)
    switchScope(); resolve(payload())
    await screen.findByText('Built-in audio')
    expect(create).not.toHaveBeenCalled()
    expect(rest).toHaveBeenCalledTimes(2)
  })
  it('registers only package sound tools and studiotwin-audio directives', () => {
    const ctx = context(); registerAudioCards(ctx)
    expect(ctx.register).toHaveBeenCalledTimes(2)
    const registrations = vi.mocked(ctx.register).mock.calls.map(([c]) => c)
    expect(registrations[0].area).toBe('transcript.toolMedia')
    expect((registrations[0].data as any).tools).toContain('mcp__studiotwin__text_to_sound_effect')
    expect((registrations[0].data as any).tools).not.toContain('terminal')
    expect((registrations[1].data as any).name).toBe('studiotwin-audio')
  })
  it('uses only Hermes theme variables for colors and observes canvas resizing', () => {
    const source = readFileSync(`${process.cwd()}/src/viewers/audio-viewer.tsx`, 'utf8')
    expect(source).toContain('ResizeObserver'); expect(source).toContain("getPropertyValue('--ui-accent')")
    expect(source).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|\b(?:black|white)\b/)
  })
})

const systemChrome = '/opt/google/chrome/chrome'
it.skipIf(!existsSync(systemChrome) && !existsSync(chromium.executablePath()))('Chromium: real WAV/MP3 decode, canvas resize/theme, audition, seek, download and scope invalidation', async () => {
  const root = process.cwd()
  // esbuild requires TextEncoder and Uint8Array from the same realm; jsdom replaces only the latter.
  vi.stubGlobal('Uint8Array', new TextEncoder().encode('').constructor)
  const { build } = await import('esbuild')
  const compiled = await build({
    stdin: { resolveDir: root, loader: 'tsx', contents: `
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {AudioCard} from './src/cards/audio-card.tsx';
      import {decodeAudio,peaks} from './src/viewers/audio-engine.ts';
      window.decoded = []; window.starts = [];
      const start = AudioBufferSourceNode.prototype.start;
      AudioBufferSourceNode.prototype.start = function(...args) { window.starts.push(args); return start.apply(this,args) };
      const a = new AudioContext();
      for (const url of window.urls) {
        const b = await decodeAudio(url,a); window.decoded.push({duration:b.duration, rate:b.sampleRate, peak:Math.max(...peaks(b))});
      }
      await a.close();
      const payload = {name:'tone.wav',mime:'audio/wav',bytes:48044,dataUrl:window.urls[0]};
      const ctx = {rest:async path => {window.requests.push(path);return payload}};
      createRoot(document.getElementById('root')).render(<AudioCard ctx={ctx} source={{path:'/cache/tone.wav'}} sessionId='owner-chat' fallback='Built-in audio'/>);
    ` }, bundle: true, write: false, format: 'esm', jsx: 'automatic', plugins: [{
      name: 'host-ui-shim', setup(builder) {
        builder.onResolve({ filter: /^@hermes\/plugin-sdk$/ }, () => ({ path: 'sdk', namespace: 'host-shim' }))
        builder.onLoad({ filter: /.*/, namespace: 'host-shim' }, () => ({ resolveDir: root, loader: 'js', contents: `
          import React from 'react';
          export const TOOL_MEDIA_RENDERER_AREA='transcript.toolMedia', TRANSCRIPT_DIRECTIVE_AREA='transcript.directives';
          export const Button=({size,variant,...p})=>React.createElement('button',p);
          export const Badge=p=>React.createElement('span',p);
          const listeners=new Set();
          window.switchScope=()=>{window.profile='beta';listeners.forEach(fn=>fn())};
          export const host={state:{profile:{get:()=>window.profile,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)}},connectionId:{get:()=> 'local',subscribe:()=>()=>{}}},composer:{submit:(session,text)=>{window.messages.push({session,text});return true}},notify:()=>{}};
        ` }))
      }
    }] })
  const browser = await chromium.launch({ executablePath: existsSync(systemChrome) ? systemChrome : undefined, headless: true, args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'] })
  try {
    const page = await browser.newPage({ viewport: { width: 800, height: 520 } })
    const errors: string[] = []; page.on('pageerror', error => errors.push(error.message))
    await page.setContent('<style>:root{--ui-accent:#8ab4f8;--ui-text-tertiary:#888;--ui-text-primary:#eee;--ui-text-secondary:#ccc;--ui-stroke-secondary:#444;--ui-bg-card:#242424;--ui-red:#f88}body{background:#181818;font:14px system-ui}button,summary{cursor:pointer}button{padding:6px;margin:2px}</style><div id="root"></div>')
    await page.evaluate(urls => Object.assign(window, { urls, profile: 'alpha', requests: [], messages: [], decoded: [] }),
      ['tone-48k.wav', 'tone-44k.mp3'].map(name => `data:audio/${name.endsWith('.mp3') ? 'mpeg' : 'wav'};base64,${fixture(name).toString('base64')}`))
    await page.addScriptTag({ type: 'module', content: compiled.outputFiles[0].text })
    await page.getByRole('button', { name: 'Play', exact: true }).waitFor()
    const decoded = await page.evaluate(() => (window as any).decoded)
    expect(decoded).toHaveLength(2)
    expect(decoded[0].duration).toBeCloseTo(.25, 3)
    expect(decoded[1].duration).toBeCloseTo(13 * 1152 / 44100, 3)
    expect(decoded.every((d: { peak: number }) => d.peak > .1)).toBe(true)
    const canvas = page.getByRole('slider')
    expect(await canvas.evaluate((c: HTMLCanvasElement) => c.width)).toBeGreaterThan(500)
    expect(await canvas.evaluate((c: HTMLCanvasElement) => Array.from(c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data).some(n => n !== 0))).toBe(true)
    // Both gestures run on a decoded, never-played card. Observe native start offsets too.
    expect(await page.evaluate(() => (window as any).starts)).toEqual([])
    await canvas.focus(); await page.keyboard.press('ArrowRight')
    await page.waitForFunction(() => document.querySelector('canvas')!.getAttribute('aria-valuenow') === '5')
    await page.getByText('0.01 / 0.25 s', { exact: true }).waitFor()
    const bounds = (await canvas.boundingBox())!
    await canvas.click({ position: { x: bounds.width / 2, y: 32 } })
    await page.waitForFunction(() => document.querySelector('canvas')!.getAttribute('aria-valuenow') === '50')
    expect(await page.evaluate(() => (window as any).starts)).toEqual([])
    await page.getByRole('button', { name: 'Loop audition' }).click()
    await page.getByRole('button', { name: 'Play', exact: true }).click()
    await page.getByRole('button', { name: 'Pause', exact: true }).waitFor()
    const starts = await page.evaluate(() => (window as any).starts)
    expect(starts).toHaveLength(1)
    expect(starts[0][0]).toBe(0); expect(starts[0][1]).toBeCloseTo(.125, 4)
    await canvas.click({ position: { x: 100, y: 30 } })
    await page.getByRole('button', { name: 'Pause', exact: true }).click()
    await canvas.focus(); await page.keyboard.press('Home')
    expect(await canvas.getAttribute('aria-valuenow')).toBe('0')
    await page.getByText('Download / Convert', { exact: true }).click()
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Download FLAC' }).click()
    expect((await download).suggestedFilename()).toBe('tone.wav') // host shim returns the fixture, not a fake conversion
    expect(await page.evaluate(() => (window as any).requests)).toContain('/file?path=%2Fcache%2Ftone.wav&format=flac')
    await page.getByText('Next', { exact: true }).click()
    await page.getByRole('button', { name: /Check Loop Seam/ }).click()
    expect((await page.evaluate(() => (window as any).messages))[0].session).toBe('owner-chat')
    if (process.env.V03_SCREENSHOT) await page.screenshot({ path: process.env.V03_SCREENSHOT.replace('.png', '-dark.png'), fullPage: true })
    await page.setViewportSize({ width: 400, height: 600 })
    await page.waitForFunction(() => document.querySelector('canvas')!.width < 400)
    await page.evaluate(() => {
      const vars = { '--ui-text-tertiary': '#555555', '--ui-bg-card': '#ffffff', '--ui-text-primary': '#222222', '--ui-text-secondary': '#444444', '--ui-stroke-secondary': '#cccccc' }
      Object.entries(vars).forEach(([key, value]) => document.documentElement.style.setProperty(key, value))
      document.body.style.background = '#f5f5f5'
    })
    await page.waitForFunction(() => {
      const c = document.querySelector('canvas')!, pixels = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data
      for (let i=0;i<pixels.length;i+=4) if(pixels[i]===85 && pixels[i+3]===255) return true
      return false
    })
    if (process.env.V03_SCREENSHOT) await page.screenshot({ path: process.env.V03_SCREENSHOT, fullPage: true })
    await page.evaluate(() => (window as any).switchScope())
    await page.getByText('Built-in audio', { exact: true }).waitFor()
    expect(errors).toEqual([])
  } finally { await browser.close() }
})
