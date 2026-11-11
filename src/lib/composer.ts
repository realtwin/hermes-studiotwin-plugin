import * as sdk from '@hermes/plugin-sdk'
const { host } = sdk

/** Call only after asserting the originating profile/connection scope.
 * Missing host owner metadata uses active; fresh drafts try new then active.
 * Explicit owners never fall back to another chat, even if not visible.
 */
export function submitTranscript(sessionId: string | null | undefined, text: string): boolean {
  if (typeof sessionId === 'string') {
    return sessionId.trim().length > 0 && Boolean(host.composer?.submit(sessionId, text))
  }
  if (sessionId === null && host.composer?.submit('new', text)) return true
  return Boolean(host.composer?.submit(null, text))
}
