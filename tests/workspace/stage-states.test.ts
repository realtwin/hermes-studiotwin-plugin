// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { PluginContext } from '@hermes/plugin-sdk'

// Only GPU construction is replaced: the viewers, pooled hook, pool, source decoding,
// scope binding, multiview staging REST and lifecycle reducers below are production code.
vi.mock('../../src/viewers/model-stage.ts', () => ({ createModelStage: vi.fn() }))
vi.mock('../../src/viewers/env-stage.ts', async original => ({
  ...await original<typeof import('../../src/viewers/env-stage.ts')>(), createEnvStage: vi.fn(),
}))
vi.mock('../../src/viewers/material-stage.ts', async original => ({
  ...await original<typeof import('../../src/viewers/material-stage.ts')>(), createMaterialStage: vi.fn(),
}))
import { createModelStage, type MultiviewCapture } from '../../src/viewers/model-stage.ts'
import { createEnvStage } from '../../src/viewers/env-stage.ts'
import { createMaterialStage } from '../../src/viewers/material-stage.ts'
import { ModelViewer } from '../../src/viewers/model-viewer.tsx'
import { EnvViewer } from '../../src/viewers/env-viewer.tsx'
import { MaterialViewer } from '../../src/viewers/material-viewer.tsx'
import { modelWebGLPool } from '../../src/viewers/webgl-pool.ts'

function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const stats = { vertices: 12, triangles: 4, meshes: 1, bones: 0, clips: [], skinnedMeshes: 0 }
const snapshot = 'data:image/png;base64,c25hcHNob3Q='
const file = (name = 'model.glb', text = 'model') => ({ name, bytes: text.length, dataUrl: `data:application/octet-stream,${encodeURIComponent(text)}` })
const capture = {
  sheetDataUrl: 'data:image/png;base64,c2hlZXQ=', shading: 'clay',
  views: [{ name: 'front', label: 'Front' }, { name: 'back', label: 'Back' }],
} as MultiviewCapture
function gpuStage() {
  return {
    load: vi.fn(async () => stats), dispose: vi.fn(), snapshot: vi.fn(() => snapshot),
    setGrid: vi.fn(), setAutoRotate: vi.fn(), setShading: vi.fn(), clearEnvironment: vi.fn(),
    setEnvironment: vi.fn(), animation: vi.fn(() => null), reset: vi.fn(), invalidate: vi.fn(),
    settings: vi.fn(), autoRotate: vi.fn(), select: vi.fn(), captureMultiview: vi.fn(async () => capture),
  }
}
let stages: ReturnType<typeof gpuStage>[]
let nextLoad: ReturnType<typeof deferred<typeof stats>> | undefined
let observers: { callback: IntersectionObserverCallback; target?: Element }[]
let rest: PluginContext['rest']
const kinds = ['model', 'environment', 'material'] as const
type Kind = typeof kinds[number]
function viewer(kind: Kind, source = 'first', extra: Record<string, unknown> = {}) {
  const common = { rest, webgl_limit: 1, ...extra }
  if (kind === 'model') return createElement(ModelViewer, { ...common, source: { path: source + '.glb' } })
  if (kind === 'environment') return createElement(EnvViewer, { ...common, source: { path: source + '.hdr' } })
  return createElement(MaterialViewer, { ...common, maps: { albedo: { path: source + '.png' } } })
}
const startName = (kind: Kind) => kind === 'model' ? 'Click to load 3D' : `Load ${kind}`
const retryName = (kind: Kind) => kind === 'model' ? 'Preview failed. Retry 3D' : `Preview failed. Retry ${kind}`
const phase = (container: HTMLElement) => container.querySelector('[data-stage-state]')?.getAttribute('data-stage-state')
const multiPhase = () => screen.getByRole('group', { name: 'Multiview' }).getAttribute('data-multiview-state')
async function start(kind: Kind) { fireEvent.click(screen.getByRole('button', { name: new RegExp(startName(kind)) })); await act(async () => {}) }
function evict(container: HTMLElement) {
  const target = container.querySelector('[data-stage-state]')!
  const observer = observers.find(o => o.target === target)!
  act(() => observer.callback([{ target, isIntersecting: false } as IntersectionObserverEntry], {} as IntersectionObserver))
}

