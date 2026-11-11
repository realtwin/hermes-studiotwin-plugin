import * as sdk from '@hermes/plugin-sdk'
import type { MediaScope } from '../cards/next-actions.ts'
import { assetId, list, type Row } from './workspace-data.ts'

/** Share the complete, scope-owned library between browsing and environment selection. */
export function useAssetLibrary(scope: MediaScope, enabled = true) {
  const query = sdk.useQuery<{ assets: Row[]; partial: boolean }>({
    queryKey: ['studiotwin-workspace', scope.key, 'complete-library'],
    queryFn: async () => {
      const rows = new Map<string, Row>()
      let partial = false
      let offset = 0
      for (;;) {
        const page = await scope.rest<Row>(`/assets?limit=100&offset=${offset}`)
        partial ||= page.partial === true
        for (const row of list(page, 'assets')) rows.set(assetId(row) ?? row.path, row)
        if (page.next_offset === null) return { assets: [...rows.values()], partial }
        if (!Number.isInteger(page.next_offset) || page.next_offset <= offset)
          throw Error('Invalid asset pagination; refresh the library to retry.')
        offset = page.next_offset
      }
    },
    enabled: enabled && scope.current(), retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false
  })
  return { ...query, data: query.data?.assets, partial: query.data?.partial === true }
}
