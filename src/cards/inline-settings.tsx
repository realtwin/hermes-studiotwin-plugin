import * as sdk from '@hermes/plugin-sdk'
import { cloneElement, isValidElement, type ReactNode } from 'react'
import { useMediaScope } from './next-actions.ts'
import { connectSettings, useStudioTwinSettings } from './settings.ts'
function InlineSettings({ctx, render, props, directive}: {
  ctx: sdk.PluginContext; render: (p: any) => ReactNode; props: any; directive: boolean
}) {
  const {scope, stale} = useMediaScope(ctx)
  const settings = useStudioTwinSettings(scope)
  const fallback = directive ? <p>{props.source}</p> : props.fallback
  if (stale || !settings.inline_cards) return <>{fallback}</>
  const child = render(props)
  // Only rich card elements receive viewer options; preserve host fallback identity/props.
  if (!isValidElement(child) || typeof child.type === 'string' || child === fallback || child === props.fallback) return <>{child}</>
  return cloneElement(child as React.ReactElement<{webgl_limit?: number; auto_rotate?: boolean}>, {
    webgl_limit: settings.webgl_limit, auto_rotate: settings.auto_rotate,
  })
}
/** Decorate only transcript registrations. Routes/chrome keep their native behavior.
 * The callback is evaluated inside a mounted component, never a registration-time snapshot.
 */
export function inlineSettingsContext(ctx: sdk.PluginContext): sdk.PluginContext {
  connectSettings(ctx)
  return {
    ...ctx,
    register: contribution => {
      const data = contribution.data as {render?: (p: any) => ReactNode; name?: string; tools?: string[]} | undefined
      if (!data?.render || (!data.name?.startsWith('studiotwin-') && !data.tools)) return ctx.register(contribution)
      const render = data.render
      return ctx.register({...contribution, data: {...data, render: (props: any) =>
        <InlineSettings ctx={ctx} render={render} props={props} directive={Boolean(data.name)} />}})
    },
  }
}
