import { existsSync } from 'node:fs'
import { build } from 'esbuild'
import { chromium } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { parseModel, companionManager } from '../../src/viewers/model-parse.ts'
import { modelStats, disposeModel, AnimationController, parseMotion } from '../../src/viewers/model-data.ts'
import { WebGLPool } from '../../src/viewers/webgl-pool.ts'
import { bindModelScope, fileQuery } from '../../src/viewers/model-source.ts'
import { modelTool, nextModelActions } from '../../src/cards/model-card.tsx'
import { Bone, Group, Mesh, BoxGeometry, MeshStandardMaterial, Texture } from 'three'
const fixture = (p: string) => readFileSync(resolve('tests/fixtures/media', p))
const bytes = (p: string) => {
  const b = fixture(p)
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer
}
describe('real loaders and animation', () => {
  it('counts the static fixture', async () => {
    const p = await parseModel(bytes('model/static-cube.glb'), { name: 'cube.glb' })
    expect(modelStats(p)).toMatchObject({ vertices: 8, triangles: 12, meshes: 1, bones: 0, clips: [] })
    disposeModel(p.root)
  })
  it('selects Wave/Idle and scrubs deterministic bone poses at all speeds while paused', async () => {
    const p = await parseModel(bytes('model/rigged-animated.glb'), { name: 'rig.glb' })
    expect(modelStats(p)).toMatchObject({ vertices: 12, triangles: 16, meshes: 1, bones: 2, clips: ['Wave', 'Idle'] })
    const audit = JSON.parse(fixture('model/rig-audit.json').toString())
    expect(audit).toMatchObject({ riggable: true, joints: modelStats(p).bones, warnings: [] })
    const c = new AnimationController(p.root, p.clips)
    c.select('Wave')
    c.setPlaying(false)
    c.setSpeed(2)
    c.seek(0.5)
    expect(p.root.getObjectByName('upper')!.quaternion.z).toBeCloseTo(Math.sin(Math.PI / 12), 6)
    const pose: number[] = []
    p.root.traverse((n) => {
      if ((n as Bone).isBone) pose.push(...n.quaternion.toArray())
    })
    c.seek(0)
    c.seek(0.5)
    const again: number[] = []
    p.root.traverse((n) => {
      if ((n as Bone).isBone) again.push(...n.quaternion.toArray())
    })
    expect(again).toEqual(pose)
    expect(c.state().time).toBeCloseTo(0.5)
    expect(c.select('Idle')).toBe(1)
    c.seek(0.5)
    expect(p.root.getObjectByName('root')!.quaternion.x).toBeCloseTo(Math.sin(Math.PI / 36), 6)
    expect(c.select('absent')).toBe(-1)
    c.setLoop(false)
    c.setPlaying(true)
    c.update(10)
    expect(c.state().playing).toBe(false)
    c.dispose()
    disposeModel(p.root)
  })
  it('parses OBJ and STL without a renderer', async () => {
    const obj = new TextEncoder().encode('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n').buffer
    expect(modelStats(await parseModel(obj, { name: 'a.obj' })).triangles).toBe(1)
    const stl = new TextEncoder().encode(
      'solid a\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid a'
    ).buffer
    expect(modelStats(await parseModel(stl, { name: 'a.stl' })).triangles).toBe(1)
  })
  it('loads motion samples as real bone tracks', () => {
    const p = parseMotion(JSON.parse(fixture('motion/walk-clip.json').toString()))
    const c = new AnimationController(p.root, p.clips)
    c.select(0)
    c.setPlaying(false)
    c.seek(2 / 30)
    expect(p.root.getObjectByName('root')?.position.z).toBeCloseTo(0.2)
    expect(modelStats(p).bones).toBe(1)
    expect(() => parseMotion({ fps: 0 })).toThrow()
    c.dispose()
    disposeModel(p.root)
  })
  it('never permits external GLB/FBX/OBJ resources', () => {
    const m = companionManager({})
    for (const u of ['https://example.com/x', 'file:///a', '../texture.png', '//host/x'])
      expect(m.resolveURL(u)).toBe('data:,')
    expect(m.resolveURL('data:,ok')).toBe('data:,ok')
    expect(m.resolveURL('blob:test')).toBe('blob:test')
    expect(companionManager({ 'evil.png': 'https://example.com/evil.png' }).resolveURL('evil.png')).toBe('data:,')
  })
  it('rejects external glTF before any fetch and parses embedded JSON glTF', async () => {
    const b = bytes('model/static-cube.glb'),
      v = new DataView(b),
      len = v.getUint32(12, true)
    const doc = JSON.parse(new TextDecoder().decode(new Uint8Array(b, 20, len)))
    doc.buffers[0].uri = 'https://example.com/evil.bin'
    const fetcher = vi.spyOn(globalThis, 'fetch')
    await expect(parseModel(new TextEncoder().encode(JSON.stringify(doc)).buffer, { name: 'a.gltf' })).rejects.toThrow(
      /external/
    )
    expect(fetcher).not.toHaveBeenCalled()
    fetcher.mockRestore()
    // Node lacks this browser event; byte loading itself remains Three's real FileLoader/fetch path.
    vi.stubGlobal('ProgressEvent', class extends Event {})
    doc.buffers[0].uri = 'data:application/octet-stream;base64,' + Buffer.from(b, 28 + len).toString('base64')
    const p = await parseModel(new TextEncoder().encode(JSON.stringify(doc)).buffer, { name: 'a.gltf' })
    expect(modelStats(p).triangles).toBe(12)
    disposeModel(p.root)
  })
})
// Optional real Chromium gate; STUDIO... enables this in V02/V08 verification, no vendor network.
it.skipIf(process.env.STUDIOTWIN_WEBGL_TEST !== '1')(
  'mounted viewers enforce cap and animate through real WebGL',
  async () => {
    const bundled = await build({
      stdin: {
        contents: `
    import React from 'react'; import {createRoot} from 'react-dom/client';
    import {ModelViewer} from './src/viewers/model-viewer.tsx';
    import {ModelCard} from './src/cards/model-card.tsx';
    import {host} from '@hermes/plugin-sdk';
    import {modelWebGLPool} from './src/viewers/webgl-pool.ts';
    const rest=async()=>(${JSON.stringify({ name: 'rigged.glb', bytes: 2492, dataUrl: 'data:model/gltf-binary;base64,' + fixture('model/rigged-animated.glb').toString('base64') })});
    const root=createRoot(document.getElementById('root'));
    window.pool=modelWebGLPool; window.unmount=()=>root.unmount();
    let profile='alpha'; const listeners=new Set(); window.prompts=[];
    const scopeState={profile:{get:()=>profile,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)}}};
    host.composer.submit=(id,text)=>{window.prompts.push({id,text});return true};
    window.switchProfile=()=>{profile='beta';listeners.forEach(fn=>fn())};
    window.card=(bad=false)=>root.render(React.createElement(ModelCard,{key:bad?'bad':'good',ctx:{rest:bad?async()=>({name:'bad.glb',dataUrl:'data:,bad'}):rest},scopeState,sessionId:'origin-chat',source:{path:'/rig.glb'},fallback:'Built-in fallback'}));
    window.auditCard=()=>root.render(React.createElement(ModelViewer,{key:'audit',rest:async()=>(${JSON.stringify({ name: 'rig-audit.json', dataUrl: 'data:application/json;base64,' + fixture('model/rig-audit.json').toString('base64') })}),source:{path:'/rig-audit.json'}}));
    root.render(React.createElement('div',{},Array.from({length:6},(_,i)=>React.createElement(ModelViewer,{key:i,rest,source:{path:'/rig.glb'},height:180}))));
  `,
        resolveDir: process.cwd(),
        loader: 'tsx'
      },
      bundle: true,
      write: false,
      format: 'iife',
      alias: { '@hermes/plugin-sdk': resolve('tests/scaffold/sdk-stub.ts') },
      define: { 'process.env.NODE_ENV': '"production"' }
    })
    const executablePath = process.env.STUDIOTWIN_CHROME || chromium.executablePath()
    expect(existsSync(executablePath)).toBe(true)
    const browser = await chromium.launch({
      executablePath,
      args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox']
    })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1600 } })
      const errors: string[] = []
      page.on('pageerror', (e) => errors.push(e.message))
      await page.setContent(
        '<style>:root{--ui-bg-secondary:#20242a;--ui-text:#eeeeee;--ui-text-secondary:#b8bdc7;--ui-stroke-secondary:#4b5360;--ui-accent:#98bcfa} #root>div{display:grid;grid-template-columns:1fr 1fr;gap:12px}</style><div id="root"></div>'
      )
      await page.addScriptTag({ content: bundled.outputFiles[0].text })
      const viewers = page.locator('[data-studiotwin-model-viewer]')
      await viewers.first().waitFor()
      for (let i = 0; i < 6; i++) {
        await viewers.nth(i).getByRole('button', { name: 'Click to load 3D' }).click()
        await viewers.nth(i).locator('[data-model-stats]').waitFor()
        expect(await page.locator('canvas').count()).toBeLessThanOrEqual(4)
      }
      expect(await page.locator('canvas').count()).toBe(4)
      expect(await page.getByRole('button', { name: 'Click to load 3D' }).count()).toBe(2)
      const last = viewers.nth(5)
      await last.getByLabel('Animation clip', { exact: true }).selectOption('1')
      await last.getByRole('button', { name: 'Pause', exact: true }).click()
      await last.getByLabel('Playback speed').selectOption('2')
      await last.getByLabel('Animation position').fill('0.5')
      await last.getByLabel('Shading mode').selectOption('normals')
      await last.getByRole('button', { name: 'Reset camera' }).click()
      expect(errors).toEqual([])
      if (process.env.STUDIOTWIN_SCREENSHOT)
        await page.screenshot({ path: process.env.STUDIOTWIN_SCREENSHOT, fullPage: true })
      // Leaving the viewport releases a context, not just its render loop.
      await last.evaluate((el) => {
        ;(el as HTMLElement).style.display = 'none'
      })
      await page.waitForFunction(() => (window as unknown as { pool: { size: number } }).pool.size === 3)
      await page.evaluate(() => {
        ;(window as unknown as { card: () => void }).card()
      })
      await page.getByRole('button', { name: 'Save to project' }).waitFor()
      await page.getByRole('button', { name: 'Save to project' }).click()
      expect(await page.evaluate(() => (window as unknown as { prompts: { id: string }[] }).prompts[0].id)).toBe(
        'origin-chat'
      )
      await page.evaluate(() => {
        ;(window as unknown as { switchProfile: () => void }).switchProfile()
      })
      await page.waitForFunction(() => Boolean(document.querySelector('button:disabled')))
      expect(await page.getByRole('button', { name: 'Download', exact: true }).isDisabled()).toBe(true)
      await page.evaluate(() => {
        ;(window as unknown as { card: (bad: boolean) => void }).card(true)
      })
      await page.getByRole('button', { name: 'Click to load 3D' }).click()
      await page.getByText('Built-in fallback', { exact: true }).waitFor()
      await page.evaluate(() => {
        ;(window as unknown as { auditCard: () => void }).auditCard()
      })
      await page.getByRole('button', { name: 'Click to load 3D' }).click()
      await page.getByText('Rig audit: passed', { exact: true }).waitFor()
      expect(await page.locator('canvas').count()).toBe(0)
      await page.evaluate(() => {
        ;(window as unknown as { unmount: () => void }).unmount()
      })
      expect(await page.locator('canvas').count()).toBe(0)
      expect(await page.evaluate(() => (window as unknown as { pool: { size: number } }).pool.size)).toBe(0)
    } finally {
      await browser.close()
    }
  },
  60_000
)

