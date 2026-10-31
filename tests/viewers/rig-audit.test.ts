import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { build } from 'esbuild'
import { chromium } from '@playwright/test'
import { describe, expect, it } from 'vitest'
import { parseRigAudit } from '../../src/viewers/animation-viewer.tsx'
import { modelResultAudit, rigAuditSource } from '../../src/cards/model-card.tsx'

const valid = { riggable: true, joints: 2, warnings: [] }
describe('audit source and host envelope', () => {
  it.each([
    { audit: '/audit.json' },
    JSON.stringify({ result: JSON.stringify({ mesh: '/rig.glb', audit: '/audit.json' }) }),
    { result: { mesh: '/rig.glb', audit: '/audit.json' } },
    { structuredContent: { audit: '/audit.json' }, result: 'Completed' },
    { content: [{ type: 'text', text: JSON.stringify({ audit: '/audit.json' }) }] }
  ])('reads the audit without guessing a sibling MEDIA file', result => {
    expect(modelResultAudit(result)).toBe('/audit.json')
  })
  it.each([null, '', '{bad', [], { result: 'MEDIA:/rig.glb\nMEDIA:/audit.json' }])('ignores absent/unparseable result %j', result => {
    expect(modelResultAudit(result)).toBeUndefined()
  })
  it.each([{}, { path: '/a', asset: 'b' }, { path: '', asset: '12345678-1234-1234-1234-123456789abc' }, { asset: 'not-uuid' }, { path: 's3://bucket/audit' }])('rejects invalid source %j', source => {
    expect(rigAuditSource(source)).toEqual({ notice: 'Rig audit unavailable: malformed audit data' })
  })
})
describe('parseRigAudit', () => {
  it('accepts provider verdicts without deriving a verdict from the mesh', () => {
    expect(parseRigAudit(valid)).toEqual(valid)
    expect(parseRigAudit({ ...valid, riggable: false, warnings: ['Check shoulder weights'] })).toEqual({
      riggable: false, joints: 2, warnings: ['Check shoulder weights']
    })
  })
  it.each([null, [], 'audit', {}, { riggable: true }, { ...valid, riggable: 'true' },
    { ...valid, joints: -1 }, { ...valid, joints: 1.5 }, { ...valid, joints: Infinity },
    { ...valid, warnings: [3] }, { ...valid, warnings: null }])('rejects malformed data %j', (doc) => {
    expect(parseRigAudit(doc)).toBeNull()
  })
})

