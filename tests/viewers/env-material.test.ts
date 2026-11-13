import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { build } from "esbuild";
import { chromium, expect as browserExpect } from "@playwright/test";
import { describe, it, expect } from "vitest";
import {
  environmentTexture,
  parseStickers,
  stickerBoundary,
  direction,
} from "../../src/viewers/env-stage.ts";
import {
  envTool,
  registerEnvCards,
  nextEnvActions,
} from "../../src/cards/env-card.tsx";
import {
  materialTool,
  registerMaterialCards,
  parseMaterialMaps,
  nextMaterialActions,
} from "../../src/cards/material-card.tsx";
import { mapZip } from "../../src/viewers/material-download.ts";
const fixture = (p: string) => readFileSync(resolve("tests/fixtures/media", p));
const bytes = (p: string) => {
  const b = fixture(p);
  return b.buffer.slice(
    b.byteOffset,
    b.byteOffset + b.byteLength,
  ) as ArrayBuffer;
};
const sticker = {
  assetId: "sticker-one",
  yawDeg: 0,
  pitchDeg: 0,
  rollDeg: 25,
  hFovDeg: 45,
  sourceAspect: 2,
};
describe("environment and material contracts", () => {
  const costs = JSON.parse(readFileSync(resolve("plugin.json"), "utf8"))
    .extensions["com.nousresearch.hermes"].servers.studiotwin.costs;
  const tools = JSON.parse(
    readFileSync(resolve("tests/fixtures/tools-list-2026-10-30.json"), "utf8"),
  ).tools as { name: string; description: string }[];
  const actions = [...nextEnvActions, ...nextMaterialActions];
  it.each([
    "pano-sticker-placement",
    "texture-to-material",
    "environment-map-to-world",
  ])("grounds the fixed %s label in checked-in pricing", (tool) => {
    const label = actions.find(([, name]) => name === tool)?.[0];
    const description = tools.find(({ name }) => name === tool)?.description;
    expect(typeof costs[tool]).toBe("number");
    expect(description).toContain(`Costs ${costs[tool]} credits.`);
    expect(label).toContain(`(${costs[tool]} cr)`);
  });
  it.each([
    "environment-map-upscale-cpu",
    "pano-stickers",
    "image-to-material",
  ])("requests an estimate instead of a flat price for %s", (tool) => {
    const label = actions.find(([, name]) => name === tool)?.[0];
    expect(costs[tool].note).toContain("Input-dependent");
    expect(label).toContain("(estimate in chat)");
    expect(label).not.toMatch(/\d+\s*(?:cr|credits)\b/i);
  });
  it("decodes real Radiance and EXR pixels", async () => {
    for (const [file, width] of [
      ["equirect-64x32.hdr", 64],
      ["equirect-32x16.exr", 32],
    ] as const) {
      const t = await environmentTexture(bytes("env/" + file), file);
      expect(t.image.width).toBe(width);
      expect(t.image.data.length).toBeGreaterThan(width);
      t.dispose();
    }
  });
  it("validates camelCase placements and projects rolled spherical FOV boundaries", () => {
    expect(parseStickers([sticker])).toEqual([sticker]);
    const points = stickerBoundary(sticker);
    expect(points).toHaveLength(65);
    for (const p of points) expect(p.length()).toBeCloseTo(1);
    expect(points[0].equals(points[64])).toBe(true);
    expect(direction(0, 0).z).toBe(-1);
    expect(() => parseStickers([{ ...sticker, hFovDeg: 180 }])).toThrow();
    expect(() => parseStickers([{ ...sticker, yawDeg: NaN }])).toThrow();
  });
  it("claims only its own tools, registers both surfaces, disposes and returns fallback for bad results", () => {
    for (const [register, tools] of [
      [registerEnvCards, ["text-to-environment-map", "pano-stickers"]],
      [registerMaterialCards, ["text-to-material", "texture-to-material"]],
    ] as const) {
      const rows: any[] = [];
      let disposed = 0;
      const stop = register({
        register: (r: any) => {
          rows.push(r);
          return () => disposed++;
        },
      } as any);
      expect(rows).toHaveLength(2);
      for (const t of tools)
        expect(rows[0].data.tools).toContain("mcp__studiotwin__" + t);
      expect(
        rows[0].data.render({ toolName: "terminal", fallback: "native" }),
      ).toBe("native");
      expect(
        rows[0].data.render({
          toolName: tools[0],
          result: {},
          file: { name: "bad.txt" },
          fallback: "native",
        }),
      ).toBe("native");
      stop();
      expect(disposed).toBe(2);
    }
    expect(envTool("mcp__studiotwin__pano_stickers")).toBe(true);
    expect(materialTool("mcp__studiotwin__text-to-material")).toBe(true);
    expect(materialTool("text-to-image")).toBe(false);
    expect(nextEnvActions).toHaveLength(4);
  });
  it("requires albedo but permits missing optional channels", () => {
    expect(parseMaterialMaps({ albedo: "/a.png" })).toEqual({
      albedo: { path: "/a.png" },
    });
    expect(() => parseMaterialMaps({ normal: "/n.png" })).toThrow();
  });
  it("uses host theme tokens for both viewer shells and cards", () => {
    for (const file of [
      "src/viewers/env-lifecycle.ts",
      "src/viewers/env-viewer.tsx",
      "src/viewers/material-viewer.tsx",
      "src/cards/env-card.tsx",
      "src/cards/material-card.tsx",
    ]) {
      const text = readFileSync(resolve(file), "utf8");
      expect(text).toMatch(/var\(--ui-|panelStyle/);
      expect(text).not.toMatch(
        /#[0-9a-f]{3,8}\b|(?:color|background):\s*['"](?:white|black|rgb)/i,
      );
    }
  });
  it("writes valid stored zip records", () => {
    const b = mapZip([
      { name: "albedo.png", buffer: new Uint8Array([1, 2, 3]).buffer },
    ]);
    const v = new DataView(b);
    expect(v.getUint32(0, true)).toBe(0x04034b50);
    expect(v.getUint32(b.byteLength - 22, true)).toBe(0x06054b50);
    expect(v.getUint16(b.byteLength - 14, true)).toBe(1);
  });
});
it.skipIf(process.env.STUDIOTWIN_WEBGL_TEST !== "1")(
  "mounted real Chromium WebGL environment and five-map material, lifecycle and scoped cards",
  async () => {
    const responses: Record<string, { name: string; dataUrl: string }> = {};
    for (const file of [
      "model/static-cube.glb",
      "env/equirect-64x32.hdr",
      "env/equirect-64x32.png",
      "env/equirect-32x16.exr",
      ...["albedo", "normal", "roughness", "metalness"].map(
        (c) => "material/pbr-" + c + ".png",
      ),
    ])
      responses["/" + file] = {
        name: file.split("/").pop()!,
        dataUrl:
          "data:application/octet-stream;base64," +
          fixture(file).toString("base64"),
      };
    const bundled = await build({
      stdin: {
        contents: `
 import React from 'react';import {createRoot} from 'react-dom/client';
 import {EnvViewer} from './src/viewers/env-viewer.tsx';import {MaterialViewer} from './src/viewers/material-viewer.tsx';
 import {EnvCard} from './src/cards/env-card.tsx';import {MaterialCard} from './src/cards/material-card.tsx';
 import {modelWebGLPool} from './src/viewers/webgl-pool.ts';import {ModelViewer} from './src/viewers/model-viewer.tsx';
 import {host} from '@hermes/plugin-sdk';
 const root=createRoot(document.getElementById('root')),responses=${JSON.stringify(responses)};
 // Explicitly generated grayscale height-channel input, since the base has no heightmap fixture.
 const c=document.createElement('canvas');c.width=c.height=16;const g=c.getContext('2d');const gradient=g.createLinearGradient(0,0,16,16);gradient.addColorStop(0,'black');gradient.addColorStop(1,'white');g.fillStyle=gradient;g.fillRect(0,0,16,16);responses['/height.png']={name:'height.png',dataUrl:c.toDataURL()};
 window.calls=[];const rest=async p=>{const path=new URLSearchParams(p.split('?')[1]).get('path');window.calls.push(path);if(path==='/bad.hdr')return {name:'bad.hdr',dataUrl:'data:,bad'};if(!responses[path])throw Error('Unknown test fixture '+path);return responses[path]};
 const maps=Object.fromEntries(['albedo','normal','roughness','metalness'].map(c=>[c,{path:'/material/pbr-'+c+'.png'}]));maps.heightmap={path:'/height.png'};
 const stickers=[${JSON.stringify(sticker)}];window.pool=modelWebGLPool;
 window.grid=()=>root.render(React.createElement('div',{className:'grid'},Array.from({length:7},(_,i)=>i===6?React.createElement(ModelViewer,{key:i,rest,source:{path:'/model/static-cube.glb'},height:160}):i%2?React.createElement(MaterialViewer,{key:i,rest,maps,height:160}):React.createElement(EnvViewer,{key:i,rest,source:{path:'/env/equirect-64x32.hdr'},height:160,stickers}))));
 window.env=(name='equirect-64x32.hdr',fallback,displayName)=>root.render(React.createElement(EnvViewer,{key:name,rest,source:{path:name==='bad.hdr'?'/bad.hdr':'/env/'+name,name:displayName},stickers,fallback}));
 window.material=()=>root.render(React.createElement(MaterialViewer,{key:'material',rest,maps}));
 window.badMaterial=()=>root.render(React.createElement(MaterialViewer,{key:'bad-material',rest,maps:{albedo:{path:'/bad.hdr'}},fallback:'Material fallback'}));
 let profile='alpha';const listeners=new Set();const scopeState={profile:{get:()=>profile,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)}}};
 window.prompts=[];host.composer.submit=(id,text)=>{window.prompts.push({id,text});return true};window.switchProfile=()=>{profile='beta';listeners.forEach(fn=>fn())};
 window.card=(material=false)=>root.render(material?React.createElement(MaterialCard,{key:'material-card',ctx:{rest},maps,scopeState,sessionId:'origin',fallback:'Native fallback'}):React.createElement(EnvCard,{key:'env-card',ctx:{rest},source:{path:'/env/equirect-64x32.hdr'},stickers,scopeState,sessionId:'origin',fallback:'Native fallback'}));
 window.clear=()=>modelWebGLPool.clear();window.unmount=()=>root.unmount();window.grid();
 `,
        resolveDir: process.cwd(),
        loader: "tsx",
      },
      bundle: true,
      write: false,
      format: "iife",
      alias: { "@hermes/plugin-sdk": resolve("tests/scaffold/sdk-stub.ts") },
      define: { "process.env.NODE_ENV": '"production"' },
    });
    const browser = await chromium.launch({
      args: [
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--no-sandbox",
      ],
    });
    try {
      const page = await browser.newPage({
          viewport: { width: 1400, height: 1600 },
        }),
        errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.setContent(
        '<style>:root{--ui-text:#eee;--ui-text-secondary:#bbb;--ui-bg-secondary:#20242a;--ui-accent:#9bf;--ui-stroke-secondary:#555}.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}</style><div id="root"></div>',
      );
      await page.addScriptTag({ content: bundled.outputFiles[0].text });
      const call = async (name: string, ...args: unknown[]) =>
        page.evaluate(({ name, args }) => (window as any)[name](...args), {
          name,
          args,
        });
      const views = page.locator("section");
      await views.first().waitFor();
      for (let i = 0; i < 7; i++) {
        await views
          .nth(i)
          .getByRole("button", {
            name:
              i === 6
                ? "Click to load 3D"
                : i % 2
                  ? "Load material"
                  : "Load environment",
            exact: true,
          })
          .click();
        await views.nth(i).getByRole("toolbar").waitFor();
        expect(await page.locator("canvas").count()).toBeLessThanOrEqual(4);
      }
      expect(await page.locator("canvas").count()).toBe(4);
      expect(await page.locator('img[alt$="poster"]').count()).toBe(3);
      await views
        .nth(5)
        .evaluate((el) => ((el as HTMLElement).style.display = "none"));
      await page.waitForFunction(() => (window as any).pool.size === 3);
      // Display labels must never choose the image decoder (including misleading extensions).
      for (const name of ['equirect-64x32.hdr', 'equirect-64x32.png', 'equirect-32x16.exr']) {
        await call('env', name, 'Environment preview unavailable.', 'Panorama preview.jpg');
        await page.getByRole('button', { name: 'Load environment', exact: true }).click();
        await browserExpect(page.getByRole('toolbar', { name: 'Environment controls' })).toBeVisible();
        expect(await page.getByText('Environment preview unavailable.', { exact: true }).count()).toBe(0);
      }
      // Preserve the original LDR pixel regression and guard HDR separately below.
      await call("env", "equirect-64x32.png");
      await page
        .getByRole("button", { name: "Load environment", exact: true })
        .click();
      await page.getByRole("toolbar").waitFor();
      const canvas = page.locator("canvas");
      const before = await canvas.evaluate((el) =>
        (el as HTMLCanvasElement).toDataURL(),
      );
      await page.getByLabel("Exposure EV").fill("2");
      await page.waitForTimeout(50);
      expect(
        await canvas.evaluate((el) => (el as HTMLCanvasElement).toDataURL()),
      ).not.toBe(before);
      await page
        .getByRole("button", { name: "Sticker sticker-one", exact: true })
        .click();
      await browserExpect(page.getByLabel("Selected sticker")).toHaveText(
        "sticker-one",
      );
      await page
        .getByRole("button", { name: "Sticker overlay", exact: true })
        .click();
      expect(
        await page
          .getByRole("button", { name: "Sticker sticker-one", exact: true })
          .count(),
      ).toBe(0);
      await page
        .getByRole("button", { name: "Chrome / matte preview" })
        .click();
      await page.getByRole("button", { name: "Flat 2:1" }).click();
      await canvas.dispatchEvent("wheel", { deltaY: 100 });
      await page.mouse.move(700, 160);
      await page.mouse.down();
      await page.mouse.move(800, 180);
      await page.mouse.up();
      await call("env", "equirect-32x16.exr");
      await page
        .getByRole("button", { name: "Load environment", exact: true })
        .click();
      await page.getByRole("toolbar").waitFor();
      await call("material");
      await page
        .getByRole("button", { name: "Load material", exact: true })
        .click();
      await page.getByRole("toolbar").waitFor();
      const channelPixels: string[] = [];
      for (const c of [
        "albedo",
        "normal",
        "roughness",
        "metalness",
        "heightmap",
        "Combined PBR",
      ]) {
        await page.getByLabel("Map channel").selectOption(c);
        await page.waitForTimeout(20);
        channelPixels.push(
          await page
            .locator("canvas")
            .evaluate((el) => (el as HTMLCanvasElement).toDataURL()),
        );
      }
      expect(new Set(channelPixels).size).toBeGreaterThanOrEqual(5);
      for (const g of ["Cube", "Rounded Plane", "Sphere"])
        await page.getByLabel("Geometry", { exact: true }).selectOption(g);
      await page.getByLabel("UV tiling").selectOption("4");
      await page.getByLabel("Displacement scale").fill("0.2");
      await page.getByLabel("Light rig rotation").fill("180");
      await page.getByRole("button", { name: "2D tiled swatch" }).click();
      await page.getByRole("button", { name: "2D tiled swatch" }).click();
      expect(
        await page.evaluate(() =>
          (window as any).calls.includes("/height.png"),
        ),
      ).toBe(true);
      await call("badMaterial");
      await page
        .getByRole("button", { name: "Load material", exact: true })
        .click();
      await page.getByText("Material fallback", { exact: true }).waitFor();
      await call("clear");
      await page.waitForTimeout(50);
      await browserExpect(
        page.getByText("Material fallback", { exact: true }),
      ).toBeVisible();
      await call("env", "bad.hdr", "Persistent fallback");
      await page
        .getByRole("button", { name: "Load environment", exact: true })
        .click();
      await page.getByText("Persistent fallback", { exact: true }).waitFor();
      await call("clear");
      await page.waitForTimeout(50);
      await browserExpect(
        page.getByText("Persistent fallback", { exact: true }),
      ).toBeVisible();
      // Replacement remounts a real observed section after the fallback removed it.
      await call("env", "equirect-64x32.hdr");
      await page
        .getByRole("button", { name: "Load environment", exact: true })
        .click();
      await page.getByRole("toolbar").waitFor();
      await page
        .locator("section")
        .evaluate((el) => ((el as HTMLElement).style.display = "none"));
      await page.waitForFunction(() => (window as any).pool.size === 0);
      await call("card", false);
      await page.getByText("Next · review and approve in chat").click();
      await page
        .getByRole("button", {
          name: "Upscale Environment (estimate in chat)",
          exact: true,
        })
        .click();
      expect(await page.evaluate(() => (window as any).prompts[0].id)).toBe(
        "origin",
      );
      expect(await page.evaluate(() => (window as any).prompts[0].text)).toContain(
        "estimate the exact inputs with studiotwin_estimate_cost and ask me to approve credits before submitting",
      );
      await page
        .getByRole("button", { name: "Load environment", exact: true })
        .click();
      await page.getByRole("toolbar").waitFor();
      await call("switchProfile");
      await browserExpect(
        page.getByRole("button", { name: "Download", exact: true }),
      ).toBeDisabled();
      await page.waitForFunction(() => (window as any).pool.size === 0);
      await call("card", true);
      await page
        .getByRole("button", { name: "Load material", exact: true })
        .click();
      await page.getByRole("toolbar").waitFor();
      const downloadEvent = page.waitForEvent("download");
      await page
        .getByRole("button", { name: "Download zip", exact: true })
        .click();
      const download = await downloadEvent;
      expect(download.suggestedFilename()).toBe("studiotwin-material.zip");
      // Canvas size follows the actual host, not a mount-time window measurement.
      const oldWidth = await page
        .locator("canvas")
        .evaluate((c) => (c as HTMLCanvasElement).width);
      await page.setViewportSize({ width: 900, height: 1200 });
      await page.waitForFunction(
        (old) =>
          (document.querySelector("canvas") as HTMLCanvasElement)?.width !==
          old,
        oldWidth,
      );
      await call("unmount");
      expect(await page.locator("canvas").count()).toBe(0);
      expect(await page.evaluate(() => (window as any).pool.size)).toBe(0);
      expect(errors).toEqual([]);
    } finally {
      await browser.close();
    }
  },
  90_000,
);
