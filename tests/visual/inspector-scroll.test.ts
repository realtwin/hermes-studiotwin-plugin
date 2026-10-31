// @vitest-environment node
import { expect, it } from 'vitest'
import { expect as pw } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { openVisual } from './bundle-harness'

for (const theme of ['light', 'dark']) {
  it(`production bundle: wheel reaches inspector Next actions in ${theme} at 1000x700`, async () => {
    const h = await openVisual(), { page } = h
    const output = process.env.STUDIOTWIN_INSPECTOR_EVIDENCE
    try {
      await page.setViewportSize({ width: 1000, height: 700 })
      await page.addStyleTag({ content: `:root {--ui-bg:${theme === 'light' ? '#fafafa' : '#15181e'};--ui-bg-card:var(--ui-bg);--ui-bg-secondary:${theme === 'light' ? '#e9edf4' : '#1c222b'};--ui-text:${theme === 'light' ? '#172033' : '#e3e9f4'};--ui-text-primary:var(--ui-text);--ui-text-secondary:var(--ui-text);--ui-stroke-secondary:var(--ui-text);--ui-accent:#285dd6;}` })
      await page.evaluate(() => (window as any).workspace())
      await page.getByRole('button', { name: 'crate.glb', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: 'Asset inspection' })
      const next = dialog.getByRole('region', { name: 'Next', exact: true })
      const action = next.getByRole('button').last()
      await pw(action).toBeAttached()
      const measure = () => dialog.evaluate(n => {
        const next = n.querySelector('[aria-label="Next"]')!
        return { overflow: getComputedStyle(n).overflowY, clientHeight: n.clientHeight,
          scrollHeight: n.scrollHeight, scrollTop: n.scrollTop,
          nextBottom: next.getBoundingClientRect().bottom, bottom: n.getBoundingClientRect().bottom }
      })
      const before = await measure()
      expect(before.scrollHeight).toBeGreaterThan(before.clientHeight)
      expect(before.scrollTop).toBe(0)
      expect(before.nextBottom).toBeGreaterThan(before.bottom)
      // No locator click/focus/scrollIntoView before measuring: those can scroll
      // overflow:hidden programmatically and conceal the user's wheel failure.
      await dialog.hover()
      await page.mouse.wheel(0, 1200)
      await pw.poll(async () => (await measure()).scrollTop).toBeGreaterThan(0)
      await pw.poll(async () => {
        const m = await measure()
        return m.nextBottom <= m.bottom
      }).toBe(true)
      const after = await measure()
      // Verify physical reachability, not merely Playwright's toBeVisible.
      const box = await action.boundingBox()
      expect(box).not.toBeNull()
      const point = { x: box!.x + box!.width / 2, y: box!.y + box!.height / 2 }
      expect(await action.evaluate((n, p) => n.contains(document.elementFromPoint(p.x, p.y)), point)).toBe(true)
      if (output) {
        mkdirSync(output, { recursive: true })
        await page.screenshot({ path: `${output}/inspector-${theme}.png` })
      }
      await page.mouse.click(point.x, point.y)
      await pw.poll(() => page.evaluate(() => (window as any).messages.length)).toBe(1)
      expect(h.errors).toEqual([])
      expect((await h.state()).submissions).toEqual([])
      if (output) writeFileSync(`${output}/inspector-${theme}.json`, JSON.stringify({ theme, before, after, errors: h.errors, paidSubmissions: [] }, null, 2) + '\n')
    } finally { await h.close() }
  }, 120000)
}
