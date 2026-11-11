/** Captured catalog prices, checked against tools-list-summary.v1.json in tests.
 * These are display hints, never authorization to submit a paid job.
 */
export const NEXT_ACTION_COSTS = {
  studiotwin_conceptlab_edit: null,
  'image-to-3d-mesh': 25,
  'tripo-image-to-3d-mesh': null,
  'image-to-environment-map': 25,
  'image-to-material': null,
  'environment-map-upscale-cpu': null,
  'pano-sticker-placement': 1,
  'pano-stickers': null,
  'environment-map-to-world': 80,
  'texture-to-material': 20,
} as const
export type NextActionTool = keyof typeof NEXT_ACTION_COSTS
export const costLabel = (tool: NextActionTool) =>
  NEXT_ACTION_COSTS[tool] === null ? 'estimate in chat' : `${NEXT_ACTION_COSTS[tool]} cr`
export const costHint = (tool: NextActionTool) =>
  NEXT_ACTION_COSTS[tool] === null ? 'estimate first' : `${NEXT_ACTION_COSTS[tool]} cr`
