import { build } from "esbuild";
import { readFileSync } from "node:fs";
import { openWorkspace } from "../workspace/browser-harness";

// Only host-owned SDK/React modules are fixtures. plugin.js is served byte-for-byte.
const hostSource = `export {createElement,cloneElement,isValidElement,useId,useState,useEffect,useRef,useSyncExternalStore} from 'react';
export {jsx,jsxs,Fragment} from 'react/jsx-runtime';
export {createRoot} from 'react-dom/client';
export {QueryClient,QueryClientProvider,useQuery,useMutation,useQueryClient} from '@tanstack/react-query';`;
const sdkSource = `import * as R from './host.js';
export const queryClient=new R.QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}});
export const useQuery=R.useQuery,useMutation=R.useMutation,useQueryClient=R.useQueryClient;
export const Button=({size,variant,asChild,...p})=>R.createElement('button',p);
export const Badge=({size,variant,...p})=>R.createElement('span',p);
export const Codicon=()=>null,Skeleton=p=>R.createElement('div',p);
export const EmptyState=({title,description,action})=>R.createElement('div',null,title,description,action);
export const ErrorState=({title,description,children})=>R.createElement('div',null,title,description,children);
export const atom=value=>{const listeners=new Set();return{get:()=>value,set:v=>{value=v;listeners.forEach(f=>f(v))},subscribe:f=>{listeners.add(f);return()=>listeners.delete(f)}}};
export const useValue=a=>R.useSyncExternalStore(a.subscribe,a.get,a.get);
export const host={state:{profile:atom('visual-fixture'),connectionId:atom(null),activeSessionId:atom('origin-chat')},navigate:p=>window.navigations.push(p),notify:n=>window.notifications.push(n),composer:{submit:(session,text)=>{window.messages.push({session,text});return true}}};
export const ROUTES_AREA='routes',SIDEBAR_NAV_AREA='sidebar.nav',PALETTE_AREA='palette',STATUSBAR_AREAS={right:'statusBar.right'};
export const TOOL_MEDIA_RENDERER_AREA='transcript.toolMedia',TRANSCRIPT_DIRECTIVE_AREA='transcript.directives';
export const registerPlugin=p=>{window.captured=p};`;

export async function openVisual() {
  const h = await openWorkspace({ backendOnly: true, deviceScaleFactor: 2 });
  try {
    const host = await build({
      stdin: { contents: hostSource, resolveDir: process.cwd(), loader: "js" },
      bundle: true,
      write: false,
      format: "esm",
      define: { "process.env.NODE_ENV": '"production"' },
    });
    const modules: Record<string, string> = {
      "plugin.js": readFileSync("desktop/plugin.js", "utf8"),
      "host.js": host.outputFiles[0].text,
      "sdk.js": sdkSource,
    };
    await h.page.route("**/__visual/*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/javascript",
        body:
          modules[new URL(route.request().url()).pathname.split("/").at(-1)!] ??
          "",
      }),
    );
    await h.page.setViewportSize({ width: 1440, height: 1100 });
    await h.page.addScriptTag({
      type: "importmap",
      content: JSON.stringify({
        imports: {
          "@hermes/plugin-sdk": h.url + "/__visual/sdk.js",
          react: h.url + "/__visual/host.js",
          "react/jsx-runtime": h.url + "/__visual/host.js",
        },
      }),
    });
    await h.page.addScriptTag({
      type: "module",
      content: `import * as R from '/__visual/host.js';import * as sdk from '/__visual/sdk.js';import plugin from '/__visual/plugin.js';
      Object.assign(window,{R,sdk,plugin});`,
    });
    await h.page.waitForFunction(() => !!(window as any).plugin);
    await h.page.evaluate(() => {
      const w = window as any,
        { R, sdk, plugin } = w;
      Object.assign(w, {
        registrations: [],
        events: {},
        disposers: [],
        messages: [],
        navigations: [],
        notifications: [],
      });
      w.emitEvent = (type: string) =>
        (w.events[type] || []).forEach((fn: any) => fn({ type }));
      const ctx = {
        source: "visual-qa",
        register: (r: any) => {
          w.registrations.push(r);
          return () => {};
        },
        onDispose: (f: any) => w.disposers.push(f),
        onEvent: (type: string, fn: any) => {
          (w.events[type] ??= []).push(fn);
          return () => {};
        },
        os: { openExternal: async () => true, revealPath: async () => true },
        rest: async (path: string, opts: any = {}) => {
          const response = await fetch(
            "/api/plugins/hermes-studiotwin" + path,
            {
              method: opts.method || "GET",
              headers: opts.body ? { "Content-Type": "application/json" } : {},
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
      w.directive = (kind: string, attrs: any) =>
        w.registrations
          .find((r: any) => r.data?.name === "studiotwin-" + kind)
          .data.render({
            attrs,
            streaming: false,
            source: "StudioTwin QA " + kind,
            sessionId: "origin-chat",
          });
      w.renderDirective = (kind: string, attrs: any) =>
        w.mount(w.directive(kind, attrs));
      w.workspace = () =>
        w.mount(
          R.createElement(
            "div",
            null,
            R.createElement(
              "header",
              { id: "chips" },
              ...w.registrations
                .filter((r: any) => r.area === "statusBar.right")
                .map((r: any) =>
                  R.createElement(
                    R.Fragment,
                    { key: r.id },
                    (r.render ?? r.data.render)(),
                  ),
                ),
            ),
            R.createElement(
              "nav",
              { "aria-label": "Plugin sidebar" },
              ...w.registrations
                .filter((r: any) => r.area === "sidebar.nav")
                .map((r: any) =>
                  R.createElement(
                    "button",
                    {
                      key: r.id,
                      onClick: () => sdk.host.navigate(r.data.path),
                    },
                    r.data.label,
                  ),
                ),
            ),
            w.registrations.find((r: any) => r.area === "routes").render(),
            R.createElement(
              "aside",
              { "aria-label": "StudioTwin palette" },
              ...w.registrations
                .filter((r: any) => r.area === "palette")
                .map((r: any) =>
                  R.createElement(
                    "button",
                    { key: r.id, onClick: r.data.run },
                    r.data.title ?? r.data.label ?? r.id,
                  ),
                ),
            ),
          ),
        );
    });
    return h;
  } catch (e) {
    await h.close();
    throw e;
  }
}
export async function upload(
  h: Awaited<ReturnType<typeof openVisual>>,
  fixture: string,
) {
  const response = await fetch(
    h.url + "/api/plugins/hermes-studiotwin/upload",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: fixture.split("/").at(-1),
        data: readFileSync("tests/fixtures/media/" + fixture).toString(
          "base64",
        ),
      }),
    },
  );
  if (!response.ok)
    throw Error("Fixture upload failed: " + (await response.text()));
  return (await response.json()).path as string;
}
