// Type-level contract for src/sdk.d.ts: compiled by `tsc -p tsconfig.json` (run from scaffold.test.ts),
// never imported at runtime. It uses the declarations the way later slices will, so a broken or
// drifting declaration fails typecheck here first. Uses SDK types only; no package module is imported.
import type {
  HermesPlugin,
  PluginContext,
  RouteContribution,
  SidebarNavContribution,
  ToolMediaRendererContribution,
  TranscriptDirectiveProps
} from '@hermes/plugin-sdk'
import { host, ROUTES_AREA, SIDEBAR_NAV_AREA, TOOL_MEDIA_RENDERER_AREA } from '@hermes/plugin-sdk'

const routes: 'routes' = ROUTES_AREA
const nav: 'sidebar.nav' = SIDEBAR_NAV_AREA

export const contractPlugin: HermesPlugin = {
  id: 'hermes-studiotwin',
  name: 'StudioTwin',
  register(ctx: PluginContext) {
    const route: RouteContribution = { path: '/studiotwin' }
    const item: SidebarNavContribution = { codicon: 'layers', label: 'StudioTwin', path: '/studiotwin' }
    ctx.registerMany([
      { id: 'route', area: routes, data: route, render: () => null },
      { id: 'nav', area: nav, data: item }
    ])
    if (TOOL_MEDIA_RENDERER_AREA !== undefined) {
      const media: ToolMediaRendererContribution = { tools: ['mcp__studiotwin__*'], render: props => props.fallback }
      ctx.register({ id: 'media', area: TOOL_MEDIA_RENDERER_AREA, data: media })
    }
    ctx.registerSettingsPage?.({ id: 'settings', title: 'StudioTwin', render: () => null })
    const stop = ctx.setInterval?.(() => undefined, 15_000)
    ctx.onDispose(() => stop?.())
  }
}

export function nextAction(props: TranscriptDirectiveProps, text: string): boolean {
  // Older hosts omit sessionId and the composer bus: degrade to "not sent" (DESIGN §4.3).
  const session = props.sessionId === undefined ? null : props.sessionId
  return host.composer?.submit(session, text) ?? false
}
