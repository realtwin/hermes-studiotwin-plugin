// @vitest-environment node
/** V10 acceptance gate: real Chromium + Three/WebGL. Only host REST/composer are
 * fixtures; no renderer mocks, paid/vendor calls, or production debug hooks.
 * Run: STUDIOTWIN_WEBGL_TEST=1 STUDIOTWIN_CHROME=/opt/google/chrome/chrome npx vitest run tests/viewers/multiview-ibl.test.ts
 */
import { existsSync, readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { openVisual, upload } from '../visual/bundle-harness'
import { delimiter, resolve } from 'node:path'
import { build } from 'esbuild'
import { chromium, expect as webExpect, type Browser, type Page } from '@playwright/test'
import { beforeAll, afterAll, describe, expect, it } from 'vitest'

const fixture = (name: string) => readFileSync(resolve('tests/fixtures/media', name)).toString('base64')
const canonical = ['front', 'right', 'back', 'left', 'three_quarter', 'top']
const pngPrefix = 'data:image/png;base64,'
const enabled = process.env.STUDIOTWIN_WEBGL_TEST === '1'
let browser: Browser
let stageCode: string
let sourceCode: string
let desktopCode: string
const theme = `<style>:root{--ui-bg-secondary:#20242a;--ui-text:#eee;--ui-text-secondary:#b8bdc7;--ui-stroke-secondary:#4b5360;--ui-accent:#98bcfa}#root{width:700px}#stage{width:520px;height:340px}</style><div id="root"></div><div id="stage"></div>`
const esbuildOptions = {
  bundle: true, write: false, format: 'iife' as const,
  nodePaths: (process.env.NODE_PATH || '').split(delimiter).filter(Boolean),
  alias: { '@hermes/plugin-sdk': resolve('tests/scaffold/sdk-stub.ts') },
  define: { 'process.env.NODE_ENV': '"production"' }
}
const fixtures = {
  cube: { name: 'cube.glb', dataUrl: 'data:model/gltf-binary;base64,' + fixture('model/static-cube.glb') },
  rig: { name: 'rig.glb', dataUrl: 'data:model/gltf-binary;base64,' + fixture('model/rigged-animated.glb') },
  hdr: { name: 'studio.hdr', dataUrl: 'data:application/octet-stream;base64,' + fixture('env/equirect-64x32.hdr') }
}
const stageHarness = `
import {createModelStage} from './src/viewers/model-stage.ts';
import {GLTFExporter} from 'three/examples/jsm/exporters/GLTFExporter.js';
import {Scene,Mesh,BoxGeometry,MeshStandardMaterial,PerspectiveCamera} from 'three';
window.captureAngles=async(options={})=>{
  const old=PerspectiveCamera.prototype.lookAt, samples=[];
  PerspectiveCamera.prototype.lookAt=function(...args){
    const target=typeof args[0]==='number'?{x:args[0],y:args[1],z:args[2]}:args[0];
    const p=this.position.clone().sub(target);samples.push([Math.atan2(p.x,p.z)*180/Math.PI,Math.asin(p.y/p.length())*180/Math.PI]);
    return old.apply(this,args);
  };
  try{await window.stage.captureMultiview({views:6,tileSize:128,...options});return samples}finally{PerspectiveCamera.prototype.lookAt=old}
};
const decode=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0)).buffer;
window.hdr=decode(${JSON.stringify(fixture('env/equirect-64x32.hdr'))});
// Avoid Window named-property access resolving #stage as the stage API.
window.stage=null;
window.initStage=async(rig=false)=>{
  window.stage?.dispose();
  const stage=window.stage=createModelStage(document.getElementById('stage'));
  if(rig) await stage.load(decode(${JSON.stringify(fixture('model/rigged-animated.glb'))}),'rig.glb');
  else {
    // Deliberately asymmetric real GLB: a cube alone cannot detect swapped views.
    const scene=new Scene();
    for(const [size,position,color] of [ [[1.2,1.8,.7],[0,.9,0],0xb84420],[[.55,.6,1.1],[.75,.3,.35],0x207ab8],[[.3,.4,.3],[-.4,2,.1],0x43b825] ]){
      const mesh=new Mesh(new BoxGeometry(...size),new MeshStandardMaterial({color,roughness:.35,metalness:.25}));
      mesh.position.set(...position);scene.add(mesh);
    }
    const glb=await new GLTFExporter().parseAsync(scene,{binary:true});
    await stage.load(glb,'asymmetric.glb');
    scene.traverse(o=>{o.geometry?.dispose();o.material?.dispose()});
  }
  stage.setAutoRotate(false);stage.setGrid(true);
  if(stage.animation()){stage.animation().setPlaying(false);stage.animation().seek(.5)}
  return true;
};
window.inspectPng=async(url)=>{
 const image=new Image();image.src=url;await image.decode();const c=document.createElement('canvas');c.width=image.width;c.height=image.height;
 const g=c.getContext('2d');g.drawImage(image,0,0);const p=g.getImageData(0,0,c.width,c.height).data;
 let opaque=0,transparent=0,minX=c.width,minY=c.height,maxX=-1,maxY=-1;const colors=new Set();
 for(let i=0;i<p.length;i+=4){if(p[i+3]===0)transparent++;if(p[i+3]>16){opaque++;const x=i/4%c.width,y=Math.floor(i/4/c.width);minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);colors.add(p[i]+','+p[i+1]+','+p[i+2])}}
 return {width:c.width,height:c.height,opaque,transparent,colors:colors.size,bounds:[minX,minY,maxX,maxY],corner:Array.from(p.slice(0,4))};
};
`

// Host-only boundary. Routes not explicitly allowed fail, so a paid invocation
// cannot accidentally pass as a successful test. Deferred promises are test-owned.
const uiHarness = (desktop: boolean) => `
import React from 'react';import {createRoot} from 'react-dom/client';
import {QueryClientProvider} from '@tanstack/react-query';
import * as sdk from '@hermes/plugin-sdk';
${desktop ? "import plugin from './desktop/plugin.js';" : "import {ModelCard} from './src/cards/model-card.tsx';import {ModelViewer} from './src/viewers/model-viewer.tsx';"}
const w=window,files=${JSON.stringify(fixtures)};w.calls=[];w.prompts=[];w.notifications=[];w.disallowed=[];w.gates={};w.fail='';w.block='';
const atom=value=>{const listeners=new Set();return{get:()=>value,set:v=>{value=v;listeners.forEach(fn=>fn())},subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)}}};
const scope={profile:atom('alpha'),connectionId:atom(null),activeSessionId:atom('origin-chat')};sdk.host.state=scope;
sdk.host.composer.submit=(id,text)=>{w.prompts.push({id,text});return true};sdk.host.notify=n=>w.notifications.push(n);
w.switchScope=kind=>scope[kind].set(kind==='profile'?'beta':'other-connection');
w.release=key=>w.gates[key]?.();
const rest=async(path,options={})=>{
 w.calls.push({path,...options});const route=path.split('?')[0];
 if(w.block===route)await new Promise(resolve=>w.gates[route]=resolve);
 if(w.fail===route)throw Error('Injected '+route+' failure');
 if(route==='/file'){const q=new URLSearchParams(path.split('?')[1]);const key=q.get('path')||q.get('asset');if(key==='/studio.hdr')return files.hdr;if(key==='/cube.glb'||key==='11111111-1111-4111-8111-111111111111')return files.cube;if(key==='/rig.glb')return files.rig;throw Error('Unknown fixture '+key)}
 if(route==='/upload')return {local_path:'/local/cube-multiview-4v-clay.png',path:'/local/cube-multiview-4v-clay.png',name:'cube-multiview-4v-clay.png',bytes:123};
 if(route==='/provenance')return {ok:true,id:options.body?.id};
 if(route==='/status')return {configured:true,settings:{inline_cards:true,auto_rotate:false,webgl_limit:4}};
 w.disallowed.push(path);throw Error('Unexpected/possibly paid route '+path);
};
const root=createRoot(document.getElementById('root'));w.unmount=()=>{root.unmount();sdk.queryClient.clear()};
const ctx={rest,register:r=>{w.registrations.push(r);return()=>{}},onDispose:()=>{},onEvent:()=>()=>{},os:{openExternal:async()=>true,revealPath:async()=>true}};
w.registrations=[];${desktop ? 'plugin.register(ctx);' : ''}
w.mount=(kind='card',env=false)=>{
 const props={ctx,rest,scopeState:scope,sessionId:'origin-chat',source:{path:'/cube.glb',name:'cube.glb'},auto_rotate:false,
 ...(env?{envSource:{path:'/studio.hdr'},environments:[{label:'Fixture HDR',source:{path:'/studio.hdr'}}]}:{})};
 const element=${desktop ? "w.registrations.find(r=>r.data?.name==='studiotwin-model').data.render({attrs:{path:'/cube.glb',name:'cube.glb'},streaming:false,source:'V10 fixture',sessionId:'origin-chat'})" : "React.createElement(kind==='viewer'?ModelViewer:ModelCard,props)"};
 root.render(React.createElement(QueryClientProvider,{client:sdk.queryClient},element));
};w.mount();
`

async function newPage(code: string) {
  const page = await browser.newPage({ viewport: { width: 1100, height: 1300 }, deviceScaleFactor: 1 })
  page.setDefaultTimeout(4000)
  const errors: string[] = [], blocked: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/*', route => {
    if (route.request().url() === 'http://localhost/__v10_harness')
      return route.fulfill({ status: 200, contentType: 'text/html', body: theme })
    blocked.push(route.request().url()); return route.abort()
  })
  // A loopback origin preserves the host's secure-context crypto APIs without
  // opening a network listener. Every other browser network request is denied.
  await page.goto('http://localhost/__v10_harness')
  await page.addScriptTag({ content: code })
  return { page, errors, blocked }
}
async function stagePage(rig = false) {
  const h = await newPage(stageCode)
  await h.page.evaluate(rig => (window as any).initStage(rig), rig)
  return h
}
async function capture(page: Page, options: Record<string, unknown> = {}) {
  return page.evaluate(options => (window as any).stage.captureMultiview({ views: 4, shading: 'clay', background: 'transparent', ...options }), options)
}
async function loadUI(page: Page) {
  await page.getByRole('button', { name: 'Click to load 3D', exact: true }).click()
  await webExpect(page.locator('[data-model-stats]')).toBeVisible()
}
async function captureUI(page: Page) {
  await page.getByRole('button', { name: 'Capture Multiview', exact: true }).click()
  await webExpect(page.getByAltText('Multiview Reference Preview', { exact: true })).toBeVisible()
}
async function calls(page: Page, route: string) {
  return page.evaluate(route => (window as any).calls.filter((c: any) => c.path.split('?')[0] === route), route)
}
async function assertNoPaid(page: Page) {
  expect(await page.evaluate(() => (window as any).disallowed)).toEqual([])
}

describe.skipIf(!enabled)('V10 real Chromium multiview + IBL', () => {
  beforeAll(async () => {
    const executablePath = process.env.STUDIOTWIN_CHROME || (existsSync('/opt/google/chrome/chrome') ? '/opt/google/chrome/chrome' : chromium.executablePath())
    expect(existsSync(executablePath), 'A real Chromium installation is required').toBe(true)
    const bundles = await Promise.all([stageHarness, uiHarness(false), uiHarness(true)].map(contents => build({
      ...esbuildOptions, stdin: { contents, resolveDir: process.cwd(), loader: 'tsx' }
    })))
    ;[stageCode, sourceCode, desktopCode] = bundles.map(b => b.outputFiles![0].text)
    browser = await chromium.launch({ executablePath, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox'] })
  }, 60000)
  afterAll(async () => { await browser?.close() })

  it('creates an actual WebGL context, not a canvas or renderer stand-in', async () => {
    const { page, errors, blocked } = await stagePage()
    try {
      expect(await page.locator('#stage canvas').evaluate(c => !!((c as HTMLCanvasElement).getContext('webgl2')))).toBe(true)
      const pixels = await page.evaluate(() => (window as any).inspectPng((window as any).stage.snapshot()))
      expect(pixels.colors).toBeGreaterThan(20)
      expect(errors).toEqual([]); expect(blocked).toEqual([])
    } finally { await page.close() }
  })

  for (const views of [4, 6]) it(`captures ${views} canonical named PNG views and a nonblank correctly sized sheet`, async () => {
    const { page, errors, blocked } = await stagePage()
    try {
      const result = await capture(page, { views, tileSize: 128 })
      expect(result).toMatchObject({ shading: 'clay', tileSize: 128, width: (views === 4 ? 2 : 3) * 128, height: 256 })
      expect(result.views.map((v: any) => v.name)).toEqual(canonical.slice(0, views))
      expect(new Set(result.views.map((v: any) => v.label)).size).toBe(views)
      for (const view of result.views) {
        expect(view.label.trim().length).toBeGreaterThan(0)
        expect(view.dataUrl).toMatch(/^data:image\/png;base64,/)
        const p = await page.evaluate(url => (window as any).inspectPng(url), view.dataUrl)
        expect(p.width).toBe(128); expect(p.height).toBe(128)
        expect(p.opaque).toBeGreaterThan(100); expect(p.transparent).toBeGreaterThan(100)
        expect(p.colors).toBeGreaterThan(8)
        expect(p.bounds[0]).toBeGreaterThan(0); expect(p.bounds[1]).toBeGreaterThan(0)
        expect(p.bounds[2]).toBeLessThan(127); expect(p.bounds[3]).toBeLessThan(127)
      }
      // Asymmetry means a repeated screenshot or swapped camera cannot pass.
      expect(new Set(result.views.map((v: any) => v.dataUrl)).size).toBe(views)
      const sheet = await page.evaluate(url => (window as any).inspectPng(url), result.sheetDataUrl)
      expect(sheet.width).toBe(result.width); expect(sheet.height).toBe(result.height)
      expect(sheet.colors).toBeGreaterThan(20); expect(sheet.opaque).toBeGreaterThan(views * 100)
      expect(errors).toEqual([]); expect(blocked).toEqual([])
    } finally { await page.close() }
  })

  it('uses the actual canonical camera yaw and pitch, not merely distinct labels', async () => {
    const { page } = await stagePage()
    try {
      const angles = await page.evaluate(() => (window as any).captureAngles())
      expect(angles).toHaveLength(6)
      const expected = [[0,12],[90,12],[180,12],[-90,12],[35,22],[0,85]]
      angles.forEach((angle: number[], i: number) => {
        expect(angle[0]).toBeCloseTo(expected[i][0], 6)
        expect(angle[1]).toBeCloseTo(expected[i][1], 6)
      })
    } finally { await page.close() }
  })

  for (const yawOffsetDeg of [0, 90, 180, -90, 22.5, 450]) it(`yaw offset ${yawOffsetDeg} rotates every canonical camera and restores the stage`, async () => {
    const { page } = await stagePage()
    try {
      const before = await page.evaluate(() => (window as any).stage.snapshot())
      const angles = await page.evaluate(yawOffsetDeg => (window as any).captureAngles({ yawOffsetDeg }), yawOffsetDeg)
      const expected = [[0,12],[90,12],[180,12],[270,12],[35,22],[0,85]]
      expect(angles).toHaveLength(6)
      angles.forEach((angle: number[], i: number) => {
        const radians = (expected[i][0] + yawOffsetDeg) * Math.PI / 180
        expect(Math.sin(angle[0] * Math.PI / 180)).toBeCloseTo(Math.sin(radians), 6)
        expect(Math.cos(angle[0] * Math.PI / 180)).toBeCloseTo(Math.cos(radians), 6)
        expect(angle[1]).toBeCloseTo(expected[i][1], 6)
      })
      expect(await page.evaluate(() => (window as any).stage.snapshot())).toBe(before)
    } finally { await page.close() }
  })

  it('yaw offset rejects nonfinite values before changing the stage', async () => {
    const { page } = await stagePage()
    try {
      const result = await page.evaluate(async () => {
        const s = (window as any).stage, before = s.snapshot(), failures = []
        for (const yawOffsetDeg of [NaN, Infinity, -Infinity]) {
          try { await s.captureMultiview({ yawOffsetDeg, tileSize: 128 }); failures.push(false) }
          catch (e) { failures.push(String(e).includes('yawOffsetDeg')) }
        }
        return { failures, restored: before === s.snapshot() }
      })
      expect(result).toEqual({ failures: [true, true, true], restored: true })
    } finally { await page.close() }
  })

  it('source yaw selector defaults to +Z and passes every selected offset into capture', async () => {
    const { page } = await newPage(sourceCode)
    try {
      await page.evaluate(() => (window as any).mount('viewer')); await loadUI(page)
      const yaw = page.getByRole('combobox', { name: 'Multiview yaw offset', exact: true })
      await webExpect(yaw).toHaveValue('0')
      expect(await yaw.locator('option').evaluateAll(options => options.map(o => [(o as HTMLOptionElement).value, o.textContent]))).toEqual([
        ['0', '0° (+Z)'], ['90', '90° (+X)'], ['180', '180° (-Z)'], ['-90', '-90° (-X)']
      ])
      await captureUI(page)
      await webExpect(yaw).toBeEnabled()
      const baseline = await page.getByAltText('Multiview Reference Preview', { exact: true }).getAttribute('src')
      for (const value of ['90', '180', '-90', '0']) {
        await yaw.selectOption(value)
        const previousUploads = (await calls(page, '/upload')).length
        await page.getByRole('button', { name: 'Capture Multiview', exact: true }).click()
        await webExpect(yaw).toBeEnabled()
        expect(await calls(page, '/upload')).toHaveLength(previousUploads + 1)
        const image = await page.getByAltText('Multiview Reference Preview', { exact: true }).getAttribute('src')
        if (value === '0') expect(image).toBe(baseline)
        else expect(image).not.toBe(baseline)
      }
      await assertNoPaid(page)
    } finally { await page.close() }
  }, 30000)

  it('production bundle stages an actual PNG through the real router and persists readable Made from lineage without spending', async () => {
    const h = await openVisual(), { page } = h
    const posts: { route: string; body: any }[] = []
    page.on('request', req => {
      if (req.method() === 'POST' && /\/(upload|provenance)$/.test(new URL(req.url()).pathname)) posts.push({ route: new URL(req.url()).pathname.split('/').at(-1)!, body: req.postDataJSON() })
    })
    try {
      const source = await upload(h, 'model/static-cube.glb')
      await page.evaluate(source => (window as any).renderDirective('model', { path: source, name: 'cube.glb' }), source)
      await loadUI(page)
      await page.getByLabel('Multiview views', { exact: true }).selectOption('6')
      await page.getByLabel('Multiview pass', { exact: true }).selectOption('normals')
      await captureUI(page)
      const button = page.getByRole('button', { name: 'Reskin 3D in Chat', exact: true })
      await webExpect(button).toBeEnabled()
      const record = posts.find(p => p.route === 'provenance')!.body
      const lineage = await fetch(h.url + '/api/plugins/hermes-studiotwin/provenance?id=' + record.id).then(r => r.json())
      expect(lineage.recorded).toBe(true)
      expect(lineage.id).toBe(record.id)
      const { id: _id, ...metadata } = record
      expect(lineage.record).toMatchObject(metadata)
      expect(lineage.made_from).toContain('Made from')
      expect(lineage.record.prompt).toContain(source)
      const match = /Multiview sheet (".*?") \(/.exec(lineage.record.prompt)!
      const sheetPath = JSON.parse(match[1])
      const stored = await fetch(h.url + '/api/plugins/hermes-studiotwin/file?' + new URLSearchParams({ path: sheetPath })).then(r => r.json())
      const img = page.getByAltText('Multiview Reference Preview', { exact: true })
      expect(await img.getAttribute('src')).toBe(stored.dataUrl)
      expect(stored.name).toContain('cube-multiview-6v-normals.png')
      expect(posts.find(p => p.route === 'upload')!.body.cloud).toBe(false)
      await button.click()
      const messages = await page.evaluate(() => (window as any).messages)
      expect(messages).toHaveLength(1); expect(messages[0].session).toBe('origin-chat')
      expect(messages[0].text).toContain(sheetPath)
      const state = await h.state()
      expect(state.submissions).toEqual([]); expect(state.ledger.filter((e: any) => e.event === 'debit')).toEqual([])
      const evidence = process.env.STUDIOTWIN_MULTIVIEW_EVIDENCE
      if (evidence) {
        mkdirSync(evidence, { recursive: true })
        writeFileSync(resolve(evidence, 'ui-6-normals-sheet.png'), Buffer.from(stored.dataUrl.split(',')[1], 'base64'))
        await page.screenshot({ path: resolve(evidence, 'multiview-reference.png'), fullPage: true })
      }
      expect(h.errors).toEqual([]); expect(h.blocked).toEqual([])
    } finally { await h.close() }
  }, 30000)

  it('defaults tileSize to 384 and supports both documented boundary sizes', async () => {
    const { page } = await stagePage()
    try {
      const defaults = await capture(page)
      expect(defaults.tileSize).toBe(384); expect(defaults.width).toBe(768); expect(defaults.height).toBe(768)
      const largest = await capture(page, { tileSize: 1024 })
      const p = await page.evaluate(url => (window as any).inspectPng(url), largest.views[0].dataUrl)
      expect(p.width).toBe(1024); expect(p.height).toBe(1024)
    } finally { await page.close() }
  }, 30000)

  it('rejects invalid requests instead of allocating unbounded render targets and preserves the live stage', async () => {
    const { page } = await stagePage()
    try {
      const result = await page.evaluate(async () => {
        const s = (window as any).stage, before = s.snapshot(), failures = []
        // Prove the valid API exists before testing rejection: a missing method
        // throwing TypeError must not count as successful validation.
        await s.captureMultiview({ views: 4, shading: 'clay', tileSize: 128, background: 'transparent' })
        // Charter explicitly clamps tile size, rather than rejecting out-of-range values.
        for (const [tileSize, expected] of [[127,128],[1025,1024],[128.5,129],[NaN,384]]) {
          const result = await s.captureMultiview({tileSize, shading:'clay'})
          if (result.tileSize !== expected) throw Error('tile size not clamped')
        }
        for (const options of [{ views: 5 }, { shading: 'invalid' }, { background: 'invalid' }]) {
          try { await s.captureMultiview({ views: 4, shading: 'clay', tileSize: 128, background: 'transparent', ...options }); failures.push(false) }
          catch { failures.push(true) }
        }
        return { failures, restored: before === s.snapshot() }
      })
      expect(result.failures).toEqual(Array(3).fill(true)); expect(result.restored).toBe(true)
    } finally { await page.close() }
  })

  it('renders four distinct shading passes and transparent versus opaque studio backgrounds', async () => {
    const { page } = await stagePage()
    try {
      const images: string[] = []
      for (const shading of ['clay', 'normals', 'textured', 'wireframe']) {
        const result = await capture(page, { shading, tileSize: 128 })
        expect(result.shading).toBe(shading); images.push(result.views[0].dataUrl)
      }
      expect(new Set(images).size).toBe(4)
      const studio = await capture(page, { background: 'studio', tileSize: 128 })
      const p = await page.evaluate(url => (window as any).inspectPng(url), studio.views[0].dataUrl)
      expect(p.transparent).toBe(0); expect(p.corner[3]).toBe(255)
    } finally { await page.close() }
  })

  it('captures a single paused animated pose deterministically and restores camera, shading, grid, canvas size and animation', async () => {
    const { page } = await stagePage(true)
    try {
      const result = await page.evaluate(async () => {
        const s = (window as any).stage, a = s.animation();s.setAutoRotate(false);s.setShading('normals');s.setGrid(true)
        a.select('Wave');a.setPlaying(false);a.setSpeed(2);a.setLoop(false);a.seek(.5)
        const before = s.snapshot(), state = a.state(), canvas = document.querySelector('#stage canvas') as HTMLCanvasElement
        const size = [canvas.width,canvas.height]
        const one = await s.captureMultiview({ views: 6, shading: 'clay', tileSize: 128, background: 'transparent' })
        const after = s.snapshot(), afterState = a.state(), afterSize = [canvas.width,canvas.height]
        const two = await s.captureMultiview({ views: 6, shading: 'clay', tileSize: 128, background: 'transparent' })
        a.seek(0);const changed = await s.captureMultiview({ views: 6, shading: 'clay', tileSize: 128, background: 'transparent' })
        return {before,after,state,afterState,size,afterSize,one:one.views.map((v: any)=>v.dataUrl),two:two.views.map((v: any)=>v.dataUrl),changed:changed.views.map((v: any)=>v.dataUrl)}
      })
      expect(result.after).toBe(result.before); expect(result.afterState).toEqual(result.state); expect(result.afterSize).toEqual(result.size)
      expect(result.one).toEqual(result.two); expect(result.changed).not.toEqual(result.one)
    } finally { await page.close() }
  })

  it('restores the live stage even when canvas PNG encoding throws partway through capture', async () => {
    const { page } = await stagePage(true)
    try {
      const result = await page.evaluate(async () => {
        const s = (window as any).stage;s.setShading('wireframe');s.setGrid(true);s.setAutoRotate(false)
        const before = s.snapshot(), state = s.animation().state(), original = HTMLCanvasElement.prototype.toDataURL
        let count = 0, error = ''
        HTMLCanvasElement.prototype.toDataURL = function (...args) { if (++count === 2) throw Error('V10 injected PNG encoding failure'); return original.apply(this,args) }
        try { await s.captureMultiview({ views: 6, shading: 'normals', tileSize: 128, background: 'transparent' }) }
        catch (e) { error = String(e) } finally { HTMLCanvasElement.prototype.toDataURL = original }
        const after = s.snapshot(), restoredState = s.animation().state()
        const recovered = await s.captureMultiview({ views: 4, shading: 'clay', tileSize: 128, background: 'transparent' })
        return {before,after,state,restoredState,error,count,recovered:recovered.views.length}
      })
      expect(result.error).toContain('V10 injected PNG encoding failure'); expect(result.count).toBeGreaterThanOrEqual(2)
      expect(result.after).toBe(result.before); expect(result.restoredState).toEqual(result.state); expect(result.recovered).toBe(4)
    } finally { await page.close() }
  })

  it('real HDR image-based lighting changes textured AND clay model pixels; clearing recovers the exact original snapshot', async () => {
    const { page, errors, blocked } = await stagePage()
    try {
      const result = await page.evaluate(async () => {
        const s = (window as any).stage, passes = []
        for (const shading of ['textured','clay']) {
          s.setShading(shading);const before=s.snapshot()
          const base=await s.captureMultiview({views:4,shading,tileSize:128,background:'transparent'})
          await s.setEnvironment((window as any).hdr,'studio.hdr',false)
          const lit=s.snapshot(), capture=await s.captureMultiview({views:4,shading,tileSize:128,background:'transparent'})
          await s.clearEnvironment()
          passes.push({shading,before,lit,cleared:s.snapshot(),base:base.views[0].dataUrl,ibl:capture.views[0].dataUrl})
        }
        return passes
      })
      for (const pass of result) {
        expect(pass.lit, pass.shading + ' live IBL').not.toBe(pass.before)
        expect(pass.ibl, pass.shading + ' captured IBL').not.toBe(pass.base)
        expect(pass.cleared, pass.shading + ' exact recovery').toBe(pass.before)
      }
      expect(errors).toEqual([]); expect(blocked).toEqual([])
    } finally { await page.close() }
  }, 30000)

  it('can show an HDR background, clear it via null, and survive malformed HDR without corrupting the stage', async () => {
    const { page } = await stagePage()
    try {
      const result = await page.evaluate(async () => {
        const s=(window as any).stage,before=s.snapshot();await s.setEnvironment((window as any).hdr,'studio.hdr',false);const hidden=s.snapshot()
        await s.setEnvironment((window as any).hdr,'studio.hdr',true);const shown=s.snapshot()
        await s.setEnvironment(null);const cleared=s.snapshot();let rejected=false
        try {await s.setEnvironment(new Uint8Array([1,2,3]).buffer,'bad.hdr',true)}catch{rejected=true}
        return {before,hidden,shown,cleared,rejected,afterBad:s.snapshot()}
      })
      expect(result.shown).not.toBe(result.hidden); expect(result.cleared).toBe(result.before)
      expect(result.rejected).toBe(true); expect(result.afterBad).toBe(result.before)
    } finally { await page.close() }
  }, 30000)

  for (const surface of ['source', 'desktop'] as const) {
    const code = () => surface === 'source' ? sourceCode : desktopCode
    it(`${surface}: exposes accessible 4/6 controls, all passes, preview and a real downloadable PNG`, async () => {
      const { page, errors, blocked } = await newPage(code())
      try {
        await loadUI(page)
        const views=page.getByLabel('Multiview views',{exact:true}), pass=page.getByLabel('Multiview pass',{exact:true})
        await webExpect(views).toHaveValue('4'); await webExpect(pass).toHaveValue('clay')
        expect(await views.locator('option').evaluateAll(o=>o.map(v=>(v as HTMLOptionElement).value))).toEqual(['4','6'])
        expect((await pass.locator('option').evaluateAll(o=>o.map(v=>(v as HTMLOptionElement).value))).sort()).toEqual(['clay','normals','textured','wireframe'])
        await views.selectOption('6');await pass.selectOption('normals');await captureUI(page)
        const preview=page.getByAltText('Multiview Reference Preview',{exact:true})
        const dimensions=await preview.evaluate(async img=>{await (img as HTMLImageElement).decode();return [(img as HTMLImageElement).naturalWidth,(img as HTMLImageElement).naturalHeight]})
        expect(dimensions).toEqual([1152,768])
        const pending=page.waitForEvent('download');await page.getByRole('button',{name:'Download Sheet',exact:true}).click()
        const download=await pending;expect(download.suggestedFilename()).toMatch(/multiview.*6v.*normals\.png$/)
        const path=await download.path();expect(path).toBeTruthy()
        expect([...readFileSync(path!).subarray(0,8)]).toEqual([137,80,78,71,13,10,26,10])
        await assertNoPaid(page);expect(errors).toEqual([]);expect(blocked).toEqual([])
      } finally {await page.close()}
    },30000)

    it(`${surface}: stages locally then records valid provenance before enabling a review-only reskin handoff`, async () => {
      const {page,errors}=await newPage(code())
      try {
        await page.evaluate(()=>{(window as any).block='/provenance'})
        await loadUI(page)
        const reskin=page.getByRole('button',{name:'Reskin 3D in Chat',exact:true})
        await webExpect(reskin).toBeDisabled();await captureUI(page)
        await page.waitForFunction(()=>(window as any).calls.some((c: any)=>c.path==='/provenance'))
        await webExpect(reskin).toBeDisabled()
        const upload=(await calls(page,'/upload'))[0]
        expect(upload.method).toBe('POST');expect(upload.body).toMatchObject({filename:'cube-multiview-4v-clay.png',cloud:false})
        expect(typeof upload.body.data).toBe('string');expect(upload.body.data).not.toContain('data:')
        expect([...Buffer.from(upload.body.data,'base64').subarray(0,8)]).toEqual([137,80,78,71,13,10,26,10])
        const provenance=(await calls(page,'/provenance'))[0]
        expect(provenance.method).toBe('POST')
        expect(provenance.body.id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i)
        const allowed=['id','jobId','task_id','sourceAssetIds','outputAssetIds','conceptId','prompt','tool','session_id']
        expect(Object.keys(provenance.body).every(k=>allowed.includes(k))).toBe(true)
        expect(provenance.body.session_id).toBe('origin-chat')
        expect(JSON.stringify(provenance.body)).toContain('/cube.glb')
        expect(JSON.stringify(provenance.body)).toContain('/local/cube-multiview-4v-clay.png')
        expect(await page.evaluate(()=>(window as any).prompts)).toEqual([])
        await page.evaluate(()=>(window as any).release('/provenance'));await webExpect(reskin).toBeEnabled();await reskin.click()
        const prompts=await page.evaluate(()=>(window as any).prompts)
        expect(prompts).toHaveLength(1);expect(prompts[0].id).toBe('origin-chat')
        for(const ref of ['/cube.glb','/local/cube-multiview-4v-clay.png','openai-gpt-image-2-v4-fn','image-to-3d-mesh','tripo-image-to-3d-mesh'])expect(prompts[0].text).toContain(ref)
        expect(prompts[0].text).toMatch(/concept.?lab/i);expect(prompts[0].text).toMatch(/estimat/i);expect(prompts[0].text).toMatch(/approv/i)
        expect(prompts[0].text).not.toContain(pngPrefix)
        expect((await calls(page,'/upload')).length).toBe(1);await assertNoPaid(page);expect(errors).toEqual([])
      }finally{await page.close()}
    },30000)

    for(const failure of ['/upload','/provenance'])it(`${surface}: ${failure} failure never enables reskin or sends a composer message`,async()=>{
      const {page}=await newPage(code())
      try{
        await page.evaluate(failure=>{(window as any).fail=failure},failure);await loadUI(page);await captureUI(page)
        await page.waitForFunction(failure=>(window as any).calls.some((c: any)=>c.path===failure),failure)
        await page.evaluate(()=>new Promise(resolve=>setTimeout(resolve,100)))
        await webExpect(page.getByRole('button',{name:'Reskin 3D in Chat',exact:true})).toBeDisabled()
        expect(await page.evaluate(()=>(window as any).prompts)).toEqual([])
        if(failure==='/upload')expect(await calls(page,'/provenance')).toHaveLength(0)
        await assertNoPaid(page)
      }finally{await page.close()}
    },20000)

    for(const kind of ['profile','connectionId'])it(`${surface}: ${kind} switch while upload is pending blocks late provenance and composer handoff`,async()=>{
      const {page}=await newPage(code())
      try{
        await page.evaluate(()=>{(window as any).block='/upload'});await loadUI(page);await captureUI(page)
        await page.waitForFunction(()=>(window as any).gates['/upload'])
        await page.evaluate(kind=>(window as any).switchScope(kind),kind)
        await page.evaluate(()=>(window as any).release('/upload'))
        await page.evaluate(()=>new Promise(resolve=>setTimeout(resolve,150)))
        expect(await calls(page,'/provenance')).toHaveLength(0)
        expect(await page.evaluate(()=>(window as any).prompts)).toEqual([])
        const reskin=page.getByRole('button',{name:'Reskin 3D in Chat',exact:true})
        if(await reskin.count())await webExpect(reskin).toBeDisabled()
        await webExpect(page.locator('canvas')).toHaveCount(0)
        await assertNoPaid(page)
      }finally{await page.close()}
    },20000)
  }

  it('source standalone ModelViewer supports multiview without a ModelCard or callbacks',async()=>{
    const {page,errors}=await newPage(sourceCode)
    try{
      await page.evaluate(()=>(window as any).mount('viewer'));await loadUI(page);await captureUI(page)
      await webExpect(page.getByRole('button',{name:'Download Sheet',exact:true})).toBeEnabled()
      expect(errors).toEqual([]);await assertNoPaid(page)
    }finally{await page.close()}
  },20000)

  it('source ModelCard forwards envSource and loads the HDR locally without a cloud or paid request',async()=>{
    const {page,errors}=await newPage(sourceCode)
    try{
      await page.evaluate(()=>(window as any).mount('card',true));await loadUI(page)
      await page.waitForFunction(()=>(window as any).calls.some((c: any)=>c.path.startsWith('/file?')&&new URLSearchParams(c.path.split('?')[1]).get('path')==='/studio.hdr'))
      await captureUI(page);await assertNoPaid(page);expect(errors).toEqual([])
    }finally{await page.close()}
  },20000)
})
