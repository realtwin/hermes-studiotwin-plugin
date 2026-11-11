import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { build } from "esbuild";
import { chromium } from "@playwright/test";
import { expect, it } from "vitest";

it.skipIf(process.env.STUDIOTWIN_WEBGL_TEST !== "1")(
  "applies exactly one EV to PNG/JPEG/HDR/EXR panoramas, before and after load and in flat view",
  async () => {
    const fixtures = Object.fromEntries(["equirect-64x32.png", "equirect-64x32.hdr", "equirect-32x16.exr"].map(name => [name, readFileSync(resolve("tests/fixtures/media/env", name)).toString("base64")]));
    const bundle = await build({
      stdin: { contents: `
        import {createEnvStage} from './src/viewers/env-stage.ts';
        const fixtures=${JSON.stringify(fixtures)};
        window.probe=async(name,early,flat)=>{
          const host=document.getElementById('stage');
          const stage=createEnvStage(host,[],()=>{});
          let bytes=Uint8Array.from(atob(fixtures[name==='test.jpg'?'equirect-64x32.png':name]),c=>c.charCodeAt(0));
          if(name==='test.jpg') {
            const image=await createImageBitmap(new Blob([bytes]));
            const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;
            canvas.getContext('2d').drawImage(image,0,0);image.close();
            bytes=new Uint8Array(await (await new Promise(r=>canvas.toBlob(r,'image/jpeg'))).arrayBuffer());
          }
          if(early)stage.settings(1,flat,false,false);
          await stage.load(bytes.buffer,name);
          stage.settings(0,flat,false,false);const zero=stage.snapshot();
          stage.settings(1,flat,false,false);const actual=stage.snapshot();
          const intensity=stage.scene.backgroundIntensity;
          // Independent oracle: sRGB backgrounds bypass tone mapping; linear HDR and
          // flat MeshBasicMaterial use renderer EV. Never multiply HDR twice.
          stage.scene.backgroundIntensity=!flat && /\\.(png|jpg)$/.test(name)?2:1;
          stage.renderer.toneMappingExposure=2;stage.render();const expected=stage.snapshot();
          stage.settings(-1,flat,false,false);const negative=stage.snapshot();
          stage.dispose();
          // Exercise EV configured while the asynchronous texture was still loading.
          const pending=createEnvStage(host,[],()=>{});pending.settings(1,flat,false,false);
          await pending.load(bytes.buffer,name);const earlyActual=pending.snapshot();pending.dispose();
          return {zero,actual,expected,negative,intensity,earlyActual};
        };`, resolveDir: process.cwd(), loader: "ts" },
      bundle: true, write: false, format: "iife",
    });
    const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--no-sandbox"] });
    try {
      const page = await browser.newPage();
      await page.setContent('<style>:root{--ui-bg-secondary:#222;--ui-text-primary:#ddd}#stage{width:640px;height:320px}</style><div id="stage"></div>');
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
      for (const name of [...Object.keys(fixtures), "test.jpg"]) {
        for (const flat of [false, true]) {
          const result = await page.evaluate(async ({name, flat}) => (window as any).probe(name, true, flat), {name, flat});
          expect(result.actual, `${name} flat=${flat} visible EV`).not.toBe(result.zero);
          expect(result.negative, `${name} flat=${flat} negative EV`).not.toBe(result.zero);
          expect(result.actual, `${name} flat=${flat} exactly one EV`).toBe(result.expected);
          expect(result.earlyActual, `${name} flat=${flat} EV retained across load`).toBe(result.expected);
          if (/\.(hdr|exr)$/.test(name)) expect(result.intensity).toBe(1);
          if (process.env.STUDIOTWIN_EXPOSURE_EVIDENCE) {
            mkdirSync(process.env.STUDIOTWIN_EXPOSURE_EVIDENCE, {recursive:true});
            for (const [ev, pixels] of [["zero", result.zero], ["plus-one", result.actual], ["minus-one", result.negative]] as const)
              writeFileSync(resolve(process.env.STUDIOTWIN_EXPOSURE_EVIDENCE, `${name}-${flat?'flat':'pano'}-${ev}.png`), Buffer.from(pixels.split(",")[1], "base64"));
          }
        }
      }
    } finally { await browser.close(); }
  }, 90_000,
);
