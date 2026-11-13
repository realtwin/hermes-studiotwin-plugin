// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { act, cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
const fixture = vi.hoisted(() => ({ rest: vi.fn(), key: 'poll-scope' }))
vi.mock('@hermes/plugin-sdk', async () => ({ ...await import('@tanstack/react-query'), host: {composer:{}}, Codicon: () => null }))
vi.mock('../../src/cards/next-actions.ts', async importOriginal => ({ ...await importOriginal<typeof import('../../src/cards/next-actions.ts')>(), useMediaScope: () => ({
  scope: { ...fixture, current: () => true, assert: () => {} }, stale: false,
}) }))
import { ActiveJobsChip } from '../../src/chrome/statusbar.tsx'
afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks() })
it('polls bounded summaries, backs off idle/errors, and caches only the count', async () => {
  vi.useFakeTimers()
  let count = 0, fail = false
  const calls: number[] = []
  fixture.rest.mockImplementation(async (path: string) => {
    if (path === '/status') return { configured: true }
    expect(path).toBe('/jobs?limit=100&offset=0&summary=true')
    calls.push(Date.now())
    if (fail) throw Error('fixture network failure')
    return { jobs: Array.from({length:count}, (_,i) => ({uuid:String(i),status:'running'})) }
  })
  const client = new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}})
  render(createElement(QueryClientProvider, {client}, createElement(ActiveJobsChip, {ctx:{} as any,onOpen:vi.fn()})))
  await act(async () => { await vi.advanceTimersByTimeAsync(10) })
  expect(calls.length).toBe(1)
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(calls.length).toBe(1)
  count = 2
  await act(async () => { await vi.advanceTimersByTimeAsync(25000) })
  expect(calls.length).toBe(2)
  await act(async () => { await vi.advanceTimersByTimeAsync(10) })
  expect(screen.getByText('2 active StudioTwin jobs')).toBeTruthy()
  expect(client.getQueryData(['studiotwin-workspace','poll-scope','active-job-count'])).toBe(2)
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(calls.length).toBe(3)
  fail = true
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(calls.length).toBe(4)
  await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
  expect(calls.length).toBe(4)
  await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
  expect(calls.length).toBe(5)
  client.clear()
})
