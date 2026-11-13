// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PluginContext } from '@hermes/plugin-sdk'
const owner = vi.hoisted(() => ({ stale: false }))
vi.mock('@hermes/plugin-sdk', async () => {
  const query = await import('@tanstack/react-query')
  const { createElement } = await import('react')
  return { ...query, host: { composer: {} }, Button: ({ size, variant, ...props }: any) => createElement('button', props),
    Badge: ({ variant, ...props }: any) => createElement('span', props), Codicon: () => null }
})
vi.mock('../../src/cards/next-actions.ts', async importOriginal => {
  const actual = await importOriginal<typeof import('../../src/cards/next-actions.ts')>()
  return { ...actual, useMediaScope: (ctx: any) => ({ scope: ctx.scope, stale: owner.stale }) }
})
vi.mock('../../src/cards/settings.ts', () => ({ useStudioTwinSettings: () => ({ gallery_limit: 24 }) }))
import { jobStatus, TaskCard } from '../../src/cards/task-card.tsx'
import { normalizedJobs, JobsTab } from '../../src/pages/jobs-tab.tsx'
function setup(rest: (path: string, options?: any) => Promise<any>) {
  const scope = { key: 'task-test', rest: vi.fn(rest), assert: () => {}, current: () => true }
  const ctx = { scope } as unknown as PluginContext
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const mount = (element: ReturnType<typeof createElement>) => render(createElement(QueryClientProvider, { client }, element))
  return { scope, ctx, client, mount }
}
afterEach(() => { cleanup(); owner.stale = false })
it.each([undefined, null, '', 'provider-new-state', {}, 42])('unknown job status %j safely defaults to queued at both consumers', raw => {
  expect(jobStatus(raw)).toBe('queued')
  expect(normalizedJobs([{ id: 'one', status: raw }])[0].status).toBe('queued')
})
it.each([['success', 'completed'], ['in-progress', 'running'], ['processing', 'running'], ['draft', 'queued'], ['canceled', 'cancelled'], ['error', 'failed']])('renders normalized %s as phase %s with existing task marker', async (raw, phase) => {
  const { ctx, mount } = setup(async () => ({ status: raw }))
  const view = mount(createElement(TaskCard, { ctx, id: 'one', pollInterval: 60000 }))
  await waitFor(() => expect(view.container.querySelector('article')?.getAttribute('data-task-phase')).toBe(phase))
  expect(view.container.querySelector('article')?.getAttribute('data-studiotwin-task')).toBe(phase)
  if (['completed', 'cancelled', 'failed'].includes(phase)) expect(screen.queryByRole('progressbar')).toBeNull()
})
it('renders loading then cancelling while preserving queued marker and disabling duplicate cancel', async () => {
  let release!: (v: any) => void
  const { ctx, mount } = setup(async (path) => path === '/cancel' ? new Promise(resolve => { release = resolve }) : { status: 'queued' })
  const view = mount(createElement(TaskCard, { ctx, id: 'one', pollInterval: 60000 }))
  expect(view.container.querySelector('article')?.getAttribute('data-task-phase')).toBe('loading')
  const cancel = await screen.findByRole('button', { name: 'Cancel queued job' })
  fireEvent.click(cancel)
  await waitFor(() => expect(view.container.querySelector('article')?.getAttribute('data-task-phase')).toBe('cancelling'))
  expect(view.container.querySelector('article')?.getAttribute('data-studiotwin-task')).toBe('queued')
  expect((cancel as HTMLButtonElement).disabled).toBe(true)
  release({ status: 'cancelled' })
  await waitFor(() => expect(view.container.querySelector('article')?.getAttribute('data-task-phase')).toBe('cancelled'))
})
it('completion retires a cancellation warning and its alert', async () => {
  let status = 'queued'
  const { ctx, mount, client } = setup(async path => {
    if (path === '/cancel') throw new Error('not confirmed')
    return { status }
  })
  const view = mount(createElement(TaskCard, { ctx, id: 'one', pollInterval: 60000 }))
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel queued job' }))
  await screen.findByRole('alert')
  status = 'completed'
  await client.invalidateQueries({ queryKey: ['studiotwin'] })
  await waitFor(() => expect(view.container.querySelector('article')?.getAttribute('data-task-phase')).toBe('completed'))
  expect(screen.queryByText(/Cancellation could not be confirmed/)).toBeNull()
})
it('stale task fallback has an explicit stale phase without exposing active controls', () => {
  owner.stale = true
  const { ctx, mount } = setup(async () => ({ status: 'queued' }))
  const view = mount(createElement(TaskCard, { ctx, id: 'one' }))
  expect(view.container.querySelector('[data-task-phase="stale"]')).toBeTruthy()
  expect(screen.getByRole('alert').textContent).toMatch(/originating profile/)
  expect(screen.queryByRole('button')).toBeNull()
})
it('JobsTab treats unknown provider states as cancellable active jobs', async () => {
  const { scope, mount } = setup(async () => ({ jobs: [{ id: 'one', status: 'future-state', tool: 'image' }] }))
  mount(createElement(JobsTab, { scope: scope as any, configured: true, onInspect: vi.fn() }))
  fireEvent.click(screen.getByRole('button', { name: 'Active' }))
  expect(await screen.findByRole('button', { name: 'Cancel queued job' })).toBeTruthy()
  expect(screen.getByRole('progressbar', { name: 'Job progress' })).toBeTruthy()
})
it('JobsTab keeps every row and explains omitted oversized inputs per row', async () => {
  const { scope, mount } = setup(async () => ({ jobs: [
    { id: 'oversized', status: 'failed', inputs_truncated: true, inputs: { prompt: 'Still usable prompt' } },
    { id: 'ordinary', status: 'done', inputs: { prompt: 'Other job' } },
  ] }))
  mount(createElement(JobsTab, { scope: scope as any, configured: true, onInspect: vi.fn() }))
  expect(await screen.findByText('Inputs too large to display. Large input values were omitted.')).toBeTruthy()
  expect(screen.getByText('Still usable prompt')).toBeTruthy()
  expect(screen.getByText('Other job')).toBeTruthy()
  expect(screen.queryByText('Could not load jobs.')).toBeNull()
})
