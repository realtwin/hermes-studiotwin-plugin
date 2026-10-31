import * as sdk from '@hermes/plugin-sdk'
import { modelScopeKey } from '../viewers/model-source.ts'
import { useWorkspaceQuery } from '../pages/workspace-data.ts'
import type { MediaScope } from './next-actions.ts'
export const DEFAULT_SETTINGS = { inline_cards: true, auto_rotate: true, webgl_limit: 4, gallery_limit: 24 }
export function normalizeSettings(value: unknown): typeof DEFAULT_SETTINGS {
  const row = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const integer = (key: 'webgl_limit' | 'gallery_limit', max: number) => {
    const v = row[key]
    return typeof v === 'number' && Number.isFinite(v) ? Math.max(1, Math.min(max, Math.trunc(v))) : DEFAULT_SETTINGS[key]
  }
  return {
    inline_cards: typeof row.inline_cards === 'boolean' ? row.inline_cards : true,
    auto_rotate: typeof row.auto_rotate === 'boolean' ? row.auto_rotate : true,
    webgl_limit: integer('webgl_limit', 4), gallery_limit: integer('gallery_limit', 100),
  }
}
// Same scoped query/cache as workspace and chrome. No cross-profile singleton values.
export function useStudioTwinSettings(scope: MediaScope) {
  return normalizeSettings(useWorkspaceQuery(scope, '/status', scope.current(), 30000).data?.settings)
}
const connected = new WeakSet<sdk.PluginContext>()
export function connectSettings(ctx: sdk.PluginContext) {
  if (connected.has(ctx)) return
  connected.add(ctx)
  ctx.onEvent('plugin.hermes-studiotwin.settings.changed', () => {
    void sdk.queryClient.invalidateQueries({ queryKey: ['studiotwin-workspace', modelScopeKey(sdk.host.state), '/status'] })
  })
}
