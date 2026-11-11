// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { AssetInspector } from '../../src/pages/asset-inspector.tsx';

const queries = vi.hoisted(() => new Map<string, Record<string, any>>());
const requests = vi.hoisted(() => [] as { path: string; enabled: boolean }[]);
vi.mock('../../src/pages/workspace-data.ts', async importOriginal => ({
  ...await importOriginal<typeof import('../../src/pages/workspace-data.ts')>(),
  useWorkspaceQuery: (_scope: unknown, path: string, enabled = true) => {
    requests.push({ path, enabled });
    return queries.get(path) ?? {};
  },
}));
vi.mock('../../src/cards/settings.ts', () => ({ useStudioTwinSettings: () => ({ auto_rotate: false }) }));
vi.mock('../../src/pages/asset-library.ts', () => ({ useAssetLibrary: () => ({ data: [] }) }));
vi.mock('../../src/viewers/image-viewer.tsx', () => ({ ImageViewer: ({ source }: any) => createElement('div', { 'data-testid': 'image-preview' }, JSON.stringify(source)) }));

const scope = { key: 'inspector-test', current: () => true, assert: () => {}, rest: vi.fn() } as any;
const close = vi.fn();
function mount(selected: Record<string, any>) {
  const props = { ctx: {} as any, scope, selected, onClose: close, session: 'origin-chat', limit: 1 };
  const view = render(createElement(AssetInspector, props));
  return { ...view, update: () => view.rerender(createElement(AssetInspector, props)) };
}
function dialog() { return screen.getByRole('dialog', { name: 'Asset inspection' }); }

