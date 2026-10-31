import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { build } from "esbuild";
import { chromium, type Browser, type Page } from "@playwright/test";

export interface WorkspaceHarness {
  page: Page;
  url: string;
  errors: string[];
  blocked: string[];
  state: () => Promise<any>;
  close: () => Promise<void>;
}

export async function openWorkspace(
  options: {
    tab?: string;
    configured?: boolean;
    settingsDoor?: boolean;
    backendOnly?: boolean;
    largeLibrary?: boolean;
  } = {},
): Promise<WorkspaceHarness> {
  const root = process.cwd();
  const python =
    process.env.WORKSPACE_TEST_PYTHON ||
    [resolve(root, ".venv/bin/python")].find(existsSync) ||
    "python";
  const child = spawn(python, ["-B", "tests/workspace/loopback_backend.py"], {
    cwd: root,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let diagnostics = "";
  child.stderr!.on("data", (chunk) => {
    diagnostics += chunk.toString();
  });
  let browser: Browser | undefined;
  try {
    const url = await new Promise<string>((accept, reject) => {
      let output = "";
      const timer = setTimeout(
        () => reject(Error("Backend startup timed out: " + diagnostics)),
        20000,
      );
      child.once("exit", (code) => {
        clearTimeout(timer);
        reject(Error(`Backend exited ${code}: ${diagnostics}`));
      });
      child.stdout!.on("data", (chunk) => {
        output += chunk.toString();
        for (const line of output.split("\n")) {
          try {
            const value = JSON.parse(line);
            if (value.url) {
              clearTimeout(timer);
              accept(value.url);
            }
          } catch {}
        }
      });
    });
    for (let i = 0; ; i++) {
      try {
        if ((await fetch(url + "/__test/state")).ok) break;
      } catch (error) {
        if (i === 100) throw error;
      }
      if (i === 100) throw Error("Backend not healthy");
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    if (options.largeLibrary)
      await fetch(url + "/__test/large-library", { method: "POST" });
    if (options.configured === false)
      await fetch(url + "/__test/configured/false", { method: "POST" });
    const bundle = options.backendOnly
      ? null
      : await build({
          nodePaths: process.env.WORKSPACE_TEST_NODE_MODULES
            ? [process.env.WORKSPACE_TEST_NODE_MODULES]
            : [],
          stdin: {
            resolveDir: root,
            loader: "tsx",
            contents: `
        import React from 'react'; import {createRoot} from 'react-dom/client';
        import {QueryClientProvider} from '@tanstack/react-query';
        import {queryClient} from '@hermes/plugin-sdk';
        import {StudioTwinPage} from './src/pages/studiotwin-page.tsx';
        import {registerWorkspaceAndChrome} from './src/chrome/navigation.tsx';
        const rows=[],events={};
        window.emitEvent=(type,event={})=>(events[type]||[]).forEach(fn=>fn(event));
        const ctx={source:'workspace-test', register:r=>{rows.push(r); return ()=>{}},registerMany:rs=>{rows.push(...rs);return ()=>{}},
          onDispose:()=>{},onEvent:(type,fn)=>{(events[type]??=[]).push(fn);return()=>{}},os:{openExternal:async()=>true,revealPath:async()=>true},
          setInterval:(fn,ms)=>{const id=setInterval(fn,ms);return()=>clearInterval(id)},setTimeout:(fn,ms)=>{const id=setTimeout(fn,ms);return()=>clearTimeout(id)},
          addEventListener:(target,name,fn,opts)=>{target.addEventListener(name,fn,opts);return()=>target.removeEventListener(name,fn,opts)},
          ${options.settingsDoor === false ? "" : "openPluginSettings:id=>window.settings.push(id),"}
          rest:async(path,opts={})=>{
            window.requests.push({path,method:opts.method||'GET'});
            let body=opts.body, headers={};
            if(opts.upload){const form=new FormData();form.append('file',new File([opts.upload.bytes],opts.upload.filename,{type:opts.upload.contentType}));body=form}
            else if(body!==undefined){headers['Content-Type']='application/json';body=JSON.stringify(body)}
            const response=await fetch('/api/plugins/hermes-studiotwin'+path,{method:opts.method||'GET',headers,body});
            if(!response.ok)throw Error('HTTP '+response.status+': '+await response.text());return response.json();
          }};
        registerWorkspaceAndChrome(ctx);
        window.registrations=rows;
        window.runPalette=index=>rows.filter(r=>r.area==='palette')[index].data.run();
        const chips=rows.filter(r=>r.area==='statusBar.right');
        createRoot(document.getElementById('root')).render(<QueryClientProvider client={queryClient}>
          <div id='chips'>{chips.map(r=><React.Fragment key={r.id}>{r.render?r.render():r.data?.render?r.data.render():null}</React.Fragment>)}</div>
          ${options.tab ? `<StudioTwinPage ctx={ctx} initialTab={${JSON.stringify(options.tab)}}/>` : `{rows.find(r=>r.area==='routes').render()}`}
        </QueryClientProvider>);
      `,
          },
          bundle: true,
          write: false,
          format: "esm",
          jsx: "automatic",
          plugins: [
            {
              name: "workspace-sdk",
              setup(b) {
                b.onResolve({ filter: /^@hermes\/plugin-sdk$/ }, () => ({
                  path: "sdk",
                  namespace: "workspace",
                }));
                b.onLoad({ filter: /.*/, namespace: "workspace" }, () => ({
                  resolveDir: root,
                  loader: "js",
                  contents: `
          import React,{useSyncExternalStore} from 'react';
          import {QueryClient} from '@tanstack/react-query';export {useQuery,useMutation,useQueryClient} from '@tanstack/react-query';
          export const queryClient=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}});
          export const ROUTES_AREA='routes',SIDEBAR_NAV_AREA='sidebar.nav',PALETTE_AREA='palette',STATUSBAR_AREAS={right:'statusBar.right',left:'statusBar.left'};
          export const TOOL_MEDIA_RENDERER_AREA='transcript.toolMedia',TRANSCRIPT_DIRECTIVE_AREA='transcript.directives';
          export const Button=({size,variant,asChild,...p})=>React.createElement('button',p);
          export const Badge=({size,variant,...p})=>React.createElement('span',p);
          export const Codicon=()=>null;
          export const Skeleton=p=>React.createElement('div',p);
          export const EmptyState=({title,description,action})=>React.createElement('div',null,title,description,action);
          export const ErrorState=({title,description,children})=>React.createElement('div',null,title,description,children);
          export const atom=value=>{const listeners=new Set();return{get:()=>value,set:next=>{value=next;listeners.forEach(fn=>fn(value))},subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)}}};
          export const useValue=a=>useSyncExternalStore(a.subscribe,a.get,a.get);
          const profile=atom('alpha'),connectionId=atom(null),activeSessionId=atom('origin-chat');
          window.switchScope=(kind,value)=>({profile,connectionId,activeSessionId}[kind].set(value));
          export const host={state:{profile,connectionId,activeSessionId},navigate:path=>window.navigations.push(path),notify:n=>{window.notifications.push(n);return 'notice'},composer:{submit:(session,text)=>{window.messages.push({session,text});return true}}};
        `,
                }));
              },
            },
          ],
        });
    browser = await chromium.launch({
      executablePath: existsSync("/opt/google/chrome/chrome")
        ? "/opt/google/chrome/chrome"
        : undefined,
      headless: true,
      args: ["--no-sandbox", "--enable-unsafe-swiftshader"],
    });
    const page = await browser.newPage({
      viewport: { width: 1280, height: 1000 },
    });
    page.setDefaultTimeout(10000);
    const errors: string[] = [],
      blocked: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    // All UI HTTP must be this real loopback server. No page.route fake API data.
    await page.route("**/*", (route) => {
      const parsed = new URL(route.request().url());
      if (
        parsed.protocol === "data:" ||
        parsed.protocol === "blob:" ||
        parsed.hostname === "127.0.0.1"
      )
        return route.continue();
      blocked.push(parsed.origin);
      return route.abort("blockedbyclient");
    });
    await page.goto(url);
    await page.evaluate(() =>
      Object.assign(window, {
        requests: [],
        messages: [],
        settings: [],
        navigations: [],
        notifications: [],
      }),
    );
    if (bundle)
      await page.addScriptTag({
        type: "module",
        content: bundle.outputFiles[0].text,
      });
    return {
      page,
      url,
      errors,
      blocked,
      state: () => fetch(url + "/__test/state").then((r) => r.json()),
      close: async () => {
        await browser!.close();
        await stop(child);
      },
    };
  } catch (error) {
    await browser?.close();
    await stop(child);
    throw error;
  }
}
async function stop(child: ChildProcess) {
  if (child.exitCode !== null) return;
  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => child.kill("SIGKILL"), 5000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
    child.kill("SIGTERM");
  });
}
