// @vitest-environment jsdom
import { expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LibraryTab } from '../../src/pages/library-tab.tsx';
it('keeps local assets visible and explicitly labels a partial cloud-unavailable inventory', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const rest = vi.fn(async () => ({ assets: [{ type: '3d_model', path: '/cache/local.glb', name: 'Local model' }], partial: true, cloud_status: 'unavailable', next_offset: null }));
  const scope = { key: 'test', current: () => true, rest } as any;
  try {
    render(createElement(QueryClientProvider, { client }, createElement(LibraryTab, { scope, onInspect: vi.fn() })));
    expect(await screen.findByRole('button', { name: 'Local model' })).toBeTruthy();
    expect(screen.queryByRole('alert')).not.toBeNull();
    expect(screen.getByRole('alert').textContent).toMatch(/cloud.*unavailable.*partial|partial.*cloud.*unavailable/i);
    expect(screen.getByRole('alert').textContent).toMatch(/refresh/i);
  } finally { cleanup(); client.clear(); }
});