beforeEach(() => {
  stages = []; observers = []; nextLoad = undefined
  rest = vi.fn(async () => file()) as PluginContext['rest']
  const make = () => {
    const stage = gpuStage()
    if (nextLoad) { const pending = nextLoad; stage.load.mockImplementation(() => pending.promise); nextLoad = undefined }
    stages.push(stage); return stage
  }
  vi.mocked(createModelStage).mockImplementation(make as unknown as typeof createModelStage)
  vi.mocked(createEnvStage).mockImplementation(make as unknown as typeof createEnvStage)
  vi.mocked(createMaterialStage).mockImplementation(make as unknown as typeof createMaterialStage)
  vi.stubGlobal('IntersectionObserver', class {
    row: typeof observers[number]
    constructor(callback: IntersectionObserverCallback) { this.row = { callback }; observers.push(this.row) }
    observe(target: Element) { this.row.target = target }
    disconnect() {}
  })
})
afterEach(() => { cleanup(); modelWebGLPool.clear() })

it.each(kinds)('%s exposes poster → loading → ready without simultaneous retry and loading UI', async kind => {
  const pending = deferred<typeof stats>(); nextLoad = pending
  const { container } = render(viewer(kind))
  expect(phase(container)).toBe('poster')
  expect(screen.queryByRole('status')).toBeNull()
  await start(kind)
  expect(phase(container)).toBe('loading')
  expect(screen.getByRole('status').textContent).toMatch(/Loading/)
  expect(screen.queryByRole('button', { name: startName(kind) })).toBeNull()
  expect(screen.queryByRole('button', { name: retryName(kind) })).toBeNull()
  await act(async () => pending.resolve(stats))
  expect(phase(container)).toBe('ready')
  expect(screen.queryByText(/Loading (model|environment|material)…/)).toBeNull()
  expect(screen.getByRole('toolbar')).toBeDefined()
})

it.each(kinds)('%s retains its snapshot after offscreen eviction and can acquire a fresh stage', async kind => {
  const { container } = render(viewer(kind))
  await start(kind)
  expect(phase(container)).toBe('ready')
  evict(container)
  expect(phase(container)).toBe('evicted')
  expect(container.querySelector('img')?.getAttribute('src')).toBe(snapshot)
  expect(screen.queryByRole('toolbar')).toBeNull()
  expect(screen.queryByRole('status')).toBeNull()
  expect(stages[0].dispose).toHaveBeenCalledTimes(1)
  expect(modelWebGLPool.size).toBe(0)
  await start(kind)
  expect(phase(container)).toBe('ready')
  expect(stages).toHaveLength(2)
})

it.each(kinds)('%s load failure survives lease release; retry is exclusive with status and actually reloads', async kind => {
  const pending = deferred<typeof stats>(); nextLoad = pending
  const onError = vi.fn(), { container } = render(viewer(kind, 'first', { onError }))
  await start(kind)
  await act(async () => pending.reject(Error('GPU decode failed')))
  expect(phase(container)).toBe('error')
  expect(screen.getByRole('button', { name: retryName(kind) })).toBeDefined()
  expect(screen.queryByRole('status')).toBeNull()
  expect(screen.queryByRole('toolbar')).toBeNull()
  expect(modelWebGLPool.size).toBe(0)
  expect(onError).toHaveBeenCalledTimes(1)
  evict(container)
  expect(phase(container)).toBe('error')
  fireEvent.click(screen.getByRole('button', { name: retryName(kind) }))
  await waitFor(() => expect(phase(container)).toBe('ready'))
  expect(stages).toHaveLength(2)
  expect(screen.queryByRole('button', { name: retryName(kind) })).toBeNull()
})

it.each(kinds)('%s fallback still exposes error instead of erasing failed load during disposal', async kind => {
  const pending = deferred<typeof stats>(); nextLoad = pending
  const { container } = render(viewer(kind, 'first', { fallback: createElement('p', null, 'Original asset fallback') }))
  await start(kind)
  await act(async () => pending.reject(Error('bad file')))
  expect(phase(container)).toBe('error')
  expect(screen.getByText('Original asset fallback')).toBeDefined()
  expect(screen.queryByRole('status')).toBeNull()
})

