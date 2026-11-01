import { build } from 'esbuild'
import { resolve } from 'node:path'
import { chromium } from '@playwright/test'
import { it, expect } from 'vitest'

it('mounted model/environment/material actions route missing and draft owners without bypassing scopes', async () => {
  const bundle = await build({
    stdin: { resolveDir: process.cwd(), loader: 'tsx', contents: `
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {ModelCard} from './src/cards/model-card.tsx';
      import {EnvCard} from './src/cards/env-card.tsx';
      import {MaterialCard} from './src/cards/material-card.tsx';
      import {host} from '@hermes/plugin-sdk';
      const root=createRoot(document.getElementById('root'));
      let profile='a',connection='a',listeners=new Set(),key=0;
      const atom=get=>({get,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)}});
      const scopeState={profile:atom(()=>profile),connectionId:atom(()=>connection)};
      window.mount=(kind,owner)=>{window.calls=[];window.accept='all';
        host.composer.submit=(id,text)=>{window.calls.push(id);return window.accept==='all'||(window.accept==='active'&&id===null)};
        const common={key:++key,ctx:{rest:async()=>{throw Error('No network expected')}},scopeState,sessionId:owner};
        root.render(kind==='model'?<ModelCard {...common} source={{path:'/m.glb'}}/>:kind==='env'?<EnvCard {...common} source={{path:'/e.hdr'}}/>:<MaterialCard {...common} maps={{albedo:{path:'/a.png'}}}/>);
      };
      window.switchScope=field=>{if(field==='profile')profile+='x';else connection+='x';listeners.forEach(fn=>fn())};
    ` },
    bundle: true, write: false, format: 'iife',
    alias: { '@hermes/plugin-sdk': resolve('tests/scaffold/sdk-stub.ts') },
    define: { 'process.env.NODE_ENV': '"production"' },
  })
  const browser = await chromium.launch({ args: ['--no-sandbox'] })
  try {
    const page = await browser.newPage()
    await page.setContent('<div id="root"></div>')
    await page.addScriptTag({ content: bundle.outputFiles[0].text })
    const mount = async (kind: string, owner?: string | null, accept = 'all') => {
      await page.evaluate(({kind,owner,accept}) => { (window as any).mount(kind,owner); (window as any).accept=accept }, {kind,owner,accept})
      await page.locator('summary').click()
    }
    const next = () => page.locator('details button').first()
    const calls = () => page.evaluate(() => (window as any).calls)
    for (const kind of ['model','env','material']) {
      await mount(kind); await next().click(); expect(await calls()).toEqual([null])
      await mount(kind,null); await next().click(); expect(await calls()).toEqual(['new'])
      await mount(kind,null,'active'); await next().click(); expect(await calls()).toEqual(['new',null])
      await mount(kind,'origin-chat','none'); await next().click(); expect(await calls()).toEqual(['origin-chat'])
      for (const field of ['profile','connection']) {
        await mount(kind)
        await page.evaluate(field => (window as any).switchScope(field), field)
        await next().evaluate(el => (el as HTMLButtonElement).click())
        expect(await calls()).toEqual([])
        expect(await next().isDisabled()).toBe(true)
      }
    }
  } finally { await browser.close() }
}, 30000)
