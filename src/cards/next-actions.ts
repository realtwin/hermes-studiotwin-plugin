import * as sdk from '@hermes/plugin-sdk'
import { submitTranscript } from '../lib/composer.ts'
import { NEXT_ACTION_COSTS, costLabel, costHint } from './action-costs.ts'
import { useEffect, useState } from 'react'
import { bindModelScope, type ModelSource } from '../viewers/model-source.ts'
export type MediaSource = ModelSource & { url?: string }
export type MediaScope = ReturnType<typeof bindModelScope>
export function useMediaScope(ctx: sdk.PluginContext, supplied?: MediaScope) {
  const [scope] = useState(() => {
    if (supplied) return supplied
    const base = bindModelScope(ctx.rest, sdk.host.state)
    let invalidated = false
    const assert = () => {
      if (invalidated) throw Error('Originating media scope changed')
      base.assert()
    }
    const rest: sdk.PluginContext['rest'] = async (path, options) => {
      assert()
      const value = await base.rest(path, options)
      assert()
      return value as never
    }
    return {
      ...base,
      assert,
      rest,
      current: () => !invalidated && base.current(),
      watch: (fn: () => void) =>
        base.watch(() => {
          invalidated = true
          fn()
        }),
    }
  })
  const [stale, setStale] = useState(!scope.current())
  useEffect(() => scope.watch(() => setStale(true)), [scope])
  return { scope, stale }
}
export function object(value: unknown): Record<string, any> {
  if (typeof value === 'string') {
    try {
      value = JSON.parse(value)
    } catch {
      return {}
    }
  }
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, any>) : {}
}
export function mediaQuery(source: MediaSource, raw = false) {
  if (Boolean(source.path) === Boolean(source.asset)) throw Error('Provide one path or asset')
  return (
    '/file?' +
    new URLSearchParams({
      ...(source.path ? { path: source.path } : { asset: source.asset! }),
      ...(raw ? { raw: '1' } : {}),
    })
  )
}
export function deliveryUrl(url: string) {
  if (!/^(https?:|data:|blob:)/i.test(url)) throw Error('Unsupported media URL')
  return url
}
/** resolveUrl belongs to Desktop, which may return its authenticated Electron media protocol. */
export function hostPlaybackUrl(url: string) {
  return /^hermes-media:\/\/(?:stream|remote)\//i.test(url) ? url : deliveryUrl(url)
}
export async function imageFile(scope: MediaScope, source: MediaSource) {
  scope.assert()
  if (source.url)
    return {
      dataUrl: deliveryUrl(source.url),
      name: source.name ?? 'StudioTwin image',
      bytes: undefined as number | undefined,
    }
  const file = await scope.rest<{ dataUrl: string; name: string; bytes: number }>(mediaQuery(source), {
    timeoutMs: 180000,
  })
  deliveryUrl(file.dataUrl)
  return file
}
export interface NextAction {
  id: string
  label: string
  cost?: number | null
  cost_label?: string
  tool?: string
  message: string
}
export function imageActions(source: MediaSource): NextAction[] {
  const ref = JSON.stringify(
    source.asset ? { asset: source.asset } : source.path ? { path: source.path } : { url: source.url },
  )
  return ([
    ['edit', 'Edit Concept Image', 'studiotwin_conceptlab_edit'],
    ['mesh', 'Convert Image to 3D Mesh', 'image-to-3d-mesh'],
    ['tripo', 'Convert Image to Tripo 3D Mesh', 'tripo-image-to-3d-mesh'],
    ['environment', 'Convert Image to 360° Environment', 'image-to-environment-map'],
    ['material', 'Convert Image to PBR Material', 'image-to-material'],
  ] as const).map(([id, label, tool]) => ({
    id: String(id),
    label: String(label),
    tool: String(tool),
    cost: NEXT_ACTION_COSTS[tool],
    cost_label: costLabel(tool),
    message: `StudioTwin source ${ref}: ${label} using ${tool} (${costHint(tool)}). Read the live tool schema, verify compatibility, estimate the exact inputs with studiotwin_estimate_cost and ask me to approve the cost before submitting.${source.path ? ' Ask before uploading this local file.' : ''}`,
  }))
}
export function submitNext(scope: MediaScope, sessionId: string | null | undefined, action: NextAction) {
  scope.assert()
  if (!submitTranscript(sessionId, action.message)) {
    sdk.host.notify({ kind: 'warning', message: 'Open the originating chat to continue this workflow.' })
    return false
  }
  return true
}
export function saveUrl(scope: MediaScope, url: string, name: string) {
  scope.assert()
  const link = document.createElement('a')
  link.href = deliveryUrl(url)
  link.download = name
  link.click()
}