it.each(kinds.flatMap(kind => [true, false].map(success => ({ kind, success }))))('$kind ignores superseded load completion (success=$success)', async ({ kind, success }) => {
  const old = deferred<typeof stats>(); nextLoad = old
  const onError = vi.fn(), { container, rerender } = render(viewer(kind, 'first', { onError }))
  await start(kind)
  const fresh = deferred<typeof stats>(); nextLoad = fresh
  rerender(viewer(kind, 'second', { onError }))
  await act(async () => {})
  expect(stages).toHaveLength(2)
  expect(stages[0].dispose).toHaveBeenCalledTimes(1)
  if (success) {
    // An obsolete success must not mark the replacement ready before it loads.
    await act(async () => old.resolve(stats))
    expect(phase(container)).toBe('loading')
    expect(screen.queryByRole('toolbar')).toBeNull()
    await act(async () => fresh.resolve(stats))
  } else {
    await act(async () => fresh.resolve(stats))
    await act(async () => old.reject(Error('obsolete failure')))
  }
  expect(phase(container)).toBe('ready')
  expect(onError).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: retryName(kind) })).toBeNull()
})

it('model audit is terminal without loading/retry controls and releases its GPU lease', async () => {
  rest = vi.fn(async () => file('rig.json', JSON.stringify({ riggable: true, joints: 24, warnings: ['Inspect hands'] }))) as PluginContext['rest']
  const { container } = render(createElement(ModelViewer, { rest, source: { path: 'rig.json' } }))
  await start('model')
  expect(phase(container)).toBe('audit')
  expect(screen.getByText(/Rig audit: passed/)).toBeDefined()
  expect(screen.getByText('Inspect hands')).toBeDefined()
  expect(screen.queryByRole('status')).toBeNull()
  expect(screen.queryByRole('button')).toBeNull()
  expect(stages[0].load).not.toHaveBeenCalled()
  expect(stages[0].dispose).toHaveBeenCalledTimes(1)
  expect(modelWebGLPool.size).toBe(0)
})

it('real shared pool evicts the first viewer when a second viewer takes its only slot', async () => {
  const a = render(viewer('environment')), b = render(viewer('material'))
  await start('environment')
  await start('material')
  expect(phase(a.container)).toBe('evicted')
  expect(a.container.querySelector('img')?.getAttribute('src')).toBe(snapshot)
  expect(phase(b.container)).toBe('ready')
  expect(modelWebGLPool.size).toBe(1)
})

