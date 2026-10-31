// @vitest-environment node
import { expect, it } from 'vitest'
import { expect as pw } from '@playwright/test'
import { openVisual, upload } from './bundle-harness'
import { cleanDisplayName, filterPillStyle, tabButtonStyle } from '../../src/lib/ui-tokens'

it('cleans only complete cache prefixes, preserving ordinary names and short IDs', () => {
  expect(cleanDisplayName('d868939e936a47448ef9944178114dc0-static-cube.glb')).toEqual({ title: 'static-cube.glb', shortId: 'd868939e' })
  expect(cleanDisplayName('000a55e7-0000-4000-8000-8b101de30738-concept.png')).toEqual({ title: 'concept.png', shortId: '000a55e7' })
  for (const name of ['hero-reference.png', '1234-concept.png', '000a55e7-0000-4000-8000-broken-concept.png'])
    expect(cleanDisplayName(name)).toEqual({ title: name, shortId: '' })
  expect(filterPillStyle(true).background).not.toBe(filterPillStyle(false).background)
  expect(tabButtonStyle(true).color).not.toBe(tabButtonStyle(false).color)
})

it('production bundle: active pills, channel/geometry controls, env reset, responsive concepts and raw filenames', async () => {
  const h = await openVisual(), { page } = h
  try {
    const image = await upload(h, 'image/concept-64.png')
    const env = await upload(h, 'env/equirect-64x32.hdr')
    await page.evaluate(() => (window as any).workspace())
    for (const theme of ['light', 'dark']) {
      await page.addStyleTag({ content: `:root { --ui-bg:${theme === 'light' ? '#fafafa' : '#15181e'}; --ui-bg-card:var(--ui-bg); --ui-bg-secondary:${theme === 'light' ? '#e9edf4' : '#1c222b'}; --ui-accent:${theme === 'light' ? '#285dd6' : '#8bb2ff'}; --ui-text:${theme === 'light' ? '#172033' : '#e3e9f4'}; --ui-text-primary:var(--ui-text); --ui-text-secondary:var(--ui-text); --ui-stroke-secondary:var(--ui-text) }` })
      const library = page.getByRole('tab', { name: 'Library', exact: true })
      await library.click()
      await pw(page.getByRole('button', { name: 'crate.glb', exact: true })).toBeVisible()
      const colors = await page.getByRole('tablist').getByRole('tab').evaluateAll(nodes => nodes.map(n => ({ active:n.getAttribute('aria-selected'), bg:getComputedStyle(n).backgroundColor, fg:getComputedStyle(n).color })))
      expect(colors.find(c => c.active === 'true')?.bg).not.toBe(colors.find(c => c.active === 'false')?.bg)
      expect(colors.find(c => c.active === 'true')?.fg).not.toBe(colors.find(c => c.active === 'true')?.bg)
      await pw(page.getByRole('button', { name: image.split('/').at(-1)!, exact: true })).toBeVisible()
      await page.getByRole('tab', { name: 'Concepts', exact: true }).click()
      await page.getByRole('button', { name: 'Hero study', exact: true }).click()
      const detail = page.getByRole('region', { name: 'Concept detail' })
      await pw(detail).toBeVisible()
      const cols = await detail.evaluate(n => getComputedStyle(n.parentElement!).gridTemplateColumns.split(' ').length)
      expect(cols).toBe(2)
      await page.setViewportSize({ width: 480, height: 900 })
      await pw.poll(() => detail.evaluate(n => getComputedStyle(n.parentElement!).gridTemplateColumns.split(' ').length)).toBe(1)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
      await page.setViewportSize({ width: 1440, height: 1100 })
    }
    await page.evaluate((path) => (window as any).renderDirective('material', { maps:JSON.stringify({ albedo:{path} }) }), image)
    await page.getByRole('button', { name:'Load material', exact:true }).click()
    const cube = page.getByRole('button', { name:'Cube', exact:true })
    await cube.click()
    await pw(cube).toHaveAttribute('aria-pressed', 'true')
    await pw(page.getByLabel('Geometry', { exact:true })).toHaveValue('Cube')
    const albedo = page.getByRole('button', { name:'Albedo', exact:true })
    await albedo.click()
    await pw(albedo).toHaveAttribute('aria-pressed', 'true')
    await pw(page.getByLabel('Map channel', { exact:true })).toHaveValue('albedo')
    await pw(page.getByRole('button', { name:'Heightmap', exact:true })).toBeDisabled()
    await page.evaluate((path) => (window as any).renderDirective('env', {path}), env)
    await page.getByRole('button', { name:'Load environment', exact:true }).click()
    await page.getByRole('button', { name:'Auto-rotate', exact:true }).click()
    await pw(page.getByRole('button', { name:'Auto-rotate', exact:true })).toHaveAttribute('aria-pressed', 'true')
    await page.getByRole('button', { name:'Reset view', exact:true }).click()
    await pw(page.getByRole('button', { name:'Auto-rotate', exact:true })).toHaveAttribute('aria-pressed', 'false')
    expect(h.errors).toEqual([])
    expect((await h.state()).submissions).toEqual([])
  } finally { await h.close() }
}, 120000)
