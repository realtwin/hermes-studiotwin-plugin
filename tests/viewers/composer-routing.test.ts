import { afterEach, describe, expect, it, vi } from 'vitest'
import { host } from '@hermes/plugin-sdk'
import { submitNext } from '../../src/cards/next-actions.ts'
import { compose } from '../../src/pages/workspace-data.ts'
import { currentScope, submitNext as audioNext } from '../../src/viewers/audio-engine.ts'

const action = { id: 'next', label: 'Next', message: 'Review in chat' }
const scope = { assert() {} } as any
const routes = [
  ['media', (id: string | null | undefined) => submitNext(scope, id, action)],
  ['audio', (id: string | null | undefined) => audioNext(currentScope(), id, { ...action, cost: '0' })],
] as const

afterEach(() => vi.restoreAllMocks())
describe.each(routes)('%s composer routing', (_name, send) => {
  it.each([undefined, null, 'owner', 'origin-chat'])('routes %s correctly', id => {
    const submit = vi.spyOn(host.composer!, 'submit').mockReturnValue(true)
    expect(send(id)).toBe(true)
    expect(submit.mock.calls).toEqual([[id === undefined ? null : id === null ? 'new' : id, action.message]])
  })
  it('falls back from an unclaimed fresh draft to active', () => {
    const submit = vi.spyOn(host.composer!, 'submit').mockReturnValueOnce(false).mockReturnValueOnce(true)
    expect(send(null)).toBe(true)
    expect(submit.mock.calls).toEqual([['new', action.message], [null, action.message]])
  })
  it.each(['owner', 'origin-chat', '', '   '])('does not retarget rejected/invalid explicit owner %s', id => {
    const submit = vi.spyOn(host.composer!, 'submit').mockReturnValue(false)
    expect(send(id)).toBe(false)
    expect(submit.mock.calls).toEqual(id.trim() ? [[id, action.message]] : [])
  })
})
it.each([undefined, null, 'owner'])('workspace %s routes to captured owner or active, never new', id => {
  const submit = vi.spyOn(host.composer!, 'submit').mockReturnValue(true)
  compose(scope, id, action)
  expect(submit.mock.calls).toEqual([[id ?? null, action.message]])
})
it('workspace preserves explicit-owner failure and scope invalidation', () => {
  const submit = vi.spyOn(host.composer!, 'submit').mockReturnValue(false)
  compose(scope, 'owner', action)
  expect(submit.mock.calls).toEqual([['owner', action.message]])
  submit.mockClear()
  compose({ assert() { throw Error('stale') } } as any, undefined, action)
  expect(submit).not.toHaveBeenCalled()
  expect(() => submitNext({ assert() { throw Error('stale') } } as any, undefined, action)).toThrow('stale')
  expect(submit).not.toHaveBeenCalled()
})
it('audio scope switch blocks even active-composer fallback', () => {
  const submit = vi.spyOn(host.composer!, 'submit').mockReturnValue(true)
  expect(audioNext({ profile: 'another-profile', connection: null }, undefined, { ...action, cost: '0' })).toBe(false)
  expect(submit).not.toHaveBeenCalled()
})