it.each(['upload', 'provenance', 'callback'] as const)('multiview retains downloadable pixels after %s failure and supports staged/reskin retry', async failure => {
  const pixels = deferred<MultiviewCapture>(), upload = deferred<{ path: string }>(), provenance = deferred<object>()
  const onReskin = vi.fn(), onMultiviewCaptured = vi.fn(async () => {})
  if (failure === 'callback') onMultiviewCaptured.mockRejectedValueOnce(Error('callback failed'))
  rest = vi.fn(async (path: string) => {
    if (path.startsWith('/file?')) return file()
    if (path === '/upload') return upload.promise
    if (path === '/provenance') return provenance.promise
    throw Error('Unexpected endpoint: ' + path)
  }) as PluginContext['rest']
  render(viewer('model', 'first', { onReskin, onMultiviewCaptured, sessionId: 'session-a' }))
  await start('model')
  stages[0].captureMultiview.mockReturnValueOnce(pixels.promise)
  expect(multiPhase()).toBe('idle')
  const captureButton = screen.getByRole('button', { name: 'Capture Multiview' }) as HTMLButtonElement
  fireEvent.click(captureButton)
  expect(multiPhase()).toBe('capturing')
  expect(captureButton.disabled).toBe(true)
  expect(screen.getByRole('status').textContent).toBe('Capturing views…')
  expect((screen.getByLabelText('Multiview views') as HTMLSelectElement).disabled).toBe(true)
  fireEvent.click(captureButton)
  expect(stages[0].captureMultiview).toHaveBeenCalledTimes(1)
  await act(async () => pixels.resolve(capture))
  expect(multiPhase()).toBe('staging')
  expect(screen.getByRole('status').textContent).toBe('Staging sheet…')
  expect(screen.getByAltText('Multiview Reference Preview').getAttribute('src')).toBe(capture.sheetDataUrl)
  expect(screen.getByRole('button', { name: 'Download Sheet' })).toBeDefined()
  expect((screen.getByRole('button', { name: 'Reskin 3D in Chat' }) as HTMLButtonElement).disabled).toBe(true)
  expect(rest).toHaveBeenCalledWith('/upload', { method: 'POST', body: { filename: 'first-multiview-2v-clay.png', data: 'c2hlZXQ=', cloud: false } })
  if (failure === 'upload') await act(async () => upload.reject(Error('upload failed')))
  else {
    await act(async () => upload.resolve({ path: '/local/sheet.png' }))
    if (failure === 'provenance') await act(async () => provenance.reject(Error('provenance failed')))
    else await act(async () => provenance.resolve({}))
  }
  expect(multiPhase()).toBe('partial_error')
  expect(screen.getByRole('alert').textContent).toContain('Nothing was generated in the cloud')
  expect(screen.queryByRole('status')).toBeNull()
  expect(captureButton.disabled).toBe(false)
  expect(screen.getByRole('button', { name: 'Download Sheet' })).toBeDefined()
  const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.href).toBe(capture.sheetDataUrl)
    expect(this.download).toBe('first-multiview-2v-clay.png')
  })
  fireEvent.click(screen.getByRole('button', { name: 'Download Sheet' }))
  expect(anchorClick).toHaveBeenCalledTimes(1)
  expect(onReskin).not.toHaveBeenCalled()
  // Retry succeeds using the actual upload/provenance helper, not a staging mock.
  vi.mocked(rest).mockImplementation(async (path: string) => (path === '/upload' ? { path: '/local/retry.png' } : {}) as never)
  fireEvent.click(captureButton)
  await waitFor(() => expect(multiPhase()).toBe('staged'))
  expect(screen.getByRole('status').textContent).toBe('Ready for Reskin')
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByText(/Locally staged/).textContent).toContain('/local/retry.png')
  expect(within(screen.getByRole('region', { name: 'Multiview Reference Preview' })).getByRole('button', { name: 'Download Sheet' })).toBeDefined()
  const reskin = screen.getByRole('button', { name: 'Reskin 3D in Chat' }) as HTMLButtonElement
  expect(reskin.disabled).toBe(false)
  fireEvent.click(reskin)
  expect(onReskin).toHaveBeenCalledWith(expect.stringContaining('/local/retry.png'))
})

