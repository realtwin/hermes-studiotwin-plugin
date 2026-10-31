// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
vi.mock('@hermes/plugin-sdk', () => ({
  TOOL_MEDIA_RENDERER_AREA: 'transcript.toolMedia', TRANSCRIPT_DIRECTIVE_AREA: 'transcript.directives',
  host: { state: {} }, Button: () => null,
}))
import { registerImageCards } from '../../src/cards/image-card.tsx'
import { registerVideoCards } from '../../src/cards/video-card.tsx'
import { registerEnvCards, nextEnvActions, workflowMessage } from '../../src/cards/env-card.tsx'
import { registerMaterialCards, nextMaterialActions } from '../../src/cards/material-card.tsx'
import { registerModelCards } from '../../src/cards/model-card.tsx'
import { imageActions } from '../../src/cards/next-actions.ts'
import { NEXT_ACTION_COSTS } from '../../src/cards/action-costs.ts'
const catalog = JSON.parse(readFileSync('tests/fixtures/contracts/tools-list-summary.v1.json', 'utf8')).tools
const aliases = (name: string) => [...new Set([name, `mcp__studiotwin__${name}`, `mcp__studiotwin__${name.replace(/-/g, '_')}`, `mcp_studiotwin_${name.replace(/-/g, '_')}`])]
const rows: any[] = []
const ctx = { register: (r: any) => { rows.push(r); return () => {} } } as any
for (const register of [registerImageCards, registerVideoCards, registerEnvCards, registerMaterialCards, registerModelCards]) register(ctx)
const media = rows.filter(r => r.area === 'transcript.toolMedia')
const models = ['image-to-3d-mesh','tripo-image-to-3d-mesh','tripo-retopology','blender-auto-rig','tripo-auto-rig','tripo-rig-check','text-to-motion','text-to-motion-kimodo','text-to-motion-edit','text-to-motion-control','motion-stitch-single','environment-map-to-world']
const videos = ['image-to-3d-mesh','tripo-image-to-3d-mesh','text-to-motion','text-to-motion-kimodo','text-to-motion-edit','text-to-motion-control','environment-map-to-world']
const envs = ['text-to-environment-map','image-to-environment-map','environment-map-upscale-cpu','pano-sticker-placement','pano-stickers']
const materials = ['text-to-material','image-to-material','texture-to-material']
const images = ['openai-gpt-image-2-v4-fn','openai-gpt-image-1-v1-fn','concept-lab-img-fn', 'studiotwin_conceptlab_create_and_generate','studiotwin_conceptlab_generate','studiotwin_conceptlab_edit','studiotwin_conceptlab_get','studiotwin_conceptlab_get_status']
const tools: string[] = catalog.filter((t: any) => t.family === 'generation' || t.conceptPaid).map((t: any) => t.name)
// Also exercise retained transcript identifiers and read-only Concept results.
for (const name of images) if (!tools.includes(name)) tools.push(name)
tools.push('terminal', 'foreign-image-tool')
it.each(tools)('exclusive media ownership and registration aliases: %s', (tool) => {
  for (const toolName of aliases(tool)) {
    for (const [kind, name] of [['image','out.png'], ['image','out.hdr'], ['file','out.hdr'], ['file','out.exr'], ['video','out.mp4'], ['file','out.glb'], ['file','out.json'], ['file','out.zip'], ['audio','out.wav'], ['file','out.txt'], ['video','out.glb'], ['audio','out.json']]) {
      const result = { environment: { path: '/env.hdr' }, maps: { albedo: { path: '/albedo.png' } } }
      const props = { toolName, file: { kind, name, path: '/'+name }, result, args: {}, fallback: 'fallback', toolCallId: 'call' } as any
      const expected = kind === 'video' && videos.includes(tool) ? 'video'
        : kind === 'file' && /\.(glb|json)$/.test(name) && models.includes(tool) ? 'model'
        : (kind === 'image' || (kind === 'file' && /\.(hdr|exr|json)$/.test(name))) && envs.includes(tool) ? 'env'
        : (kind === 'image' || (kind === 'file' && /\.(json|zip)$/.test(name))) && materials.includes(tool) ? 'material'
        : kind === 'image' && images.includes(tool) ? 'image' : undefined
      const owners = media.filter(r => r.data.render(props) !== 'fallback').map(r => r.id)
      expect(owners, `${toolName} / ${kind} / ${name}`).toEqual(expected ? [`studiotwin-${expected}-media`] : [])
      for (const r of media.filter(r => r.id !== 'studiotwin-model-media')) {
        const claimsTool = r.data.tools.includes(toolName)
        const family = r.id.split('-')[1]
        const shouldClaim = ({image: images, video: videos, env: envs, material: materials} as Record<string,string[]>)[family].includes(tool)
        expect(claimsTool, `${r.id} / ${toolName}`).toBe(shouldClaim)
      }
    }
  }
})
it('all image, environment and material next-action prices match the captured fixedCost', () => {
  for (const [tool, cost] of Object.entries(NEXT_ACTION_COSTS)) {
    expect(cost).toBe(catalog.find((t: any) => t.name === tool)?.fixedCost)
  }
  expect(media.find(r => r.id === 'studiotwin-model-media').data.tools).toEqual(['mcp__studiotwin__*'])
  const actions = imageActions({ asset: 'source' })
  for (const a of actions) {
    const row = catalog.find((t: any) => t.name === a.tool)
    expect(row).toBeDefined()
    expect(a.cost).toBe(row.fixedCost)
    expect(a.cost_label).toBe(row.fixedCost === null ? 'estimate in chat' : `${row.fixedCost} cr`)
    expect(a.message).toContain('estimate the exact inputs with studiotwin_estimate_cost and ask me to approve')
    if (row.fixedCost === null) {
      expect(a.message).toContain('estimate first')
      expect(a.message).not.toMatch(/\d+ (credits|cr)/)
    }
  }
  for (const [label, tool] of [...nextEnvActions, ...nextMaterialActions]) {
    const row = catalog.find((t: any) => t.name === tool)
    expect(row).toBeDefined()
    expect(label).toContain(`(${row.fixedCost === null ? 'estimate in chat' : `${row.fixedCost} cr`})`)
    expect(workflowMessage({ asset: 'source' }, tool)).toContain('estimate the exact inputs with studiotwin_estimate_cost and ask me to approve')
    if (row.fixedCost === null) expect(workflowMessage({}, tool)).toContain('estimate first')
  }
})
