/** Unified Desktop entrypoint. Cloud tools connect directly through mcp.json;
 * this module only contributes UI, using the active plugin backend via ctx.rest.
 */
import * as sdk from '@hermes/plugin-sdk'
import { inlineSettingsContext } from './cards/inline-settings.tsx'
import { registerModelCards } from './cards/model-card.tsx'
import { registerAudioCards } from './cards/audio-card.tsx'
import { registerEnvCards } from './cards/env-card.tsx'
import { registerMaterialCards } from './cards/material-card.tsx'
import { registerImageCards } from './cards/image-card.tsx'
import { registerVideoCards } from './cards/video-card.tsx'
import { registerTaskCards } from './cards/task-card.tsx'
import { registerWorkspaceAndChrome } from './chrome/navigation.tsx'

const plugin: sdk.HermesPlugin = {
  id: 'hermes-studiotwin',
  name: 'StudioTwin Creative Suite',
  description: 'StudioTwin models, animation, environments, materials, images, audio and video in one creative workspace.',
  defaultEnabled: false,
  register(ctx) {
    const cards = inlineSettingsContext(ctx)
    registerModelCards(cards)
    registerAudioCards(cards)
    registerEnvCards(cards)
    registerMaterialCards(cards)
    registerImageCards(cards)
    registerVideoCards(cards)
    registerTaskCards(cards)
    registerWorkspaceAndChrome(ctx)
  },
}

// The pinned ambient contract predates this optional host registration door.
// Do not add a named ESM import: default-export hosts intentionally omit it.
;(sdk as typeof sdk & { registerPlugin?: (definition: sdk.HermesPlugin) => void }).registerPlugin?.(plugin)
export default plugin
