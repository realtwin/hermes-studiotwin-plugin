// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { readFileSync, existsSync } from 'node:fs'
import { Buffer as NodeBuffer } from 'node:buffer'
import { chromium } from '@playwright/test'
import type { PluginContext } from '@hermes/plugin-sdk'
const owner = vi.hoisted(() => ({
  profile: 'alpha',
  connection: null as string | null,
  listeners: new Set<() => void>(),
  submit: vi.fn((_session: string, _message: string) => true),
}))
vi.mock('@hermes/plugin-sdk', async () => {
  const query = await import('@tanstack/react-query')
  const { createElement } = await import('react')
  return {
    ...query,
    Button: ({ size, variant, ...props }: Record<string, unknown>) => createElement('button', props),
    host: {
      state: {
        profile: {
          get: () => owner.profile,
          subscribe: (fn: () => void) => {
            owner.listeners.add(fn)
            return () => owner.listeners.delete(fn)
          },
        },
        connectionId: {
          get: () => owner.connection,
          subscribe: (fn: () => void) => {
            owner.listeners.add(fn)
            return () => owner.listeners.delete(fn)
          },
        },
      },
      composer: { submit: owner.submit },
      notify: vi.fn(),
    },
    TOOL_MEDIA_RENDERER_AREA: 'transcript.toolMedia',
    TRANSCRIPT_DIRECTIVE_AREA: 'transcript.directives',
  }
})
import { ImageCard, registerImageCards, conceptImages } from '../../src/cards/image-card.tsx'
import { VideoCard, registerVideoCards } from '../../src/cards/video-card.tsx'
import { TaskCard, registerTaskCards, jobStatus } from '../../src/cards/task-card.tsx'
import { imageActions, hostPlaybackUrl, deliveryUrl, mediaQuery } from '../../src/cards/next-actions.ts'
const png = `data:image/png;base64,${readFileSync('tests/fixtures/media/image/concept-64.png').toString('base64')}`
const file = { dataUrl: png, name: 'concept.png', bytes: 123 }
const ctx = (rest = vi.fn(async () => file)) => ({ rest, register: vi.fn(() => vi.fn()) }) as unknown as PluginContext
function switchScope() {
  owner.profile = 'beta'
  owner.listeners.forEach((fn) => fn())
}
function mountTask(context: PluginContext, extra = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    createElement(
      QueryClientProvider,
      { client },
      createElement(TaskCard, {
        ctx: context,
        id: 'job-1',
        sessionId: 'original',
        pollInterval: 20,
        fallback: 'Task fallback',
        ...extra,
      }),
    ),
  )
}
beforeEach(() => {
  owner.profile = 'alpha'
  owner.connection = null
  owner.submit.mockClear()
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => {
  cleanup()
  owner.listeners.clear()
})
it('loads image metadata, provenance, comparison, zoom lightbox and owner-chat Next with quoted credit estimates', async () => {
  const rest = vi.fn(async (path: string) =>
    path.startsWith('/provenance')
      ? { made_from: 'Made from Reference', parents: [{ id: 'parent', relation: 'source' }] }
      : file,
  )
  render(
    createElement(ImageCard, {
      ctx: ctx(rest as any),
      source: { path: '/image.png', asset: undefined },
      provenanceId: 'asset-1',
      before: { url: png },
      sessionId: 'owner',
      fallback: 'Image fallback',
    }),
  )
  const image = await screen.findByAltText('StudioTwin image')
  Object.defineProperties(image, { naturalWidth: { value: 64 }, naturalHeight: { value: 64 } })
  fireEvent.load(image)
  await screen.findByText(/64 × 64/)
  await screen.findByText('Made from Reference')
  fireEvent.change(screen.getByRole('slider', { name: 'Before / after' }), { target: { value: '27' } })
  expect(screen.getByRole('slider', { name: 'Before / after' }).getAttribute('value')).toBe('27')
  fireEvent.click(screen.getByRole('button', { name: 'Inspect image' }))
  expect(screen.getByRole('dialog')).toBeTruthy()
  fireEvent.change(screen.getByRole('slider', { name: 'Zoom' }), { target: { value: '2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Close inspection' }))
  fireEvent.click(screen.getByRole('button', { name: /Edit Concept Image/ }))
  expect(owner.submit).toHaveBeenCalledWith('owner', expect.stringContaining('estimate first'))
  expect(owner.submit.mock.calls[0][1]).not.toMatch(/\d+ credits/)
  switchScope()
  await screen.findByText('Image fallback')
})
it('keeps image fetch/decode failures on fallback and discards pending old-scope data', async () => {
  const view = render(createElement(ImageCard, { ctx: ctx(), source: { path: '/a.png' }, fallback: 'Image fallback' }))
  const image = await screen.findByAltText('StudioTwin image')
  fireEvent.error(image)
  await screen.findByText('Image fallback')
  view.rerender(createElement(ImageCard, { ctx: ctx(), source: { path: '/a.png' }, fallback: 'Image fallback' }))
  expect(screen.queryByAltText('StudioTwin image')).toBeNull()
  expect(screen.queryByText('StudioTwin Image / Concept')).toBeNull()
  expect(screen.queryByRole('button', { name: /Edit Concept Image/ })).toBeNull()
})
it('polls queued → running → completed and morphs to an image with backend actions', async () => {
  let polls = 0
  const rest = vi.fn(async (path: string) => {
    if (path.startsWith('/task'))
      return [
        { status: 'queued' },
        { status: 'running', progress: 50 },
        { status: 'COMPLETE', outputs: { imageUrl: png } },
      ][Math.min(polls++, 2)]
    if (path.startsWith('/actions'))
      return { actions: [{ id: 'rig', label: 'Backend next', cost: 17, message: 'Backend follow-up (17 credits)' }] }
    return file
  })
  mountTask(ctx(rest as any))
  await screen.findByText('queued')
  await screen.findByText('running')
  await screen.findByAltText('StudioTwin image')
  fireEvent.click(await screen.findByRole('button', { name: /Backend next.*17 cr/ }))
  expect(owner.submit).toHaveBeenCalledWith('original', 'Backend follow-up (17 credits)')
  const count = polls
  await new Promise((r) => setTimeout(r, 70))
  expect(polls).toBe(count)
})
it('cancels queued once, never running; stops polling and actions permanently on connection switch', async () => {
  const rest = vi.fn(async (path: string) =>
    path === '/cancel' ? { status: 'cancelled' } : { status: 'queued', progress: null },
  )
  mountTask(ctx(rest as any))
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel queued job' }))
  await screen.findByText('cancelled')
  expect(rest).toHaveBeenCalledWith('/cancel', { method: 'POST', body: { id: 'job-1' } })
  owner.connection = 'remote'
  owner.listeners.forEach((fn) => fn())
  await screen.findByText('Task fallback')
  const count = rest.mock.calls.length
  await new Promise((r) => setTimeout(r, 60))
  expect(rest).toHaveBeenCalledTimes(count)
})
it('stops at failed/cancelled, permanent polling error fallback persists', async () => {
  const rest = vi.fn(async () => {
    throw Error('offline')
  })
  mountTask(ctx(rest as any))
  await screen.findByText('Task fallback')
  await new Promise((r) => setTimeout(r, 60))
  expect(rest).toHaveBeenCalledTimes(1)
})
it('registers explicit image tools (bare and canonical), directives and no terminal claim', () => {
  const c = ctx()
  registerImageCards(c)
  registerVideoCards(c)
  registerTaskCards(c)
  const rows = vi.mocked(c.register).mock.calls.map(([r]) => r)
  expect(rows.filter((r) => r.area === 'transcript.directives').map((r) => (r.data as any).name)).toEqual([
    'studiotwin-image',
    'studiotwin-video',
    'studiotwin-task',
    'studiotwin-job',
    'studiotwin-concept',
  ])
  const tools = (rows[0].data as any).tools
  expect(tools).toContain('openai-gpt-image-1-v1-fn')
  expect(tools).toContain('openai-gpt-image-2-v4-fn')
  expect(tools).toContain('mcp__studiotwin__studiotwin_conceptlab_edit')
  expect(tools).not.toContain('terminal')
  expect(imageActions({ asset: 'a' }).map((a) => a.cost)).toEqual([null, 25, null, 25, null])
  expect(imageActions({ asset: 'a' }).map((a) => a.cost_label)).toEqual([
    'estimate in chat', '25 cr', 'estimate in chat', '25 cr', 'estimate in chat',
  ])
})
it('renders video controls, handles decode failure with persistent fallback', async () => {
  render(createElement(VideoCard, { ctx: ctx(), source: { path: '/v.mp4' }, fallback: 'Video fallback' }))
  await screen.findByRole('button', { name: '+1f' })
  fireEvent.error(document.querySelector('video')!)
  await screen.findByText('Video fallback')
})
it('requires explicit sequence timing rather than inventing a playback rate', async () => {
  render(createElement(VideoCard, { ctx: ctx(), source: {}, frames: [{ url: png }, { url: png }] }))
  await screen.findByAltText('Frame 1')
  expect((screen.getByRole('button', { name: '+1f' }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: 'Play' }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole('slider', { name: 'Timeline' }) as HTMLInputElement).disabled).toBe(true)
  await screen.findByText(/Exact frame timing unavailable/)
  expect(screen.queryByText(/24 fps/)).toBeNull()
})
it('all V05 presentation colors use theme variables', () => {
  for (const path of [
    'src/viewers/image-viewer.tsx',
    'src/viewers/video-viewer.tsx',
    'src/cards/image-card.tsx',
    'src/cards/video-card.tsx',
    'src/cards/task-card.tsx',
  ]) {
    const text = readFileSync(path, 'utf8')
    expect(text).not.toMatch(/#[\da-f]{3,8}\b|rgba?\(|(?:color|background):\s*['"](?:black|white)/i)
    expect(text).toContain('var(--ui-')
  }
})

it.each(['failed', 'cancelled'])(
  'stops polling terminal %s jobs and exposes no Cancel or generation retry',
  async (status) => {
    const rest = vi.fn(async () => ({ status, error: status === 'failed' ? 'provider failed' : null }))
    mountTask(ctx(rest as any))
    await screen.findByText(status, { exact: true })
    expect(screen.queryByRole('button', { name: /Cancel/ })).toBeNull()
    await new Promise((r) => setTimeout(r, 70))
    expect(rest).toHaveBeenCalledTimes(1)
  },
)
it('discards a pending response and never resurrects the old card after switching away and back', async () => {
  let resolve!: (value: unknown) => void
  const rest = vi.fn(
    () =>
      new Promise((r) => {
        resolve = r
      }),
  )
  const view = render(
    createElement(ImageCard, {
      ctx: ctx(rest as any),
      source: { path: '/a.png' },
      sessionId: 'owner',
      fallback: 'Old scope',
    }),
  )
  await waitFor(() => expect(rest).toHaveBeenCalledTimes(1))
  switchScope()
  owner.profile = 'alpha'
  owner.listeners.forEach((fn) => fn())
  resolve(file)
  await screen.findByText('Old scope')
  view.rerender(
    createElement(ImageCard, {
      ctx: ctx(rest as any),
      source: { path: '/a.png' },
      sessionId: 'owner',
      fallback: 'Old scope',
    }),
  )
  expect(screen.queryByRole('button', { name: /Edit Concept Image/ })).toBeNull()
  expect(rest).toHaveBeenCalledTimes(1)
})
it('never labels a cancellation acknowledgement as cancelled until status confirms it', async () => {
  let polls = 0
  const rest = vi.fn(async (path: string) =>
    path === '/cancel' ? { accepted: true } : { status: polls++ ? 'running' : 'queued' },
  )
  mountTask(ctx(rest as any), { pollInterval: 1000 })
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel queued job' }))
  await screen.findByText('running', { exact: true })
  expect(screen.queryByText('cancelled', { exact: true })).toBeNull()
  expect(screen.queryByRole('button', { name: /Cancel queued/ })).toBeNull()
})
it('polls Concept operation.status, resolves active history, comparison lineage and asset-specific /actions', async () => {
  let polls = 0
  const rest = vi.fn(async (path: string) => {
    if (path.endsWith('/status')) return { operation: { status: polls++ ? 'done' : 'running' } }
    if (path === '/concepts/job-1')
      return {
        assets: [
          { assetId: 'before', isActive: false, operation: { type: 'generate' } },
          { assetId: 'after', isActive: true, operation: { type: 'edit', sourceAssetId: 'before' } },
        ],
      }
    if (path.startsWith('/actions')) return { actions: [] }
    if (path.startsWith('/provenance')) return { made_from: 'Made from edit', parents: [{ id: 'before' }] }
    return file
  })
  mountTask(ctx(rest as any), { kind: 'concept' })
  await screen.findByText('running', { exact: true })
  await screen.findByRole('slider', { name: 'Before / after' })
  expect(rest).toHaveBeenCalledWith('/actions?id=after&type=image', undefined)
  expect(rest.mock.calls.map((c) => c[0])).toContain('/file?asset=after')
  expect(rest.mock.calls.map((c) => c[0])).toContain('/file?asset=before')
})
it('normalizes status vocabulary and Concept history, preserves delivery links and only trusts host media schemes from the resolver', () => {
  expect(['COMPLETE', 'done', 'succeeded'].map(jobStatus)).toEqual(['completed', 'completed', 'completed'])
  expect(jobStatus('IN_PROGRESS')).toBe('running')
  expect(() => jobStatus('unrecognized')).toThrow()
  expect(
    conceptImages({
      assets: [
        { assetId: null },
        { assetId: 'first' },
        { assetId: 'second', isActive: true, operation: { sourceAssetId: 'original' } },
      ],
    }),
  ).toEqual([
    { source: { asset: 'first' }, active: false, before: undefined },
    { source: { asset: 'second' }, active: true, before: { asset: 'original' } },
  ])
  expect(hostPlaybackUrl('hermes-media://remote/video?profile=alpha')).toContain('profile=alpha')
  expect(() => deliveryUrl('hermes-media://remote/video')).toThrow()
  const signed = 'https://s3.example/clip.mp4?X-Amz-Signature=delivery'
  expect(deliveryUrl(signed)).toBe(signed)
  expect(mediaQuery({ asset: 'a' }, true)).toBe('/file?asset=a&raw=1')
})

it.each([6, 10])('Chromium: registered and completed %i-fps video decoded steps, image inspection, sequence, jobs and invalidation', async (fps) => {
  const root = process.cwd()
  vi.stubGlobal('Uint8Array', new TextEncoder().encode('').constructor)
  const { build } = await import('esbuild')
  const bundle = await build({
    stdin: {
      resolveDir: root,
      loader: 'tsx',
      contents: `
    import React from 'react'; import {createRoot} from 'react-dom/client';
    import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
    import {ImageCard} from './src/cards/image-card.tsx';
    import {VideoCard,registerVideoCards} from './src/cards/video-card.tsx';
    import {TaskCard} from './src/cards/task-card.tsx';
    const ctx={rest: async (path,opts={}) => {window.requests.push(path); const response=await fetch('/api/plugins/hermes-studiotwin'+path,{method:opts.method||'GET',headers:{'Content-Type':'application/json'},body:opts.body?JSON.stringify(opts.body):undefined}); if(!response.ok)throw Error('HTTP '+response.status);return response.json()}};
    const registrations=[];ctx.register=row=>registrations.push(row);registerVideoCards(ctx);
    const registeredVideo=(path)=>registrations.find(r=>r.id==='studiotwin-video-media').data.render({toolName:'mcp__studiotwin__text_to_motion',toolCallId:path,result:{success:true},file:{kind:'video',path,resolveUrl:async()=>location.origin+'/api/plugins/hermes-studiotwin/file?path='+encodeURIComponent(path)+'&raw=1'},fallback:'Video fallback'});
    const history=[{source:{url:window.png},active:false},{source:{url:window.png},active:true,before:{url:window.png}}];
    const frames=[{url:window.png},{url:window.png},{url:window.png},{url:window.png}];
    createRoot(document.getElementById('root')).render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}>
      <div id='image'><ImageCard ctx={ctx} source={{url:window.png}} before={{url:window.png}} provenanceId='image-id' history={history} sessionId='owner' fallback='Image fallback'/></div>
      <div id='jpg'><ImageCard ctx={ctx} source={{url:window.jpg}} fallback='JPG fallback'/></div>
      <div id='webp'><ImageCard ctx={ctx} source={{url:window.webp}} fallback='WebP fallback'/></div>
      <div id='video'>{registeredVideo('/cache/preview.mp4')}</div>
      <div id='unknown-video'>{registeredVideo('/cache/unknown.mp4')}</div>
      <div id='completed-video'><TaskCard ctx={ctx} id='video-job' fallback='Completed video fallback'/></div>
      <div id='sequence'><VideoCard ctx={ctx} source={{}} frames={frames} fps={4} fallback='Sequence fallback'/></div>
      <div id='task'><TaskCard ctx={ctx} id='job' pollInterval={250} sessionId='owner' fallback='Task fallback'/></div>
      <div id='cancel'><TaskCard ctx={ctx} id='cancel' pollInterval={250} sessionId='owner' fallback='Cancel fallback'/></div>
    </QueryClientProvider>);
  `,
    },
    bundle: true,
    write: false,
    format: 'esm',
    jsx: 'automatic',
    plugins: [
      {
        name: 'host-shim',
        setup(b) {
          b.onResolve({ filter: /^@hermes\/plugin-sdk$/ }, () => ({ path: 'sdk', namespace: 'shim' }))
          b.onLoad({ filter: /.*/, namespace: 'shim' }, () => ({
            resolveDir: root,
            loader: 'js',
            contents: `
      import React from 'react'; export const Button=({size,variant,...p})=>React.createElement('button',p);
      export {useQuery} from '@tanstack/react-query';
      export const TOOL_MEDIA_RENDERER_AREA='transcript.toolMedia',TRANSCRIPT_DIRECTIVE_AREA='transcript.directives';
      const listeners=new Set();window.switchScope=()=>{window.profile='beta';listeners.forEach(fn=>fn())};
      export const host={state:{profile:{get:()=>window.profile,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)}},connectionId:{get:()=>null,subscribe:()=>()=>{}}},composer:{submit:(session,text)=>{window.messages.push({session,text});return true}},notify:()=>{}};
    `,
          }))
        },
      },
    ],
  })
  const browser = await chromium.launch({
    executablePath: existsSync('/opt/google/chrome/chrome') ? '/opt/google/chrome/chrome' : undefined,
    headless: true,
    args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'],
  })
  try {
    const page = await browser.newPage({ viewport: { width: 900, height: 1000 }, acceptDownloads: true })
    const errors: string[] = [],
      ranges: string[] = []
    page.on('pageerror', (e) => errors.push(e.message))
    let polls = 0,
      cancelled = false
    const bytes = readFileSync(fps === 6 ? 'tests/fixtures/media/video/testsrc-32.mp4' : 'tests/fixtures/video-timing/testsrc-32-10fps.mp4')
    await page.route('http://v05.test/**', async (route) => {
      const url = new URL(route.request().url()),
        path = url.pathname
      if (path === '/')
        return route.fulfill({
          contentType: 'text/html',
          body: '<style>:root{--ui-text-primary:#ddd;--ui-text-secondary:#aaa;--ui-stroke-secondary:#555;--ui-bg-card:#222;--ui-accent:#58a}body{background:#181818;color:#ddd;font:14px system-ui}button,input,select{margin:4px}article{margin:8px}</style><div id="root"></div>',
        })
      if (path.endsWith('/file')) {
        const range = route.request().headers().range
        if (url.searchParams.get('path') === '/cache/unknown.mp4' && !range)
          return route.fulfill({ status: 403, body: 'Timing inspection denied' })
        if (range) {
          ranges.push(range)
          const parts = /bytes=(\d+)-(\d*)/.exec(range)!,
            start = Number(parts[1]),
            end = parts[2] ? Math.min(Number(parts[2]), bytes.length - 1) : bytes.length - 1
          return route.fulfill({
            status: 206,
            headers: {
              'Content-Type': 'video/mp4',
              'Accept-Ranges': 'bytes',
              'Content-Range': `bytes ${start}-${end}/${bytes.length}`,
              'Content-Length': String(end - start + 1),
            },
            body: bytes.subarray(start, end + 1),
          })
        }
        return route.fulfill({ contentType: 'video/mp4', body: bytes })
      }
      let result: any = {}
      if (path.endsWith('/provenance'))
        result = { made_from: 'Made from Parent image', parents: [{ id: 'reference', relation: 'source' }] }
      if (path.endsWith('/task'))
        result =
          url.searchParams.get('id') === 'video-job'
            ? { status: 'completed', outputs: { videoUrl: 'http://v05.test/api/plugins/hermes-studiotwin/file?raw=1' } }
            : url.searchParams.get('id') === 'cancel'
            ? { status: cancelled ? 'cancelled' : 'queued' }
            : [
                { status: 'queued' },
                { status: 'running', progress: 55 },
                { status: 'COMPLETE', outputs: { imageUrl: png } },
              ][Math.min(polls++, 2)]
      if (path.endsWith('/actions'))
        result = {
          actions: [
            {
              id: 'next',
              label: 'Backend workflow',
              cost: 23,
              message: 'Continue this existing asset (23 credits); ask before submission.',
            },
          ],
        }
      if (path.endsWith('/cancel')) {
        cancelled = true
        result = { status: 'cancelled' }
      }
      return route.fulfill({ json: result })
    })
    await page.goto('http://v05.test/')
    await page.evaluate(async (png) => {
      const image = new Image()
      image.src = png
      await image.decode()
      const canvas = document.createElement('canvas')
      canvas.width = image.naturalWidth
      canvas.height = image.naturalHeight
      canvas.getContext('2d')!.drawImage(image, 0, 0)
      Object.assign(window, {
        png,
        jpg: canvas.toDataURL('image/jpeg'),
        webp: canvas.toDataURL('image/webp'),
        profile: 'alpha',
        requests: [],
        messages: [],
      })
    }, png)
    await page.addScriptTag({ type: 'module', content: bundle.outputFiles[0].text })
    const image = page.locator('#image'),
      video = page.locator('#video'),
      sequence = page.locator('#sequence'),
      task = page.locator('#task')
    await image.getByText(/64 × 64/).waitFor()
    for (const id of ['jpg', 'webp'])
      await page
        .locator('#' + id)
        .getByText(/64 × 64/)
        .waitFor()
    await image.getByText(/Made from/).waitFor()
    await image.getByRole('button', { name: /Version 2.*Active asset/ }).click()
    const slider = image.getByRole('slider', { name: 'Before / after' })
    await slider.fill('25')
    expect(await image.getByAltText('Before image').evaluate((el) => (el as HTMLElement).style.clipPath)).toContain(
      '75%',
    )
    await image.getByRole('button', { name: 'Inspect image' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('slider', { name: 'Zoom' }).fill('3')
    const pan = dialog.getByLabel('Pan image'),
      bounds = (await pan.boundingBox())!
    await page.mouse.move(bounds.x + 200, bounds.y + 40)
    await page.mouse.down()
    await page.mouse.move(bounds.x + 60, bounds.y + 40)
    await page.mouse.up()
    expect(await pan.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0)
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'detached' })
    await image.getByText(/Next ·/).click()
    await image.getByRole('button', { name: /Edit Concept Image/ }).click()
    expect((await page.evaluate(() => (window as any).messages))[0].session).toBe('owner')
    await page.locator('#cancel').getByRole('button', { name: 'Cancel queued job' }).click()
    await page.locator('#cancel').getByText('cancelled', { exact: true }).waitFor()
    expect(cancelled).toBe(true)
    await task.getByAltText('StudioTwin image').waitFor()
    await task
      .getByText(/Next ·/)
      .last()
      .click()
    await task.getByRole('button', { name: /Backend workflow.*23 cr/ }).click()
    expect((await page.evaluate(() => (window as any).messages))[1].text).toContain('23 credits')
    await page.waitForFunction(() => document.querySelector('video')!.readyState >= 2)
    expect(ranges.length).toBeGreaterThan(0)
    expect(await video.locator('video').getAttribute('src')).toContain('raw=1')
    expect(await video.locator('video').evaluate((v: HTMLVideoElement) => v.duration)).toBeCloseTo(1)
    for (const container of [video, page.locator('#completed-video')]) {
      await container.getByText(/source presentation timestamps/).waitFor()
      // Wait for the browser's decoded presentation callback, not just currentTime:
      // arbitrary sub-frame seeks can change currentTime while displaying the same frame.
      const decoded = await container.locator('video').evaluate(async (v: HTMLVideoElement) => {
        await new Promise<void>((resolve) => {
          v.requestVideoFrameCallback(() => resolve())
          v.currentTime = 0
        })
        const frames: number[] = []
        const tick = (_: number, metadata: VideoFrameCallbackMetadata) => {
          frames.push(metadata.mediaTime)
          v.requestVideoFrameCallback(tick)
        }
        v.requestVideoFrameCallback(tick)
        ;(v as any).decodedTimes = frames
        const pixels = () => {
          const c = document.createElement('canvas'); c.width = v.videoWidth; c.height = v.videoHeight
          c.getContext('2d')!.drawImage(v, 0, 0); return c.toDataURL()
        }
        ;(v as any).pixels = pixels
        return pixels()
      })
      await container.getByRole('button', { name: '+1f', exact: true }).click()
      expect(await container.locator('video').evaluate((v: HTMLVideoElement) => v.currentTime)).toBeCloseTo(1 / fps, 3)
      await page.waitForFunction(({ id, expected }) => {
        const v = document.querySelector(`#${id} video`) as any
        return !v.seeking && v.decodedTimes.some((t: number) => Math.abs(t - expected) < 0.00001)
      }, { id: await container.getAttribute('id'), expected: 1 / fps })
      expect(await container.locator('video').evaluate((v: HTMLVideoElement) => v.currentTime)).toBeCloseTo(1 / fps, 3)
      expect(await container.locator('video').evaluate((v: any) => v.pixels())).not.toBe(decoded)
      await container.locator('video').evaluate((v: any) => { v.decodedTimes.length = 0 })
      await container.getByRole('button', { name: '-1f', exact: true }).click()
      await page.waitForFunction((id) => {
        const v = document.querySelector(`#${id} video`) as any
        return !v.seeking && v.decodedTimes.includes(0)
      }, await container.getAttribute('id'))
      expect(await container.locator('video').evaluate((v: any) => v.pixels())).toBe(decoded)
    }
    const unknown = page.locator('#unknown-video')
    await unknown.getByText(/Exact frame timing unavailable/).waitFor()
    expect(await unknown.getByRole('button', { name: '+1f', exact: true }).isDisabled()).toBe(true)
    expect(await unknown.getByRole('button', { name: '-1f', exact: true }).isDisabled()).toBe(true)
    expect(await unknown.locator('small').innerText()).not.toContain('24 fps')
    await unknown.getByRole('button', { name: 'Play', exact: true }).click()
    await page.waitForFunction(() => (document.querySelector('#unknown-video video') as HTMLVideoElement).currentTime > 0.1)
    await unknown.getByRole('button', { name: 'Pause', exact: true }).click()
    await video.getByRole('slider', { name: 'Timeline' }).fill('0.5')
    await page.waitForFunction(
      () =>
        Math.abs(document.querySelector('video')!.currentTime - 0.5) < 0.01 &&
        !document.querySelector('video')!.seeking,
    )
    await video.getByRole('button', { name: 'Loop', exact: true }).click()
    expect(await video.locator('video').evaluate((v: HTMLVideoElement) => v.loop)).toBe(true)
    await video.getByRole('combobox', { name: 'Playback rate' }).selectOption('2')
    expect(await video.locator('video').evaluate((v: HTMLVideoElement) => v.playbackRate)).toBe(2)
    const download = page.waitForEvent('download')
    await video.getByRole('button', { name: 'Capture PNG' }).click()
    const capture = await download
    expect(capture.suggestedFilename()).toMatch(/\.png$/)
    const capturePath = (await capture.path())!
    expect(readFileSync(capturePath).subarray(0, 8)).toEqual(NodeBuffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
    await video.getByRole('button', { name: 'Play', exact: true }).click()
    await page.waitForFunction(
      () => !document.querySelector('video')!.paused && document.querySelector('video')!.currentTime > 0.1,
    )
    await page.waitForTimeout(700) // one real loop at 2×; media must still be playing
    expect(await video.locator('video').evaluate((v: HTMLVideoElement) => v.paused)).toBe(false)
    await video.getByRole('button', { name: 'Pause', exact: true }).click()
    await sequence.getByRole('button', { name: '+1f', exact: true }).click()
    await sequence.getByAltText('Frame 2', { exact: true }).waitFor()
    await sequence.getByRole('slider', { name: 'Timeline' }).fill('0.75')
    await sequence.getByAltText('Frame 4', { exact: true }).waitFor()
    await sequence.getByRole('button', { name: 'Loop', exact: true }).click()
    await sequence.getByRole('button', { name: 'Play', exact: true }).click()
    await sequence.getByAltText('Frame 1', { exact: true }).waitFor()
    await sequence.getByRole('button', { name: 'Pause', exact: true }).click()
    await page.evaluate(() => {
      document.documentElement.style.setProperty('--ui-text-primary', 'rgb(20, 20, 20)')
      document.documentElement.style.setProperty('--ui-bg-card', 'rgb(245, 245, 245)')
    })
    expect(await video.locator('article').evaluate((el) => getComputedStyle(el).color)).toBe('rgb(20, 20, 20)')
    if (process.env.V05_SCREENSHOT) await page.screenshot({ path: process.env.V05_SCREENSHOT, fullPage: true })
    await page.evaluate(() => (window as any).switchScope())
    for (const text of [
      'Image fallback',
      'JPG fallback',
      'WebP fallback',
      'Video fallback',
      'Completed video fallback',
      'Sequence fallback',
      'Task fallback',
      'Cancel fallback',
    ]) {
      await page.getByText(text, { exact: true }).first().waitFor()
      for (const fallback of await page.getByText(text, { exact: true }).all()) await fallback.waitFor()
    }
    expect(await page.getByText('Video fallback', { exact: true }).count()).toBe(2)
    const count = await page.evaluate(() => (window as any).requests.length)
    await page.waitForTimeout(350)
    expect(await page.evaluate(() => (window as any).requests.length)).toBe(count)
    expect(errors).toEqual([])
  } finally {
    await browser.close()
  }
}, 60000)
