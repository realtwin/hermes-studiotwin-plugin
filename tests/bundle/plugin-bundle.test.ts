// @vitest-environment node
import { expect, it } from "vitest";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import ts from "typescript";
import { build } from "esbuild";
import { expect as browserExpect } from "@playwright/test";
import { openWorkspace } from "../workspace/browser-harness";

const root = process.cwd();
const artifact = resolve(root, "desktop/plugin.js");
const read = (p: string) => readFileSync(resolve(root, p), "utf8");
const directives = [
  "model",
  "audio",
  "env",
  "material",
  "image",
  "video",
  "task",
  "job",
  "concept",
].map((n) => "studiotwin-" + n);
const mediaIds = ["model", "audio", "env", "material", "image", "video"].map(
  (n) => "studiotwin-" + n + "-media",
);
function sources(dir: string): string[] {
  return readdirSync(resolve(root, dir), { withFileTypes: true }).flatMap(
    (e) =>
      e.isDirectory() ? sources(dir + "/" + e.name) : [dir + "/" + e.name],
  );
}
it("ships a single compiled ESM artifact with only namespace SDK imports and allowed external modules", () => {
  expect(existsSync(artifact), "build and commit desktop/plugin.js").toBe(true);
  const text = readFileSync(artifact, "utf8");
  const file = ts.createSourceFile(
    "plugin.js",
    text,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.JS,
  );
  const imports: string[] = [];
  function visit(node: ts.Node) {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
      if (node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier))
        imports.push(node.moduleSpecifier.text);
      if (
        ts.isImportDeclaration(node) &&
        (node.moduleSpecifier as ts.StringLiteral).text === "@hermes/plugin-sdk"
      )
        expect(
          node.importClause?.namedBindings &&
            ts.isNamespaceImport(node.importClause.namedBindings),
          "no named SDK value imports at ESM link time",
        ).toBe(true);
    }
    if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword
    )
      throw Error("Unbundled dynamic import");
    ts.forEachChild(node, visit);
  }
  visit(file);
  expect([...new Set(imports)].sort()).toEqual(
    ["@hermes/plugin-sdk", "react", "react/jsx-runtime"].sort(),
  );
  expect(text).not.toMatch(/\bnode:|\beval\s*\(|\bnew\s+Function\s*\(/);
  for (const path of sources("src").filter(
    (p) => /\.tsx?$/.test(p) && !p.endsWith(".d.ts"),
  )) {
    const source = ts.createSourceFile(
      path,
      read(path),
      ts.ScriptTarget.Latest,
      true,
    );
    for (const node of source.statements) {
      if (
        !ts.isImportDeclaration(node) ||
        (node.moduleSpecifier as ts.StringLiteral).text !==
          "@hermes/plugin-sdk" ||
        node.importClause?.isTypeOnly
      )
        continue;
      expect(
        node.importClause?.namedBindings &&
          ts.isNamespaceImport(node.importClause.namedBindings),
        path,
      ).toBe(true);
    }
  }
});
it("bundles the complete discoverable workflow skill and documents the manifest settings", () => {
  const skill = read("skills/studiotwin/SKILL.md"),
    readme = read("README.md");
  expect(skill).toMatch(/^---\nname: studiotwin\n/);
  expect(skill).toMatch(/version: 0\.2\.0/);
  const catalog = JSON.parse(read("tests/fixtures/tools-list-2026-10-30.json"));
  const tools = catalog.tools ?? catalog.result?.tools;
  expect(tools).toHaveLength(45);
  for (const tool of tools) expect(skill, tool.name).toContain(tool.name);
  for (const name of directives) expect(skill).toContain("::" + name);
  for (const name of [
    "glb_stats.py",
    "render_preview.mjs",
    "blender_handoff.py",
    "sfx_tool.py",
    "studiotwin_get_job_status",
    "POST /provenance",
    "notify=True",
  ])
    expect(skill).toContain(name);
  const manifest = JSON.parse(read("plugin.json"));
  // The pinned portable host auto-discovers skills/*/SKILL.md and warns on a
  // top-level `skills` key. The real host discovery is checked by verify_v07.py.
  expect(manifest.skills).toBeUndefined();
  for (const name of Object.keys(
    manifest.extensions["com.nousresearch.hermes"].config_schema,
  ))
    expect(readme).toContain("`" + name + "`");
  expect(readme).toContain("hermes plugins install realtwin/hermes-studiotwin");
  expect(read("after-install.md")).toContain("STUDIOTWIN_API_KEY");
});

