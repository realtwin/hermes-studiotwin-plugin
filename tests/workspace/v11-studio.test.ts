// @vitest-environment node
import { expect, it } from 'vitest'
import { expect as pw } from '@playwright/test'
import { mkdirSync, readFileSync, readdirSync } from 'node:fs'
import ts from 'typescript'
import { filterPillStyle, tabButtonStyle } from '../../src/lib/ui-tokens'
import { openVisual } from '../visual/bundle-harness'

it('V12 uses explicit SDK control hierarchy everywhere', () => {
  const missing: string[] = []
  for (const dir of ['src/pages', 'src/cards', 'src/viewers']) for (const file of readdirSync(dir).filter(f => f.endsWith('.tsx'))) {
    const source = ts.createSourceFile(file, readFileSync(`${dir}/${file}`, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    const visit = (node: ts.Node) => {
      if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        const name = node.tagName.getText(source)
        if (['sdk.Button', 'Button', 'sdk.Badge', 'Badge'].includes(name)) {
          const attrs = node.attributes.properties.filter(ts.isJsxAttribute).map(a => a.name.getText(source))
          if (!attrs.includes('variant') || (!name.endsWith('Badge') && !attrs.includes('size'))) missing.push(`${dir}/${file}:${source.getLineAndCharacterOfPosition(node.pos).line + 1} ${name}`)
        }
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
  }
  expect(missing).toEqual([])
})

it('V12 selection is soft and readable rather than primary blue with background-colored text', () => {
  expect(filterPillStyle(true).background).toContain('16%')
  expect(filterPillStyle(true).color).toBe('var(--ui-text-primary, var(--ui-text))')
  expect(tabButtonStyle(true).background).not.toContain('--ui-accent')
})

it('V12 production inspection rooms are achromatic in light and dark with dedicated right-hand Close controls', async () => {
  const h = await openVisual(), { page } = h
  try {
    await page.evaluate(() => (window as any).workspace())
    mkdirSync('.verification/v12', { recursive: true })
    for (const theme of ['light', 'dark']) {
      await page.addStyleTag({ content: `:root{--ui-bg:${theme === 'light' ? '#e8e0f0' : '#18102f'};--ui-bg-editor:var(--ui-bg);--ui-bg-secondary:${theme === 'light' ? '#d6e4ff' : '#10285a'};--ui-bg-elevated:${theme === 'light' ? '#dcbcff' : '#301060'};--ui-bg-card:var(--ui-bg-elevated);--ui-text:#888aff;--ui-text-primary:${theme === 'light' ? '#241238' : '#ece4ff'};--ui-text-secondary:var(--ui-text-primary);--ui-stroke-secondary:#697aaa;--ui-accent:#0053fd}body{background:var(--ui-bg);color:var(--ui-text-primary)}` })
      await page.getByRole('button', { name: 'hero-reference.png', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: 'Asset inspection', exact: true })
      const close = dialog.getByRole('button', { name: 'Close asset inspection', exact: true })
      await pw(close).toContainText('Close')
      await pw(close).toContainText('ESC')
      const neutral = async (locator: any) => {
        const colors = await locator.evaluate((node: HTMLElement) => {
          const c = document.createElement('canvas'); c.width = c.height = 1
          const g = c.getContext('2d')!
          return ['backgroundColor', 'color', 'borderTopColor'].map(key => {
            g.clearRect(0, 0, 1, 1); g.fillStyle = (getComputedStyle(node) as any)[key]; g.fillRect(0, 0, 1, 1)
            return Array.from(g.getImageData(0, 0, 1, 1).data)
          })
        })
        for (const [r, g, b, a] of colors) if (a) expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThanOrEqual(1)
      }
      await neutral(dialog); await neutral(close)
      expect(await dialog.evaluate(n => n.getAttribute('style'))).not.toContain('var(--ui-accent)')
      const roomStyles = await dialog.locator('[style]').evaluateAll(nodes => nodes.map(n => n.getAttribute('style')).join('\n'))
      expect(roomStyles).not.toContain('var(--ui-accent)')
      expect(roomStyles).not.toMatch(/#[\da-f]{3,8}\b|rgba?\(/i)
      await dialog.getByRole('button', { name: 'Inspect image', exact: true }).click()
      const lightbox = page.getByRole('dialog', { name: 'Image inspection', exact: true })
      const imageClose = lightbox.getByRole('button', { name: 'Close inspection', exact: true })
      await pw(imageClose).toContainText('ESC')
      await neutral(lightbox); await neutral(imageClose)
      await lightbox.getByRole('button', { name: '2×', exact: true }).click()
      await neutral(lightbox.getByRole('button', { name: '2×', exact: true }))
      expect((await imageClose.boundingBox())!.x).toBeGreaterThan((await lightbox.getByRole('button', { name: '1×', exact: true }).boundingBox())!.x)
      await page.screenshot({ path: `.verification/v12/image-${theme}.png` })
      await page.locator('[data-image-backdrop]').click({ position: { x: 2, y: 2 } })
      await pw(lightbox).toHaveCount(0)
      await pw(dialog).toBeVisible()
      await dialog.getByRole('button', { name: 'Inspect image', exact: true }).click()
      await page.setViewportSize({ width: 560, height: 760 })
      await pw(imageClose).toBeInViewport()
      expect((await imageClose.boundingBox())!.x).toBeGreaterThan((await lightbox.getByRole('button', { name: '1×', exact: true }).boundingBox())!.x)
      await page.screenshot({ path: `.verification/v12/image-narrow-${theme}.png` })
      await imageClose.press('Escape')
      await pw(lightbox).toHaveCount(0)
      await pw(dialog).toBeVisible()
      await pw(dialog.getByRole('button', { name: 'Inspect image', exact: true })).toBeFocused()
      await page.setViewportSize({ width: 1440, height: 1100 })
      await page.screenshot({ path: `.verification/v12/inspector-${theme}.png` })
      await close.click()
      await page.screenshot({ path: `.verification/v12/library-${theme}.png` })
    }
    expect(h.errors).toEqual([])
  } finally { await h.close() }
}, 90000)

it('V11 production bundle: cloud-shaped names, real image posters, HDR classification and five-channel sibling PBR inspection', async () => {
  const h = await openVisual(), { page } = h
  try {
    const ids = await fetch(h.url + '/__test/v11-cloud', { method: 'POST' }).then(r => r.json())
    await page.route('**/api/plugins/hermes-studiotwin/assets*', async route => {
      const response = await route.fetch(), body = await response.json()
      const transform = (r: any) => {
        if (Object.values(ids).includes(r.uuid)) { delete r.name; r.extension = r.uuid === ids.env ? 'hdr' : 'png' }
        else if (r.name === 'hero-reference.png') r.name += '@' + r.uuid
        return r
      }
      if (Array.isArray(body.assets)) body.assets = body.assets.map(transform)
      else transform(body)
      await route.fulfill({ response, json: body })
    })
    await page.evaluate(() => (window as any).workspace())
    await pw(page.getByRole('button', { name: ids.basecolor, exact: true })).toBeVisible()
    await pw(page.getByText('patina-basecolor.png', { exact: true })).toBeVisible()
    const poster = page.locator('[data-asset-poster="image"] img').first()
    await pw(poster).toBeVisible()
    expect(await poster.evaluate((n: HTMLImageElement) => n.complete && n.naturalWidth > 0)).toBe(true)
    for (const theme of ['light', 'dark']) {
      await page.addStyleTag({ content: `:root{--ui-bg-editor:${theme === 'light' ? '#f8fafc' : '#111827'};--ui-bg-elevated:var(--ui-bg-editor);--ui-bg-card:color-mix(in srgb, var(--ui-bg-editor) 8%, transparent);--ui-bg-secondary:${theme === 'light' ? '#e8edf3' : '#202c3c'};--ui-text-primary:${theme === 'light' ? '#162033' : '#e2e8f0'};--ui-text-secondary:var(--ui-text-primary);--ui-accent:#6794f7;--ui-stroke-secondary:#758295}body{background:var(--ui-bg-editor);color:var(--ui-text-primary)}` })
      await page.getByRole('button', { name: '360° Env', exact: true }).click()
      await page.getByRole('button', { name: ids.env, exact: true }).click()
      const dialog = page.getByRole('dialog', { name: 'Asset inspection', exact: true })
      await pw(dialog.getByRole('button', { name: 'Load environment', exact: true })).toBeVisible()
      expect(await dialog.evaluate(n => getComputedStyle(n).backgroundColor)).not.toMatch(/rgba\([^)]*, 0\)/)
      await dialog.getByRole('button', { name: 'Close asset inspection', exact: true }).click()
      await page.getByRole('button', { name: 'PBR Material', exact: true }).click()
      await page.getByRole('button', { name: ids.normal, exact: true }).click()
      await dialog.getByRole('button', { name: 'Load material', exact: true }).click()
      await pw(dialog.getByRole('toolbar', { name: 'Material controls', exact: true })).toBeVisible()
      for (const c of ['Albedo', 'Normal', 'Roughness', 'Metalness', 'Heightmap'])
        await pw(dialog.getByRole('button', { name: c, exact: true })).toBeEnabled()
      await pw(dialog.getByLabel('Map channel', { exact: true })).toHaveValue('Combined PBR')
      await pw(dialog.getByRole('button', { name: 'Download original', exact: true })).toBeVisible()
      mkdirSync('.verification/v11', { recursive: true })
      await page.screenshot({ path: `.verification/v11/inspector-${theme}.png` })
      await page.locator('[data-asset-backdrop]').click({ position: { x: 2, y: 2 } })
      await pw(dialog).toHaveCount(0)
      await page.getByRole('button', { name: 'All', exact: true }).click()
      await page.screenshot({ path: `.verification/v11/library-${theme}.png` })
    }
    const state = await h.state()
    expect(state.submissions).toEqual([])
    expect(state.balance).toBe(500)
    expect(h.errors).toEqual([])
  } finally { await h.close() }
}, 120000)

it('V11 production bundle: job prompts, metadata, copy and reuse preserve canonical tool and originating chat', async () => {
  const h = await openVisual(), { page } = h
  try {
    await fetch(h.url + '/__test/v11-cloud', { method: 'POST' })
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.evaluate(() => (window as any).workspace())
    await page.getByRole('tab', { name: 'Jobs', exact: true }).click()
    await page.getByRole('button', { name: 'Completed', exact: true }).click()
    await pw(page.getByText('A stylized alchemical astrolabe resting on dark slate', { exact: true })).toBeVisible()
    await pw(page.getByText('Generation: 9s', { exact: true })).toBeVisible()
    await pw(page.getByText('openai-gpt-image-2-v4-fn', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Copy ID', exact: true }).click()
    expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^000010b5-/)
    await page.getByRole('button', { name: 'Reuse Prompt', exact: true }).click()
    expect(await page.evaluate(() => (window as any).messages.at(-1))).toEqual({ session: 'origin-chat', text: 'A stylized alchemical astrolabe resting on dark slate' })
    await page.screenshot({ path: '.verification/v11/jobs.png' })
    expect((await h.state()).submissions).toEqual([])
    expect(h.errors).toEqual([])
  } finally { await h.close() }
}, 60000)

it('V11 production bundle: unindexed completed model, HDR, audio and negative rig-check outputs inspect without resubmission', async () => {
  const h = await openVisual(), { page } = h
  try {
    await page.evaluate(() => (window as any).workspace())
    await page.getByRole('tab', { name: 'Jobs', exact: true }).click()
    await page.getByRole('button', { name: 'Completed', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Asset inspection', exact: true })
    for (const key of ['meshUrl', 'modelUrl', 'hdrUrl', 'audioUrl', 'riggable']) {
      await fetch(h.url + '/__test/v11-job-output/' + key, { method: 'POST' })
      await page.getByRole('button', { name: 'Inspect Output', exact: true }).click()
      if (key === 'riggable') await pw(dialog.getByText('Not riggable', { exact: true })).toBeVisible()
      else if (key === 'audioUrl') await pw(dialog.locator('canvas')).toBeVisible()
      else {
        await dialog.getByRole('button', { name: key === 'hdrUrl' ? 'Load environment' : 'Click to load 3D', exact: true }).click()
        await pw(dialog.locator('canvas')).toBeVisible()
      }
      await dialog.getByRole('button', { name: 'Close asset inspection', exact: true }).click()
    }
    expect(h.errors).toEqual([])
    expect((await h.state()).submissions).toEqual([])
    expect((await h.state()).balance).toBe(500)
  } finally { await h.close() }
}, 90000)
