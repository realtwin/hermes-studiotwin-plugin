import type { PluginContext } from '@hermes/plugin-sdk'
import type { ModelSource } from './model-source.ts'
import type { MultiviewCapture } from './model-stage.ts'

export function multiviewFilename(source: ModelSource, capture: MultiviewCapture) {
  const raw = (source.name || source.path?.split(/[\\/]/).pop() || 'model').replace(/\.[^.]+$/, '')
  const stem = raw.replace(/[^A-Za-z0-9_-]/g, '-').slice(0, 64) || 'model'
  return `${stem}-multiview-${capture.views.length}v-${capture.shading}.png`
}
export async function stageMultiview(rest: PluginContext['rest'], source: ModelSource, capture: MultiviewCapture, sessionId?: string | null) {
  // Caller supplies the originating scope-bound REST function. No cloud upload, no generation.
  const filename = multiviewFilename(source, capture)
  const upload = await rest<{ path: string }>('/upload', {
    method: 'POST', body: { filename, data: capture.sheetDataUrl.split(',')[1], cloud: false }
  })
  if (!upload || typeof upload.path !== 'string' || !upload.path) throw new Error('Local staging returned no file path')
  const id = crypto.randomUUID()
  await rest('/provenance', {
    method: 'POST', body: {
      id, tool: 'capture-multiview', ...(sessionId ? { session_id: sessionId } : {}),
      ...(source.asset ? { sourceAssetIds: [source.asset] } : {}),
      prompt: `Multiview sheet ${JSON.stringify(upload.path)} (${capture.views.length} views, ${capture.shading}). Made from source 3D model ${JSON.stringify(source)}.`
    }
  })
  return { path: upload.path, id, filename }
}
export function reskinPrompt(source: ModelSource, sheet: string) {
  return `Reskin this 3D model using a Forge-E style structure-locked multiview workflow. Source 3D model: ${JSON.stringify(source)}. Local multiview reference sheet: ${JSON.stringify(sheet)}. First inspect the sheet as pixels; the viewer alone is not model observation. Ask me for the intended visual changes. Use ConceptLab / openai-gpt-image-2-v4-fn to edit the multiview reference, preserving geometry, silhouettes, camera angles and tile layout. Review the edited sheet before reconstructing with image-to-3d-mesh or tripo-image-to-3d-mesh; read the live schemas and choose compatible image inputs rather than assuming a contact sheet is directly supported. Estimate the exact credits for each paid stage and ask me to approve before submitting. Ask before uploading any local reference or source model to the cloud. Do not auto-submit, auto-retry or overwrite the source model; reconstruction is not guaranteed to preserve topology, rig or exact geometry.`
}