// Supply host-owned modules separately. The production artifact is served byte-for-byte,
// never transformed/rebundled against the SDK fixture: missing ESM exports must fail here.
const hostSource = `
export {createElement,cloneElement,isValidElement,useId,useState,useEffect,useRef,useSyncExternalStore} from 'react';
export {jsx,jsxs,Fragment} from 'react/jsx-runtime';
export {createRoot} from 'react-dom/client';
export {QueryClient,QueryClientProvider,useQuery,useMutation,useQueryClient} from '@tanstack/react-query';
`;
function sdkSource(legacy: boolean) {
  return `
import * as R from './host.js';
export const queryClient=new R.QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}});
export const useQuery=R.useQuery,useMutation=R.useMutation,useQueryClient=R.useQueryClient;
export const Button=({size,variant,asChild,...p})=>R.createElement('button',p);
export const Badge=({size,variant,...p})=>R.createElement('span',p);
export const Codicon=()=>null,Skeleton=p=>R.createElement('div',p);
export const EmptyState=({title,description,action})=>R.createElement('div',null,title,description,action);
export const ErrorState=({title,description,children})=>R.createElement('div',null,title,description,children);
export const atom=value=>{const listeners=new Set();return{get:()=>value,set:v=>{value=v;listeners.forEach(f=>f(v))},subscribe:f=>{listeners.add(f);return()=>listeners.delete(f)}}};
export const useValue=a=>R.useSyncExternalStore(a.subscribe,a.get,a.get);
export const host={state:{profile:atom('alpha'),connectionId:atom(null),activeSessionId:atom('origin-chat')},navigate:p=>window.navigations.push(p),notify:n=>window.notifications.push(n),composer:{submit:()=>true}};
${
  legacy
    ? ""
    : `export const ROUTES_AREA='routes',SIDEBAR_NAV_AREA='sidebar.nav',PALETTE_AREA='palette',STATUSBAR_AREAS={right:'statusBar.right'};
export const TOOL_MEDIA_RENDERER_AREA='transcript.toolMedia',TRANSCRIPT_DIRECTIVE_AREA='transcript.directives';
export const registerPlugin=p=>{window.captured=p};`
}
`;
}
for (const legacy of [false, true])
  it(`Chromium imports the committed bundle, registers and renders all surfaces (${legacy ? "missing area/registration exports" : "full SDK"})`, async () => {
    const h = await openWorkspace({ backendOnly: true });
    try {
      const host = await build({
        stdin: { contents: hostSource, resolveDir: root, loader: "js" },
        bundle: true,
        write: false,
        format: "esm",
        define: { "process.env.NODE_ENV": '"production"' },
      });
      const modules: Record<string, string> = {
        "plugin.js": readFileSync(artifact, "utf8"),
        "host.js": host.outputFiles[0].text,
        "sdk.js": sdkSource(legacy),
      };
      await h.page.route("**/__bundle/*", (route) => {
        const name = new URL(route.request().url()).pathname.split("/").at(-1)!;
        return route.fulfill({
          status: 200,
          contentType: "application/javascript",
          body: modules[name] ?? "",
        });
      });
      await h.page.addScriptTag({
        type: "importmap",
        content: JSON.stringify({
          imports: {
            "@hermes/plugin-sdk": h.url + "/__bundle/sdk.js",
            react: h.url + "/__bundle/host.js",
            "react/jsx-runtime": h.url + "/__bundle/host.js",
          },
        }),
      });
      await h.page.addScriptTag({
        type: "module",
        content: `
      import * as R from '/__bundle/host.js'; import * as sdk from '/__bundle/sdk.js';
      import plugin from '/__bundle/plugin.js';
      window.R=R; window.sdk=sdk; window.plugin=plugin;
    `,
      });
      await h.page.waitForFunction(() => !!(window as any).plugin);
      await h.page.evaluate(async () => {
        const w = window as any,
          { R, sdk, plugin } = w;
        w.navigations = [];
        w.notifications = [];
        w.registrations = [];
        w.disposers = [];
        w.events = {};
        w.emitEvent = (type: string) => (w.events[type] || []).forEach((fn: any) => fn({type}));
        w.savedFixtures = {};
        const ctx = {
          source: "bundle-test",
          register: (r: any) => {
            w.registrations.push(r);
            return () => {};
          },
          onDispose: (f: any) => w.disposers.push(f),
          onEvent: (type: string, fn: any) => { (w.events[type] ??= []).push(fn); return () => {}; },
          os: { openExternal: async () => true, revealPath: async () => true },
          rest: async (path: string, opts: any = {}) => {
            const response = await fetch(
              "/api/plugins/hermes-studiotwin" + path,
              {
                method: opts.method || "GET",
                headers: opts.body
                  ? { "Content-Type": "application/json" }
                  : {},
                body: opts.body ? JSON.stringify(opts.body) : undefined,
              },
            );
            if (!response.ok) throw Error("HTTP " + response.status);
            return response.json();
          },
        };
        plugin.register(ctx);
        w.reactRoot = R.createRoot(document.getElementById("root"));
        w.mount = (element: any) =>
          w.reactRoot.render(
            R.createElement(
              R.QueryClientProvider,
              { client: sdk.queryClient },
              element,
            ),
          );
        w.mountRows = () =>
          w.mount(
            R.createElement(
              R.Fragment,
              null,
              ...w.registrations
                .filter((r: any) => r.render)
                .map((r: any) =>
                  R.createElement(R.Fragment, { key: r.id }, r.render()),
                ),
            ),
          );
        w.mountRows();
      });
      const rows = await h.page.evaluate(() =>
        (window as any).registrations.map((r: any) => ({
          id: r.id,
          area: r.area,
          name: r.data?.name,
          path: r.data?.path,
          tools: r.data?.tools,
        })),
      );
      expect(
        rows
          .filter((r: any) => r.area === "transcript.directives")
          .map((r: any) => r.name)
          .sort(),
      ).toEqual([...directives].sort());
      expect(
        rows
          .filter((r: any) => r.area === "transcript.toolMedia")
          .map((r: any) => r.id)
          .sort(),
      ).toEqual(legacy ? [] : [...mediaIds].sort());
      expect(
        rows.filter((r: any) => r.area === "routes").map((r: any) => r.path),
      ).toEqual(["/studiotwin"]);
      expect(
        rows
          .filter((r: any) => r.area === "sidebar.nav")
          .map((r: any) => r.path),
      ).toEqual(["/studiotwin"]);
      expect(rows.filter((r: any) => r.area === "palette")).toHaveLength(6);
      expect(
        rows.filter((r: any) => r.area === "statusBar.right"),
      ).toHaveLength(2);
      expect(new Set(rows.map((r: any) => r.id)).size).toBe(rows.length);
      expect(
        await h.page.evaluate(
          () => (window as any).captured === (window as any).plugin,
        ),
      ).toBe(!legacy);
      await browserExpect(
        h.page.getByRole("tab", { name: "Library", exact: true }),
      ).toBeVisible();
      await browserExpect(
        h.page.getByRole("button", {
          name: "StudioTwin 500 credits",
          exact: true,
        }),
      ).toBeVisible();
      await browserExpect(
        h.page.getByRole("button", {
          name: "1 active StudioTwin jobs",
          exact: true,
        }),
      ).toBeVisible();
      await h.page.evaluate(() => {
        const w = window as any;
        w.registrations
          .filter((r: any) => r.area === "palette")
          .forEach((r: any) => r.data.run());
      });
      expect(
        await h.page.evaluate(() => (window as any).navigations),
      ).toContain("/studiotwin");
      // Every directive renders even while streamed/incomplete; none may throw on agent text.
      for (const name of directives) {
        await h.page.evaluate((name) => {
          const w = window as any;
          w.mount(
            w.registrations
              .find((r: any) => r.data?.name === name)
              .data.render({
                attrs: {},
                streaming: true,
                source: "waiting " + name,
                sessionId: "origin-chat",
              }),
          );
        }, name);
        // Empty streamed env/material cards intentionally render null.
        await h.page.evaluate(() => new Promise(requestAnimationFrame));
      }
      // Exercise the real finished viewers via the bundle, with local fixture files copied
      // through the real plugin upload route, never arbitrary cloud URLs.
      const fixtures: Record<string, string> = {
        model: "model/static-cube.glb",
        audio: "audio/tone-48k.wav",
        env: "env/equirect-64x32.png",
        material: "material/pbr-albedo.png",
        image: "image/concept-64.png",
        video: "video/testsrc-32.mp4",
      };
      for (const [kind, fixture] of Object.entries(fixtures)) {
        const data = readFileSync(
          resolve(root, "tests/fixtures/media", fixture),
        ).toString("base64");
        const saved = await fetch(
          h.url + "/api/plugins/hermes-studiotwin/upload",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename: fixture.split("/").at(-1), data }),
          },
        ).then((r: any) => r.json());
        expect(saved.path).toBeTruthy();
        await h.page.evaluate(({kind,path}) => { (window as any).savedFixtures[kind] = path }, {kind,path:saved.path});
        for (const mode of legacy ? ["directive"] : ["directive", "media"]) {
          await h.page.evaluate(async () => {
            (window as any).mount(null);
            await new Promise(requestAnimationFrame);
          });
          await h.page.evaluate(
            ({ kind, path, mode }) => {
              const w = window as any;
              if (mode === "directive") {
                const attrs =
                  kind === "material"
                    ? { maps: JSON.stringify({ albedo: { path } }) }
                    : { path };
                w.mount(
                  w.registrations
                    .find((r: any) => r.data?.name === "studiotwin-" + kind)
                    .data.render({
                      attrs,
                      source: "fixture " + kind,
                      streaming: false,
                      sessionId: "origin-chat",
                    }),
                );
              } else {
                const names: Record<string, string> = {
                  model: "image_to_3d_mesh",
                  audio: "text_to_sound_effect",
                  env: "text-to-environment-map",
                  material: "text-to-material",
                  image: "concept-lab-img-fn",
                  video: "text_to_motion",
                };
                const props = {
                  toolName: "mcp__studiotwin__" + names[kind],
                  toolCallId: "fixture-" + kind,
                  file: {
                    path,
                    name: path.split("/").at(-1),
                    kind:
                      kind === "audio"
                        ? "audio"
                        : kind === "video"
                          ? "video"
                          : kind === "model"
                            ? "file"
                            : "image",
                  },
                  args: {},
                  result:
                    kind === "material" ? { maps: { albedo: { path } } } : {},
                  sessionId: "origin-chat",
                  fallback: w.R.createElement(
                    "p",
                    null,
                    "unexpected media fallback",
                  ),
                };
                w.mount(
                  w.registrations
                    .find((r: any) => r.id === "studiotwin-" + kind + "-media")
                    .data.render(props),
                );
              }
            },
            { kind, path: saved.path, mode },
          );
          if (kind === "model") {
            await h.page
              .getByRole("button", { name: "Click to load 3D", exact: true })
              .click();
            await browserExpect(
              h.page.locator("[data-model-stats]"),
            ).toContainText("triangles");
            await browserExpect(h.page.getByRole('button', {name:'Auto-rotate',exact:true})).toHaveAttribute('aria-pressed','true');
          } else if (kind === "image")
            await browserExpect(h.page.locator("img").first()).toBeVisible();
          else if (kind === "video")
            await h.page.waitForFunction(
              () => document.querySelector("video")?.readyState! >= 2,
            );
          else {
            if (kind === "env")
              await h.page
                .getByRole("button", { name: "Load environment", exact: true })
                .click();
            if (kind === "material")
              await h.page
                .getByRole("button", { name: "Load material", exact: true })
                .click();
            await browserExpect(h.page.locator("canvas").first()).toBeVisible();
            if (kind === "env")
              await browserExpect(
                h.page.getByRole("toolbar", { name: "Environment controls" }),
              ).toBeVisible();
            if (kind === "material")
              await browserExpect(
                h.page.getByRole("toolbar", { name: "Material controls" }),
              ).toBeVisible();
          }
          await browserExpect(
            h.page.getByText("unexpected media fallback", { exact: true }),
          ).toHaveCount(0);
        }
      }
      if (!legacy) {
        // Settings are changed in the real loopback host config, with the production event.
        const change = async (settings: Record<string, unknown>) => {
          await h.page.evaluate(async settings => {
            const response = await fetch('/__test/settings', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)});
            if (!response.ok) throw Error('settings failed');
            (window as any).emitEvent('plugin.hermes-studiotwin.settings.changed');
          }, settings);
        };
        await change({webgl_limit:1, auto_rotate:false});
        for (const kind of ['env','material']) {
          await h.page.evaluate(kind => {
            const w=window as any, R=w.R, path=w.savedFixtures[kind];
            const render=w.registrations.find((r:any)=>r.id==='studiotwin-'+kind+'-media').data.render;
            w.mount(R.createElement(R.Fragment,null,...[0,1].map(i=>R.createElement('div',{key:kind+i},render({
              toolName:kind==='env'?'mcp__studiotwin__text-to-environment-map':'mcp__studiotwin__text-to-material',
              toolCallId:kind+i,file:{path,name:path.split('/').at(-1),kind:'image'},args:{},
              result:kind==='material'?{maps:{albedo:{path}}}:{},fallback:R.createElement('p',null,'unexpected limited fallback')
            })))));
          },kind);
          const load=h.page.getByRole('button',{name:kind==='env'?/Load environment$/:/Load material$/});
          await load.first().click();
          await browserExpect(h.page.getByRole('toolbar',{name:kind==='env'?'Environment controls':'Material controls'})).toHaveCount(1);
          await load.click();
          await browserExpect(load).toHaveCount(1);
          await browserExpect(h.page.getByRole('toolbar',{name:kind==='env'?'Environment controls':'Material controls'})).toHaveCount(1);
          await browserExpect(h.page.locator('canvas')).toHaveCount(1);
          await browserExpect(h.page.getByText('unexpected limited fallback',{exact:true})).toHaveCount(0);
        }
        await h.page.evaluate(() => {
          const w = window as any, R = w.R;
          const render = w.registrations.find((r:any)=>r.id==='studiotwin-model-media').data.render;
          w.mount(R.createElement(R.Fragment,null,...[0,1].map(i=>R.createElement('div',{key:i},render({
            toolName:'mcp__studiotwin__image_to_3d_mesh', toolCallId:'pool-'+i,
            file:{path:w.savedFixtures.model,name:'static-cube.glb',kind:'file'},args:{},result:{},fallback:R.createElement('p',null,'model fallback')
          })))));
        });
        await h.page.getByRole('button',{name:'Click to load 3D',exact:true}).first().click();
        await browserExpect(h.page.getByRole('button',{name:'Auto-rotate',exact:true})).toHaveAttribute('aria-pressed','false');
        await h.page.getByRole('button',{name:'Click to load 3D',exact:true}).click();
        await browserExpect(h.page.getByRole('button',{name:/Click to load 3D$/})).toHaveCount(1);
        await browserExpect(h.page.locator('[data-model-stats]')).toHaveCount(1);
        await browserExpect(h.page.locator('canvas')).toHaveCount(1);
        await change({auto_rotate:true});
        const spin = h.page.getByRole('button',{name:'Auto-rotate',exact:true});
        await browserExpect(spin).toHaveAttribute('aria-pressed','true');
        await spin.click();
        await change({auto_rotate:false});
        await change({auto_rotate:true});
        await browserExpect(spin).toHaveAttribute('aria-pressed','false');
        // Already mounted rich viewers disappear without re-registration.
        await change({inline_cards:false});
        await browserExpect(h.page.getByText('model fallback',{exact:true})).toHaveCount(2);
        await browserExpect(h.page.locator('canvas')).toHaveCount(0);
        await h.page.evaluate(() => {
          const w = window as any, R=w.R;
          w.mount(R.createElement(R.Fragment,null,...w.registrations.filter((r:any)=>r.data?.tools).map((r:any)=>
            R.createElement('div',{key:r.id},r.data.render({toolName:r.data.tools[0],file:{path:w.savedFixtures.image,name:'image.png',kind:'image'},args:{},result:{},fallback:R.createElement('p',null,'disabled '+r.id)}))),
            ...w.registrations.filter((r:any)=>r.data?.name?.startsWith('studiotwin-')).map((r:any)=>
              R.createElement('div',{key:r.id},r.data.render({attrs:{path:w.savedFixtures.model},streaming:false,source:'plain '+r.data.name})))));
        });
        await browserExpect(h.page.getByText(/^disabled studiotwin-/)).toHaveCount(6);
        await browserExpect(h.page.getByText(/^plain studiotwin-/)).toHaveCount(9);
        await change({inline_cards:true,auto_rotate:true,webgl_limit:4});
      }
      const state = await h.state();
      for (const [kind, id] of [
        ["task", state.jobs.queued],
        ["job", state.jobs.failed],
        ["concept", state.concept],
      ]) {
        await h.page.evaluate(
          ({ kind, id }) => {
            const w = window as any;
            w.mount(
              w.registrations
                .find((r: any) => r.data?.name === "studiotwin-" + kind)
                .data.render({
                  attrs: { id },
                  streaming: false,
                  source: "fixture " + kind,
                  sessionId: "origin-chat",
                }),
            );
          },
          { kind, id },
        );
        await browserExpect(
          h.page.locator("[data-studiotwin-task]"),
        ).not.toHaveAttribute("data-studiotwin-task", "loading");
      }
      // Foreign tool ownership must preserve the host's fallback for every renderer.
      if (!legacy) {
        await h.page.evaluate(() => {
          const w = window as any,
            R = w.R;
          w.mount(
            R.createElement(
              R.Fragment,
              null,
              ...w.registrations
                .filter((r: any) => r.area === "transcript.toolMedia")
                .map((r: any) =>
                  R.createElement(
                    "div",
                    { key: r.id },
                    r.data.render({
                      toolName: "terminal",
                      file: { path: "/nope", name: "image.png", kind: "image" },
                      args: {},
                      result: {},
                      fallback: R.createElement(
                        "span",
                        null,
                        "builtin " + r.id,
                      ),
                    }),
                  ),
                ),
            ),
          );
        });
        await browserExpect(h.page.getByText(/^builtin /)).toHaveCount(6);
      }
      await h.page.evaluate(() => {
        const w = window as any;
        w.reactRoot.unmount();
        w.disposers.forEach((f: any) => f());
        w.sdk.queryClient.clear();
      });
      expect(state.submissions).toEqual([]);
      expect(state.ledger.filter((r: any) => r.event === "debit")).toEqual([]);
      expect(h.errors).toEqual([]);
      expect(h.blocked).toEqual([]);
    } catch (error) {
      throw new Error(
        String(error) + "\nChromium errors: " + JSON.stringify(h.errors),
      );
    } finally {
      await h.close();
    }
  }, 120000);
