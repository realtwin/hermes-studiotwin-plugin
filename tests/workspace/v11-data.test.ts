import { expect, it } from 'vitest'
import { cleanDisplayName } from '../../src/lib/ui-tokens'
import * as data from '../../src/pages/workspace-data'
import { jobPrompt, jobMetadata, jobToolLabel } from '../../src/pages/jobs-tab'

const uuid = '01d1d8fc-bbe5-4db7-8134-b297b065e1ca'
const directory = 's3://rt-vp-cloud/jobs-dev/20261019/job/'
const channels = ['basecolor', 'normal', 'roughness', 'metalness', 'height']
const siblings = channels.map((c, i) => ({ uuid: `${uuid}-${i}`, type: 'image', s3Uri: `${directory}patina-${c}.png` }))
it('V11: strips suffix IDs without losing leading-cache compatibility', () => {
  expect(cleanDisplayName(`mod1_chassis_001.png@${uuid}`)).toEqual({ title: 'mod1_chassis_001.png', shortId: '01d1d8fc' })
  expect(cleanDisplayName(`${uuid}-crate.glb`).title).toBe('crate.glb')
  expect(data.assetSource({ uuid, name: `crate.glb@${uuid}` })).toMatchObject({ asset: uuid, name: 'crate.glb' })
})
it('V11: names nameless cloud assets from S3 and shortens generated identifiers', () => {
  expect(data.assetDisplayName({ uuid, s3Uri: directory + 'patina-basecolor.png' }).title).toBe('patina-basecolor.png')
  expect(data.assetDisplayName({ uuid, type: 'image', extension: 'png', s3Uri: directory + `openai_${uuid}_0.png` }).title).toBe('Image · 01d1d8fc.png')
  expect(data.assetDisplayName({ uuid, type: 'image', extension: 'png' }).title).toBe('Image · 01d1d8fc.png')
})
it('V11: classifies real cloud HDR/EXR and PBR image records, preserving explicit non-image types', () => {
  for (const row of [{ extension: 'hdr' }, { s3Uri: directory + 'panorama.exr?download=1' }, { s3Uri: 's3://bucket/panoramas/uuid/data' }])
    expect(data.modality({ type: 'image', ...row })).toBe('environment')
  for (const row of siblings) expect(data.modality(row)).toBe('material')
  expect(data.modality({ ...siblings[0], type: '3d_model' })).toBe('3d_model')
})
it('V11: assembles all five siblings without mixing folders or stems or overriding explicit maps', () => {
  const others = [{ uuid: 'wrong', s3Uri: directory + 'other-normal.png' }, { uuid: 'wrong2', s3Uri: directory + 'nested/patina-height.png' }]
  const maps = data.siblingMaterialMaps(siblings[1], [...others, ...siblings])
  expect(Object.keys(maps).sort()).toEqual(['albedo', 'heightmap', 'metalness', 'normal', 'roughness'])
  expect(maps.albedo).toMatchObject({ asset: siblings[0].uuid })
  expect(maps.heightmap).toMatchObject({ asset: siblings[4].uuid })
  const explicit = { albedo: { asset: 'explicit' } }
  expect(data.siblingMaterialMaps({ ...siblings[0], maps: explicit }, siblings)).toBe(explicit)
})
it('V11: job prompt fallbacks, rig metadata, timings and friendly labels preserve provider detail', () => {
  expect(jobPrompt({ outputs: { prompt: { user: 'Cloud prompt' } } })).toBe('Cloud prompt')
  expect(jobPrompt({ prompt: 'Legacy prompt' })).toBe('Legacy prompt')
  expect(jobMetadata({ inputs: { size: '1024x1024', quality: 'high' }, outputs: { processingTime: '11s', riggable: true, rigType: 'avian' } })).toEqual(['Generation: 11s', '1024x1024', 'high', 'riggable: avian'])
  expect(jobToolLabel('openai-gpt-image-2-v4-fn')).toBe('Image / Concept')
})
