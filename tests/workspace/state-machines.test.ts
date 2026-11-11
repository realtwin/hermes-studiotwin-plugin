import { expect, it } from 'vitest'
const machines = await import('../../src/lib/state-machines.ts').catch(() => ({})) as typeof import('../../src/lib/state-machines.ts')
it('stage residency preserves snapshots and failures; ignores late ready', () => {
  expect(machines.stageTransition).toBeTypeOf('function')
  let s = machines.stageTransition({ phase: 'poster' }, { type: 'start' })
  expect(s.phase).toBe('loading')
  s = machines.stageTransition(s, { type: 'ready' }); expect(s.phase).toBe('ready')
  s = machines.stageTransition(s, { type: 'evict', poster: 'snapshot' }); expect(s).toEqual({ phase: 'evicted', poster: 'snapshot' })
  expect(machines.stageTransition(s, { type: 'ready' })).toBe(s)
  s = machines.stageTransition(s, { type: 'start' })
  s = machines.stageTransition(s, { type: 'error' })
  expect(machines.stageTransition(s, { type: 'evict' })).toBe(s)
  expect(machines.stageProjection(s)).toEqual({ live: false, ready: false, error: true })
  expect(machines.stageTransition(s, { type: 'reset', poster: 'new' })).toEqual({ phase: 'poster', poster: 'new' })
  expect(machines.stageTransition({ phase: 'loading' }, { type: 'audit' }).phase).toBe('audit')
})
it('multiview preserves downloadable capture on staging failure and rejects out-of-order events', () => {
  expect(machines.multiviewTransition).toBeTypeOf('function')
  const capture = { sheetDataUrl: 'png', views: [] }
  const idle = { phase: 'idle' } as const
  expect(machines.multiviewTransition(idle, { type: 'staged', sheetPath: '/sheet' })).toBe(idle)
  let s = machines.multiviewTransition(idle, { type: 'start' })
  s = machines.multiviewTransition(s, { type: 'captured', capture })
  expect(s).toEqual({ phase: 'staging', capture })
  expect(machines.multiviewTransition(s, { type: 'error', message: 'host failed' })).toEqual({ phase: 'partial_error', capture, message: 'host failed' })
  expect(machines.multiviewTransition(s, { type: 'staged', sheetPath: '/sheet' })).toEqual({ phase: 'staged', capture, sheetPath: '/sheet' })
  expect(machines.multiviewTransition({ phase: 'capturing' }, { type: 'error', message: 'render failed' })).toEqual({ phase: 'error', message: 'render failed' })
  expect(machines.multiviewTransition(s, { type: 'reset' })).toEqual(idle)
})
it('task derivation gives terminal results priority over cancellation', () => {
  expect(machines.deriveTaskCardState).toBeTypeOf('function')
  expect(machines.deriveTaskCardState({ status: 'success', cancelling: true, cancelWarning: 'late' })).toEqual({ phase: 'completed' })
  expect(machines.deriveTaskCardState({ stale: true })).toEqual({ phase: 'stale' })
  expect(machines.deriveTaskCardState({ loading: true })).toEqual({ phase: 'loading' })
  expect(machines.deriveTaskCardState({ status: 'running', cancelWarning: 'retry' })).toEqual({ phase: 'running', cancelWarning: 'retry' })
})
it.each([
  ['submitted', 'queued'], ['pending', 'queued'], ['draft', 'queued'], ['queued', 'queued'],
  ['executing', 'running'], ['in-progress', 'running'], ['IN PROGRESS', 'running'], ['processing', 'running'], ['running', 'running'],
  ['done', 'completed'], ['complete', 'completed'], ['completed', 'completed'], ['succeeded', 'completed'], ['success', 'completed'],
  ['canceled', 'cancelled'], ['cancelled', 'cancelled'], ['failed', 'failed'], ['error', 'failed'],
  [undefined, 'queued'], [null, 'queued'], [{}, 'queued'], ['future-state', 'queued'],
])('normalizes %j to %s without throwing', (input, expected) => {
  expect(machines.normalizeJobStatus(input)).toBe(expected)
})
it('stage transitions cannot manufacture readiness from passive or terminal states', () => {
  for (const phase of ['poster', 'evicted', 'error', 'audit'] as const) {
    const state = { phase, poster: 'retained' }
    expect(machines.stageTransition(state, { type: 'ready' })).toBe(state)
    expect(machines.stageTransition(state, { type: 'audit' })).toBe(state)
    expect(machines.stageProjection(state).live).toBe(false)
    expect(machines.stageProjection(state).ready).toBe(false)
    expect(machines.stageTransition(state, { type: 'start' })).toEqual({ phase: 'loading', poster: 'retained' })
  }
  for (const phase of ['loading', 'ready'] as const) {
    const state = { phase, poster: 'retained' }
    expect(machines.stageTransition(state, { type: 'start' })).toBe(state)
    expect(machines.stageProjection(state).live).toBe(true)
    expect(machines.stageTransition(state, { type: 'evict' })).toEqual({ phase: 'evicted', poster: 'retained' })
    expect(machines.stageTransition(state, { type: 'error' })).toEqual({ phase: 'error', poster: 'retained' })
  }
})
it('multiview accepts only in-order completion and permits retry after failure', () => {
  const capture = { sheetDataUrl: 'sheet' }
  for (const state of [
    { phase: 'idle' }, { phase: 'staged', capture, sheetPath: '/local' },
    { phase: 'partial_error', capture, message: 'host' }, { phase: 'error', message: 'gpu' },
  ] as const) {
    expect(machines.multiviewTransition(state, { type: 'error', message: 'late' })).toBe(state)
    expect(machines.multiviewTransition(state, { type: 'captured', capture })).toBe(state)
    expect(machines.multiviewTransition(state, { type: 'staged', sheetPath: '/late' })).toBe(state)
    expect(machines.multiviewTransition(state, { type: 'start' })).toEqual({ phase: 'capturing' })
  }
  for (const state of [{ phase: 'capturing' }, { phase: 'staging', capture }] as const) {
    expect(machines.multiviewTransition(state, { type: 'start' })).toBe(state)
  }
})
it('inspector covers jobOnly and error precedence without losing local fallback', () => {
  expect(machines.resolveInspectorTargetState({ jobOnly: true }, {}, {})).toEqual({ phase: 'loading_job_output' })
  expect(machines.resolveInspectorTargetState({ jobOnly: true }, {}, { isError: true })).toEqual({ phase: 'job_output_error' })
  const target = { path: '/local', type: 'image' }
  expect(machines.resolveInspectorTargetState(target, { isError: true }, {})).toEqual({ phase: 'ready', target, modality: 'image' })
  expect(machines.resolveInspectorTargetState({ jobOnly: true }, {}, { data: { type: 'rig_check' } }).phase).toBe('rig_check_summary')
})
it('task covers cancellation and query errors explicitly', () => {
  expect(machines.deriveTaskCardState({ status: 'queued', cancelling: true })).toEqual({ phase: 'cancelling' })
  expect(machines.deriveTaskCardState({ status: 'queued', cancelled: true })).toEqual({ phase: 'cancelled' })
  expect(machines.deriveTaskCardState({ failed: true })).toEqual({ phase: 'failed' })
  expect(machines.deriveTaskCardState({ status: 'error', cancelWarning: 'late' })).toEqual({ phase: 'failed' })
})