describe('GPU ownership', () => {
  it('caps four contexts, evicts LRU synchronously before allocation, releases exactly once', () => {
    const p = new WebGLPool(4)
    const disposed = Array.from({ length: 6 }, () => vi.fn())
    for (let i = 0; i < 4; i++) p.acquire(String(i), disposed[i])
    p.touch('0')
    p.acquire('4', disposed[4])
    expect(disposed[1]).toHaveBeenCalledTimes(1)
    expect(p.size).toBe(4)
    p.release('1')
    expect(disposed[1]).toHaveBeenCalledTimes(1)
    p.setLimit(2)
    expect(p.size).toBe(2)
    p.clear()
    expect(p.size).toBe(0)
    for (const i of [0, 1, 2, 3, 4]) expect(disposed[i]).toHaveBeenCalledTimes(1)
  })
  it('disposes shared resources once', () => {
    const g = new BoxGeometry()
    const texture = new Texture()
    const mat = new MeshStandardMaterial({ map: texture })
    const root = new Group()
    root.add(new Mesh(g, mat), new Mesh(g, mat))
    const a = vi.spyOn(g, 'dispose'),
      b = vi.spyOn(mat, 'dispose')
    const t = vi.spyOn(texture, 'dispose')
    disposeModel(root)
    expect(a).toHaveBeenCalledTimes(1)
    expect(b).toHaveBeenCalledTimes(1)
    expect(t).toHaveBeenCalledTimes(1)
  })
})
describe('backend scope and card contract', () => {
  it('blocks requests and composer writes after a scope switch, including delayed results', async () => {
    let profile = 'a'
    let finish!: (v: unknown) => void
    const rest = vi.fn(
      () =>
        new Promise((r) => {
          finish = r
        })
    )
    const scope = bindModelScope(rest as never, { profile: { get: () => profile }, connectionId: { get: () => null } })
    const pending = scope.rest('/file?path=x')
    profile = 'b'
    finish({ dataUrl: 'wrong' })
    await expect(pending).rejects.toThrow(/scope/i)
    await expect(scope.rest('/save', { method: 'POST' })).rejects.toThrow(/scope/i)
    expect(rest).toHaveBeenCalledTimes(1)
    expect(scope.current()).toBe(false)
  })
  it('builds file queries and tool-specific visible next prompts', () => {
    expect(fileQuery({ path: '/a b.glb' })).toBe('/file?path=%2Fa+b.glb')
    expect(fileQuery({ asset: 'abc' })).toBe('/file?asset=abc')
    expect(() => fileQuery({ path: 'a', asset: 'b' })).toThrow()
    expect(modelTool('mcp__studiotwin__studiotwin_tripo_auto_rig')).toBe(true)
    expect(modelTool('terminal')).toBe(false)
    expect(nextModelActions({ asset: 'x' }).map((a) => a.label)).toEqual([
      'Retopologize',
      'Check Rig',
      'Auto-Rig',
      'Animate',
      'Blender Handoff'
    ])
  })
  it('has only theme-based DOM chrome', () => {
    for (const file of [
      'src/viewers/model-viewer.tsx',
      'src/viewers/animation-viewer.tsx',
      'src/cards/model-card.tsx'
    ]) {
      const source = readFileSync(file, 'utf8')
      expect(source).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i)
      expect(source).toContain('var(--ui-')
    }
  })
})