it('multiview capture failure has error without nonexistent download or reskin availability', async () => {
  render(viewer('model', 'first', { onReskin: vi.fn() }))
  await start('model')
  stages[0].captureMultiview.mockRejectedValueOnce(Error('capture failed'))
  fireEvent.click(screen.getByRole('button', { name: 'Capture Multiview' }))
  await waitFor(() => expect(multiPhase()).toBe('error'))
  expect(screen.getByRole('alert')).toBeDefined()
  expect(screen.queryByRole('button', { name: 'Download Sheet' })).toBeNull()
  expect((screen.getByRole('button', { name: 'Reskin 3D in Chat' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.queryByRole('status')).toBeNull()
})

it('multiview completion from a superseded model cannot stage a sheet or enable reskin', async () => {
  const pending = deferred<MultiviewCapture>()
  const { rerender } = render(viewer('model'))
  await start('model')
  stages[0].captureMultiview.mockReturnValueOnce(pending.promise)
  fireEvent.click(screen.getByRole('button', { name: 'Capture Multiview' }))
  expect(multiPhase()).toBe('capturing')
  rerender(viewer('model', 'second'))
  await waitFor(() => expect(multiPhase()).toBe('idle'))
  await act(async () => pending.resolve(capture))
  expect(multiPhase()).toBe('idle')
  expect(screen.queryByRole('button', { name: 'Download Sheet' })).toBeNull()
  expect(vi.mocked(rest).mock.calls.some(([path]) => path === '/upload')).toBe(false)
})

it('a superseded model fetch cannot decode into the retired stage or replace current stats', async () => {
  const old = deferred<ReturnType<typeof file>>()
  rest = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValue(file()) as PluginContext['rest']
  const { container, rerender } = render(viewer('model'))
  await start('model')
  rerender(viewer('model', 'second'))
  await waitFor(() => expect(phase(container)).toBe('ready'))
  await act(async () => old.resolve(file('obsolete.glb')))
  expect(phase(container)).toBe('ready')
  expect(stages[0].load).not.toHaveBeenCalled()
  expect(stages[1].load).toHaveBeenCalledTimes(1)
  expect(container.querySelector('[data-model-stats]')?.textContent).toContain('12 vertices')
})

it('a staging completion after model replacement cannot restore the old sheet or enable reskin', async () => {
  const upload = deferred<{ path: string }>(), onReskin = vi.fn()
  rest = vi.fn(async (path: string) => {
    if (path.startsWith('/file?')) return file()
    if (path === '/upload') return upload.promise
    return {}
  }) as PluginContext['rest']
  const { rerender } = render(viewer('model', 'first', { onReskin }))
  await start('model')
  fireEvent.click(screen.getByRole('button', { name: 'Capture Multiview' }))
  await waitFor(() => expect(multiPhase()).toBe('staging'))
  rerender(viewer('model', 'second', { onReskin }))
  await waitFor(() => expect(multiPhase()).toBe('idle'))
  await act(async () => upload.resolve({ path: '/local/obsolete.png' }))
  expect(multiPhase()).toBe('idle')
  expect(screen.queryByAltText('Multiview Reference Preview')).toBeNull()
  expect((screen.getByRole('button', { name: 'Reskin 3D in Chat' }) as HTMLButtonElement).disabled).toBe(true)
  expect(onReskin).not.toHaveBeenCalled()
})

/* MUTATION_RUNNER_PYTHON
# Extract this block and run only after coordinating exclusive production-file access.
# It snapshots current worktree bytes (never git/stash/reset), mutates one contract
# at a time, requires assertion failures (not transform/import errors), and restores
# exactly these sources in finally. Baseline is rerun after every restoration.
from pathlib import Path
import subprocess
root = Path('/home/deploy/work/realtwin/hermes-studiotwin/worktrees/v13')
allowed = ['src/viewers/env-lifecycle.ts', 'src/viewers/model-viewer.tsx', 'src/viewers/env-viewer.tsx', 'src/viewers/material-viewer.tsx']
saved = {p: (root / p).read_bytes() for p in allowed}
cmd = ['node_modules/.bin/vitest', 'run', 'tests/workspace/stage-states.test.ts', '--reporter=verbose']
mutants = [
 ('model-phase', allowed[1], 'data-stage-state={v.phase}', "data-stage-state={'poster'}"),
 ('env-phase', allowed[2], 'data-stage-state={v.phase}', "data-stage-state={'poster'}"),
 ('material-phase', allowed[3], 'data-stage-state={v.phase}', "data-stage-state={'poster'}"),
 ('late-load-fence', allowed[0], 'if (!alive) return;', 'if (false) return;'),
 ('snapshot-loss', allowed[0], 'poster = local.snapshot()', 'poster = undefined'),
 ('multiview-phase', allowed[1], 'data-multiview-state={multiview.phase}', "data-multiview-state={'idle'}"),
]
try:
 for name, path, old, new in mutants:
  source = saved[path].decode()
  assert old in source, f'Mutation anchor missing: {name}'
  try:
   (root / path).write_text(source.replace(old, new))
   run = subprocess.run(cmd, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
   (root / f'evidence/v13/stage-mutation-{name}.log').write_text(run.stdout)
   assert run.returncode != 0 and 'AssertionError' in run.stdout, f'{name}: no assertion RED'
   assert 'Test Files  1 failed' in run.stdout and 'Unhandled Errors' not in run.stdout, f'{name}: invalid RED'
  finally:
   (root / path).write_bytes(saved[path])
  baseline = subprocess.run(cmd, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  (root / f'evidence/v13/stage-restored-{name}.log').write_text(baseline.stdout)
  assert baseline.returncode == 0, f'{name}: restored baseline failed'
finally:
 for path, content in saved.items():
  (root / path).write_bytes(content)
MUTATION_RUNNER_PYTHON */