it('downloads the scoped cached original rather than an expired URL and reports backend failures', async () => {
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const create = vi.fn(() => 'blob:cached-original');
  const priorCreate = URL.createObjectURL, priorRevoke = URL.revokeObjectURL;
  URL.createObjectURL = create; URL.revokeObjectURL = vi.fn();
  scope.rest.mockReset().mockResolvedValue({ name: 'cached.png', dataUrl: 'data:image/png;base64,aGVsbG8=', bytes: 5 });
  try {
    mount({ type: 'image', path: '/local/cached.png', downloadUrl: 'https://expired.invalid/file.png', name: 'Cached' });
    fireEvent.click(screen.getByRole('button', { name: 'Download original' }));
    await waitFor(() => expect(scope.rest).toHaveBeenCalledWith(expect.stringContaining('path=%2Flocal%2Fcached.png'), expect.objectContaining({ timeoutMs: 180000 })));
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect((click.mock.instances[0] as HTMLAnchorElement).href).toBe('blob:cached-original');
    scope.rest.mockRejectedValueOnce(Error('backend unavailable'));
    fireEvent.click(screen.getByRole('button', { name: 'Download original' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/download unavailable.*refresh|download unavailable.*retry/i));
    expect(click).toHaveBeenCalledOnce();
  } finally {
    click.mockRestore(); URL.createObjectURL = priorCreate; URL.revokeObjectURL = priorRevoke;
  }
});
beforeEach(() => { queries.clear(); requests.length = 0; close.mockClear(); });
afterEach(cleanup);

it('requests continuation for a URL-backed output using job identity, never an invented asset identity', () => {
  mount({ type: 'image', jobId: 'job-output-id', path: '/cache/output.png' });
  expect(requests.find(r => r.path === '/actions?id=job-output-id&type=job')?.enabled).toBe(true);
});

it('exposes ready local modality and preserves the selected preview and accessible controls', () => {
  mount({ type: 'image', path: '/local/reference.png', name: 'Reference' });
  expect(dialog().getAttribute('data-inspector-state')).toBe('ready');
  expect(dialog().getAttribute('data-inspector-modality')).toBe('image');
  expect(screen.getByTestId('image-preview').textContent).toContain('/local/reference.png');
  expect(within(dialog()).getByRole('button', { name: 'Close asset inspection' })).toBeTruthy();
  expect(requests.find(r => r.path === '/assets/')?.enabled).toBe(false);
});

it('keeps cloud selection preview ready while detail metadata is loading', () => {
  queries.set('/assets/cloud-image', { isLoading: true });
  mount({ uuid: 'cloud-image', type: 'image', name: 'Selected fallback' });
  expect(dialog().getAttribute('data-inspector-state')).toBe('ready');
  expect(screen.getByTestId('image-preview').textContent).toContain('cloud-image');
  expect(screen.queryByRole('alert')).toBeNull();
});

it('warns explicitly on failed detail resolution without discarding selected fallback', () => {
  queries.set('/assets/cloud-image', { isError: true });
  mount({ uuid: 'cloud-image', type: 'image', name: 'Selected fallback' });
  expect(dialog().getAttribute('data-inspector-state')).toBe('ready');
  expect(screen.getByRole('alert').textContent).toMatch(/detail|resolv/i);
  expect(screen.getByRole('heading', { name: 'Selected fallback' })).toBeTruthy();
  expect(screen.getByTestId('image-preview').textContent).toContain('cloud-image');
});

it('merges resolved cloud details and exposes their effective modality', () => {
  queries.set('/assets/cloud-image', { data: { type: 'image', name: 'Resolved image' } });
  mount({ uuid: 'cloud-image', type: 'unknown', name: 'Selected fallback' });
  expect(dialog().getAttribute('data-inspector-state')).toBe('ready');
  expect(dialog().getAttribute('data-inspector-modality')).toBe('image');
  expect(screen.getByRole('heading', { name: 'Resolved image' })).toBeTruthy();
  expect(screen.getByTestId('image-preview').textContent).toContain('cloud-image');
});

it('exposes a rig-check summary including a negative compatibility result', () => {
  mount({ type: 'rig_check', riggable: false, name: 'Rig result' });
  expect(dialog().getAttribute('data-inspector-state')).toBe('rig_check_summary');
  expect(dialog().getAttribute('data-inspector-modality')).toBe('rig_check');
  expect(screen.getByText('Not riggable')).toBeTruthy();
  expect(screen.queryByTestId('image-preview')).toBeNull();
});

it('renders loading and error states for an unresolved job output without a misleading preview', () => {
  const path = '/jobs/job%2Fid/output';
  queries.set(path, { isLoading: true });
  const view = mount({ type: 'job_output', jobId: 'job/id', name: 'Completed job output' });
  expect(dialog().getAttribute('data-inspector-state')).toBe('loading_job_output');
  expect(within(dialog()).getByRole('status').textContent).toMatch(/loading.*output/i);
  expect(screen.queryByTestId('image-preview')).toBeNull();
  expect(requests.find(r => r.path === path)?.enabled).toBe(true);
  queries.set(path, { isError: true });
  view.update();
  expect(dialog().getAttribute('data-inspector-state')).toBe('job_output_error');
  expect(within(dialog()).getByRole('alert').textContent).toMatch(/output.*unavailable|could not.*output/i);
  expect(screen.queryByText('Preview unavailable. Download the original asset instead.')).toBeNull();
});

it('replaces an unresolved job output with the resolved target preview', () => {
  const path = '/jobs/job-id/output';
  queries.set(path, { isLoading: true });
  const view = mount({ type: 'job_output', jobId: 'job-id' });
  expect(dialog().getAttribute('data-inspector-state')).toBe('loading_job_output');
  queries.set(path, { data: { type: 'image', url: 'https://example.com/output.png', name: 'Resolved output' } });
  view.update();
  expect(dialog().getAttribute('data-inspector-state')).toBe('ready');
  expect(dialog().getAttribute('data-inspector-modality')).toBe('image');
  expect(screen.getByTestId('image-preview').textContent).toContain('https://example.com/output.png');
  expect(screen.getByRole('heading', { name: 'Resolved output' })).toBeTruthy();
});
