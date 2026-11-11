import { expect, it } from 'vitest'
import { normalizeSettings } from '../../src/cards/settings'
it('uses manifest defaults for missing and malformed settings', () => {
  expect(normalizeSettings(undefined)).toEqual({inline_cards:true, auto_rotate:true, webgl_limit:4, gallery_limit:24})
  expect(normalizeSettings({inline_cards:'false',auto_rotate:0,webgl_limit:NaN,gallery_limit:Infinity})).toEqual(normalizeSettings(null))
})
it('preserves booleans and clamps finite integer settings to manifest ranges', () => {
  expect(normalizeSettings({inline_cards:false,auto_rotate:false,webgl_limit:99,gallery_limit:-2})).toEqual({inline_cards:false,auto_rotate:false,webgl_limit:4,gallery_limit:1})
  expect(normalizeSettings({webgl_limit:0,gallery_limit:1000})).toMatchObject({webgl_limit:1,gallery_limit:100})
  expect(normalizeSettings({webgl_limit:2.8,gallery_limit:7.9})).toMatchObject({webgl_limit:2,gallery_limit:7})
})