it.skipIf(process.env.STUDIOTWIN_WEBGL_TEST !== '1')('production registrations load provider audits independently of the real WebGL preview', async () => {
  const file = (name: string) => ({ name, dataUrl: 'data:application/octet-stream;base64,' + readFileSync(resolve('tests/fixtures/media/model', name)).toString('base64') })
  const bundle = await build({
    stdin: { resolveDir: process.cwd(), loader: 'tsx', contents: `
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {registerModelCards, ModelCard} from './src/cards/model-card.tsx';
      import {host} from '@hermes/plugin-sdk';
      const root=createRoot(document.getElementById('root')); const registrations={};
      let profile='alpha';const listeners=new Set();
      host.state={profile:{get:()=>profile,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)}}};
      window.switchProfile=()=>{profile='beta';listeners.forEach(fn=>fn())};
      const files=${JSON.stringify({ rig: file('rigged-animated.glb'), cube: file('static-cube.glb') })};
      window.calls=[]; let auditDoc=${JSON.stringify(valid)}, mode='valid', key=0;
      const rest=async route=>{window.calls.push(route);const q=new URL(route,'https://local').searchParams;
        const ref=q.get('path')||q.get('asset');
        if(ref==='/rig.glb')return files.rig;if(ref==='/cube.glb')return files.cube;
        if(mode==='failed')throw Error('not found');
        if(mode==='delayed')await new Promise(resolve=>{window.finishAudit=resolve});
        return {name:'audit.json',dataUrl:'data:application/json,'+encodeURIComponent(mode==='non-json'?'not json':JSON.stringify(auditDoc))};};
      const ctx={rest,register:r=>{registrations[r.id]=r.data;return()=>{}}}; registerModelCards(ctx);
      window.show=(kind, audit, variant='valid', staticModel=false)=>{
        mode=variant; auditDoc=variant==='attention'?{riggable:false,joints:2,warnings:['Check shoulder weights']}:variant==='types'?{riggable:'true',joints:2,warnings:[]}:variant==='missing'?{riggable:true}: ${JSON.stringify(valid)};
        window.calls=[];let element;
        if(kind==='directive')element=registrations['studiotwin-model-directive'].render({attrs:{path:staticModel?'/cube.glb':'/rig.glb',...(audit===null?{}:{audit})},streaming:false});
        else if(kind==='media')element=registrations['studiotwin-model-media'].render({toolName:variant==='tripo'?'mcp__studiotwin__tripo_auto_rig':'mcp__studiotwin__blender_auto_rig',file:{kind:'file',path:'/rig.glb',name:'rig.glb'},result:JSON.stringify({result:JSON.stringify({mesh:'/rig.glb',audit})}),fallback:'Built-in fallback'});
        else element=React.createElement(ModelCard,{ctx,source:{path:'/rig.glb'},auditSource:audit});
        root.render(React.createElement(React.Fragment,{key:++key},element));
      };
    ` }, bundle: true, write: false, format: 'iife', alias: { '@hermes/plugin-sdk': resolve('tests/scaffold/sdk-stub.ts') }, define: { 'process.env.NODE_ENV': '"production"' }
  })
  const browser = await chromium.launch({ executablePath: process.env.STUDIOTWIN_CHROME || chromium.executablePath(), args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox'] })
  try {
    const page = await browser.newPage()
    const errors: string[] = []
    const requests: string[] = []
    page.on('request', r => requests.push(r.url()))
    page.on('pageerror', e => errors.push(e.message))
    await page.setContent('<div id="root" style="width:650px"></div>')
    await page.addScriptTag({ content: bundle.outputFiles[0].text })
    const show = async (kind: string, audit: unknown, variant = 'valid', staticModel = false) => {
      await page.evaluate(({ kind, audit, variant, staticModel }) => (window as any).show(kind, audit, variant, staticModel), { kind, audit, variant, staticModel })
      await page.getByRole('button', { name: 'Click to load 3D' }).click()
      await page.locator('[data-model-stats]').waitFor()
      expect(await page.locator('canvas').count()).toBe(1)
      expect(await page.getByText('Built-in fallback', { exact: true }).count()).toBe(0)
    }
    for (const [kind, audit] of [['directive', '/audit.json'], ['directive', '12345678-1234-1234-1234-123456789abc'], ['media', '/audit.json'], ['media', { asset: '12345678-1234-1234-1234-123456789abc' }]] as const) {
      await show(kind, audit)
      await page.getByText('Rig audit: passed · 2 joints', { exact: true }).waitFor()
      expect(await page.evaluate(() => (window as any).calls)).toContain(typeof audit === 'string' && audit.startsWith('/') ? '/file?path=%2Faudit.json' : '/file?asset=12345678-1234-1234-1234-123456789abc')
    }
    await show('directive', '/audit.json', 'attention')
    await page.getByText(/Rig audit: needs attention/).waitFor()
    await page.getByText('Check shoulder weights', { exact: true }).waitFor()
    await show('media', '/audit.json', 'tripo')
    await page.getByText('Rig audit: passed · 2 joints', { exact: true }).waitFor()
    for (const variant of ['types', 'missing', 'non-json', 'failed']) {
      await show('directive', '/audit.json', variant)
      await page.getByText(/Rig audit unavailable:/).waitFor()
      expect(await page.getByText(/Rig audit: passed/).count()).toBe(0)
    }
    for (const audit of [{ path: '/a', asset: 'b' }, {}, { path: 3 }, '']) {
      await show('direct', audit)
      await page.getByText('Rig audit unavailable: malformed audit data', { exact: true }).waitFor()
      expect(await page.evaluate(() => (window as any).calls)).toEqual(['/file?path=%2Frig.glb'])
    }
    await show('directive', null)
    await page.getByText('Rig inspection (local): 2 joints · 1 skinned meshes · 2 clips', { exact: true }).waitFor()
    expect(await page.getByText(/Rig audit:/).count()).toBe(0)
    await show('directive', null, 'valid', true)
    expect(await page.getByText(/Rig inspection/).count()).toBe(0)
    await show('media', 'https://assets.example/audit.json?signature=secret')
    await page.getByText('Rig audit: provided separately', { exact: true }).waitFor()
    expect(await page.evaluate(() => (window as any).calls)).toEqual(['/file?path=%2Frig.glb'])
    await show('directive', '/audit.json', 'delayed')
    await page.evaluate(() => { (window as any).switchProfile(); (window as any).finishAudit() })
    await page.getByText('Select the originating profile and connection, then reopen this card.', { exact: true }).waitFor()
    // Resolve the old response after the switch: it must never surface a verdict.
    await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 100)))
    expect(await page.getByText(/Rig audit: passed/).count()).toBe(0)
    expect(await page.locator('canvas').count()).toBe(0)
    expect(await page.getByRole('button', { name: 'Download', exact: true }).isDisabled()).toBe(true)
    expect(errors).toEqual([])
    expect(requests.filter(url => /^https?:/.test(url))).toEqual([])
  } finally { await browser.close() }
}, 60_000)
