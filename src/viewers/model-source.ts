import type { PluginContext } from '@hermes/plugin-sdk'
export interface ModelSource {
  path?: string
  asset?: string
  name?: string
}
interface Atom<T> {
  get: () => T
  subscribe?: (fn: () => void) => () => void
}
export interface ModelScopeState {
  profile?: Atom<string>
  connectionId?: Atom<string | null>
}
export const modelScopeKey = (state?: ModelScopeState) =>
  JSON.stringify([state?.connectionId?.get() ?? null, state?.profile?.get() ?? 'default'])
/** Refuse before dispatch, and reject stale responses. ctx.rest resolves its destination synchronously. */
export function bindModelScope(rest: PluginContext['rest'], state?: ModelScopeState) {
  const key = modelScopeKey(state)
  const current = () => key === modelScopeKey(state)
  const assert = () => {
    if (!current()) throw new Error('Originating model scope is no longer selected')
  }
  const bound: PluginContext['rest'] = async (path, options) => {
    assert()
    const value = await rest(path, options)
    assert()
    return value as never
  }
  return {
    key,
    current,
    assert,
    rest: bound,
    watch(fn: () => void) {
      const unsubs = [state?.profile, state?.connectionId].map((a) =>
        a?.subscribe?.(() => {
          if (!current()) fn()
        })
      )
      return () => unsubs.forEach((u) => u?.())
    }
  }
}
export function fileQuery(source: ModelSource) {
  if (Boolean(source.path) === Boolean(source.asset)) throw new Error('Provide exactly one local path or asset UUID')
  return '/file?' + new URLSearchParams(source.path ? { path: source.path } : { asset: source.asset! }).toString()
}
export interface ModelFile {
  name: string
  bytes: number
  dataUrl: string
}
export function dataUrlBytes(url: string): ArrayBuffer {
  const comma = url.indexOf(',')
  if (comma < 0 || !url.startsWith('data:')) throw new Error('Invalid file response')
  const text = /;base64$/i.test(url.slice(0, comma))
    ? atob(url.slice(comma + 1))
    : decodeURIComponent(url.slice(comma + 1))
  return Uint8Array.from(text, (c) => c.charCodeAt(0)).buffer
}
export async function fetchModel(rest: PluginContext['rest'], source: ModelSource) {
  const f = await rest<ModelFile>(fileQuery(source), { timeoutMs: 180_000 })
  return { ...f, buffer: dataUrlBytes(f.dataUrl) }
}
