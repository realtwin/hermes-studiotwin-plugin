// @vitest-environment node
import { afterEach, expect, it } from "vitest";
import { expect as browserExpect } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import { openWorkspace, type WorkspaceHarness } from "./browser-harness";

let harness: WorkspaceHarness | undefined;
async function mount(options: Parameters<typeof openWorkspace>[0] = {}) {
  harness = await openWorkspace(options);
  await harness.page
    .getByRole("tab", { name: options.tab || "Library", exact: true })
    .waitFor();
  return harness;
}
afterEach(async () => {
  if (!harness) return;
  try {
    const state = await harness.state();
    expect(
      state.submissions,
      "workspace actions must never execute generation",
    ).toEqual([]);
    expect(
      state.ledger.filter((entry: any) => entry.event === "debit"),
    ).toEqual([]);
    expect(state.balance).toBeGreaterThanOrEqual(500);
    expect(harness.blocked, "browser must not contact cloud origins").toEqual(
      [],
    );
    expect(harness.errors, "uncaught Chromium errors").toEqual([]);
  } finally {
    await harness.close();
    harness = undefined;
  }
});

it('Chromium: settings events change recent gallery page sizes, not complete-library paging or workspace previews', async () => {
  const {page} = await mount({tab:'Concepts'});
  const change = async (settings: Record<string,unknown>) => {
    await page.evaluate(async settings => {
      await fetch('/__test/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)});
      (window as any).emitEvent('plugin.hermes-studiotwin.settings.changed');
    },settings);
  };
  await page.waitForFunction(()=>(window as any).requests.some((r:any)=>r.path==='/concepts?limit=24&offset=0'));
  await change({gallery_limit:1,inline_cards:false,auto_rotate:false,webgl_limit:1});
  await page.waitForFunction(()=>(window as any).requests.some((r:any)=>r.path==='/concepts?limit=1&offset=0'));
  await page.getByRole('tab',{name:'Jobs',exact:true}).click();
  await page.waitForFunction(()=>(window as any).requests.some((r:any)=>r.path==='/jobs?limit=1&offset=0'));
  await page.getByRole('button',{name:'Next jobs',exact:true}).click();
  await browserExpect(page.getByText('Offset 1',{exact:true})).toBeVisible();
  await change({gallery_limit:3});
  await page.waitForFunction(()=>(window as any).requests.some((r:any)=>r.path==='/jobs?limit=3&offset=0'));
  await browserExpect(page.getByText('Offset 0',{exact:true})).toBeVisible();
  await page.getByRole('tab',{name:'Concepts',exact:true}).click();
  await page.waitForFunction(()=>(window as any).requests.some((r:any)=>r.path==='/concepts?limit=3&offset=0'));
  await page.getByRole('tab',{name:'Library',exact:true}).click();
  await page.waitForFunction(()=>(window as any).requests.some((r:any)=>r.path.startsWith('/assets?') && r.path.includes('limit=100')));
  await page.getByRole('button',{name:'crate.glb',exact:true}).click();
  await page.getByRole('button',{name:'Click to load 3D',exact:true}).click();
  const spin = page.getByRole('button',{name:'Auto-rotate',exact:true});
  await browserExpect(spin).toHaveAttribute('aria-pressed','false');
  await change({auto_rotate:true});
  await browserExpect(spin).toHaveAttribute('aria-pressed','true');
  await spin.click();
  await change({auto_rotate:false});
  await change({auto_rotate:true});
  await browserExpect(spin).toHaveAttribute('aria-pressed','false');
},60000);

it("Chromium loopback backend: real router/MCP/storage, image decoding, local/cloud upload and pre-network validation", async () => {
  harness = await openWorkspace({ backendOnly: true });
  const { page } = harness;
  const results = await page.evaluate(async () => {
    const base = "/api/plugins/hermes-studiotwin";
    const status = await fetch(base + "/status").then((r) => r.json());
    const assets = await fetch(base + "/assets").then((r) => r.json());
    const imageId = assets.assets.find(
      (a: any) => a.name === "hero-reference.png",
    ).uuid;
    const media = await fetch(base + "/file?asset=" + imageId).then((r) =>
      r.json(),
    );
    const image = new Image();
    image.src = media.dataUrl;
    await image.decode();
    document.body.append(image);
    const local = await fetch(base + "/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: "reference.png",
        data: media.dataUrl.split(",")[1],
      }),
    }).then((r) => r.json());
    const before = await fetch("/__test/state").then((r) => r.json());
    const rejected = await fetch(base + "/upload?cloud=true", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: "../../bad.png", data: "YQ==" }),
    });
    const after = await fetch("/__test/state").then((r) => r.json());
    const cloud = await fetch(base + "/upload?cloud=true", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: "cloud.png",
        data: media.dataUrl.split(",")[1],
      }),
    }).then((r) => r.json());
    return {
      status,
      width: image.naturalWidth,
      height: image.naturalHeight,
      local,
      localUploads: before.upload_count,
      rejected: rejected.status,
      callsBefore: before.calls.length,
      callsAfter: after.calls.length,
      cloud,
    };
  });
  expect(results.status.configured).toBe(true);
  expect(results.status.balance).toBe(500);
  expect([results.width, results.height]).toEqual([64, 64]);
  expect(results.local.path).toContain("reference.png");
  expect(results.localUploads).toBe(0);
  expect(results.rejected).toBe(400);
  expect(results.callsAfter).toBe(results.callsBefore);
  expect(results.cloud.assets[0].uuid).toBeTruthy();
  expect(JSON.stringify(results.cloud)).not.toMatch(
    /Policy|X-Amz-Signature|STCANARY/,
  );
  const state = await harness.state();
  expect(state.upload_count).toBe(1);
  expect(
    state.storage_requests
      .filter((r: any) => r.path.startsWith("/storage"))
      .every((r: any) => !r.has_api_key),
  ).toBe(true);
}, 60000);

it("Chromium: registers the route, sidebar, six palette commands, and live credits/active-job chrome", async () => {
  const { page } = await mount();
  const rows = await page.evaluate(() =>
    (window as any).registrations.map((r: any) => ({
      id: r.id,
      area: r.area,
      data: { path: r.data?.path, label: r.data?.label },
      render: typeof (r.render || r.data?.render),
    })),
  );
  expect(
    rows.filter((r: any) => r.area === "routes").map((r: any) => r.data.path),
  ).toEqual(["/studiotwin"]);
  expect(
    rows
      .filter((r: any) => r.area === "sidebar.nav")
      .map((r: any) => r.data.path),
  ).toEqual(["/studiotwin"]);
  expect(rows.filter((r: any) => r.area === "palette")).toHaveLength(6);
  expect(rows.filter((r: any) => r.area === "statusBar.right")).toHaveLength(2);
  await browserExpect(
    page.getByRole("button", { name: "StudioTwin 500 credits", exact: true }),
  ).toBeVisible();
  await browserExpect(
    page.getByRole("button", { name: "1 active StudioTwin jobs", exact: true }),
  ).toBeVisible();
  for (const tab of ["Library", "Jobs", "Concepts", "Upload"])
    await browserExpect(
      page.getByRole("tab", { name: tab, exact: true }),
    ).toBeVisible();
}, 60000);

it("Chromium: real library filters/search, model inspector, backend lineage and quoted Next actions address origin chat", async () => {
  const h = await mount(),
    { page } = h;
  for (const filter of [
    "All",
    "3D & Rigged",
    "Audio SFX",
    "360° Env",
    "PBR Material",
    "Image & Concept",
    "Video",
  ])
    await browserExpect(
      page.getByRole("button", { name: filter, exact: true }),
    ).toBeVisible();
  await page.getByRole("button", { name: "Audio SFX", exact: true }).click();
  await browserExpect(
    page.getByRole("button", { name: "wind.wav", exact: true }),
  ).toBeVisible();
  await browserExpect(
    page.getByRole("button", { name: "crate.glb", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "All", exact: true }).click();
  await page.getByLabel("Search assets").fill("crate");
  await page.getByRole("button", { name: "crate.glb", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Asset inspection" });
  await browserExpect(dialog).toBeVisible();
  await dialog
    .getByRole("button", { name: "Click to load 3D", exact: true })
    .click();
  await browserExpect(dialog.locator("canvas")).toBeVisible();
  await browserExpect(dialog.locator("[data-model-stats]")).toContainText(
    "triangles",
  );
  const state = await h.state();
  await browserExpect(
    dialog.getByRole("button", { name: new RegExp(state.parent) }),
  ).toBeVisible();
  const actions = await fetch(
    h.url +
      `/api/plugins/hermes-studiotwin/actions?id=${state.mesh}&type=3d_model`,
  ).then((r) => r.json());
  expect(actions.actions.length).toBeGreaterThan(0);
  const action = actions.actions[0];
  const button = dialog.getByRole("button", { name: new RegExp(action.label) });
  await browserExpect(button).toContainText(action.cost_label);
  await page.evaluate(() =>
    (window as any).switchScope("activeSessionId", "different-chat"),
  );
  await button.click();
  expect(await page.evaluate(() => (window as any).messages)).toEqual([
    { session: "origin-chat", text: action.message },
  ]);
  await dialog.getByRole("button", { name: new RegExp(state.parent) }).click();
  await browserExpect(dialog.getByAltText("StudioTwin image")).toBeVisible();
  await page
    .getByRole("button", { name: "Close asset inspection", exact: true })
    .click();
  await browserExpect(dialog).toHaveCount(0);
}, 60000);

it("Chromium: complete merged library beyond 100 rows supports late modality, search and inspection", async () => {
  const { page, url } = await mount({ largeLibrary: true });
  const all = page.getByRole("region", { name: "Asset Library" });
  await browserExpect(all.locator("article")).toHaveCount(209);
  await page.getByRole("button", { name: "Video", exact: true }).click();
  await page.getByRole("button", { name: "late-video.mp4", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Asset inspection" });
  await browserExpect(dialog.locator("video")).toBeVisible();
  await page.waitForFunction(() => document.querySelector("video")!.readyState >= 2);
  await dialog.getByRole("button", { name: "Close asset inspection", exact: true }).click();
  await page.getByRole("button", { name: "Image & Concept", exact: true }).click();
  await page.getByLabel("Search assets").fill("late-local");
  await browserExpect(all.locator("article")).toHaveCount(1);
  await page.getByRole("button", { name: "late-local.png", exact: true }).click();
  await browserExpect(dialog.getByAltText("StudioTwin image")).toBeVisible();
  await dialog.getByRole("button", { name: "Close asset inspection", exact: true }).click();
  await page.getByLabel("Search assets").fill("cached-cloud");
  await browserExpect(all.locator("article")).toHaveCount(1);
  await page.getByRole("button", { name: "cached-cloud.png", exact: true }).click();
  await browserExpect(dialog.getByAltText("StudioTwin image")).toBeVisible();
  await dialog.getByRole("button", { name: "Close asset inspection", exact: true }).click();
  await page.getByLabel("Search assets").fill("");
  await page.getByRole("button", { name: "All", exact: true }).click();
  await browserExpect(all.locator("article")).toHaveCount(209);
  const state = await harness!.state();
  const lists = state.calls.filter((c: any) => c.name === "studiotwin_list_my_assets");
  expect(lists.length).toBeGreaterThanOrEqual(3);
  // Paging is plugin-owned, never invented as provider tool arguments.
  expect(lists.every((c: any) => Object.keys(c.arguments ?? c.args ?? {}).length === 0)).toBe(true);
  const pages = await Promise.all([0, 100, 200, 300].map(offset =>
    fetch(url + `/api/plugins/hermes-studiotwin/assets?limit=100&offset=${offset}`).then(r => r.json())));
  expect(pages.map(p => p.assets.length)).toEqual([100, 100, 9, 0]);
  expect(pages.map(p => p.next_offset)).toEqual([100, 200, null, null]);
  expect(pages.every(p => p.total === 209)).toBe(true);
  expect(new Set(pages.flatMap(p => p.assets.map((a: any) => a.uuid ?? a.path))).size).toBe(209);
}, 60000);

it("Chromium: a failed later library page reports an error, not missing assets, and refresh retries all pages", async () => {
  const { page } = await mount({ tab: "Jobs", largeLibrary: true });
  await page.route("**/api/plugins/hermes-studiotwin/assets?limit=100&offset=100", route => route.abort("failed"));
  await page.getByRole("tab", { name: "Library", exact: true }).click();
  await page.getByRole("button", { name: "Video", exact: true }).click();
  await browserExpect(page.getByRole("alert")).toContainText("Asset library unavailable");
  await browserExpect(page.getByText(/No matching assets/)).toHaveCount(0);
  await page.unroute("**/api/plugins/hermes-studiotwin/assets?limit=100&offset=100");
  await page.getByRole("button", { name: "Refresh library", exact: true }).click();
  await browserExpect(page.getByRole("button", { name: "late-video.mp4", exact: true })).toBeVisible();
  await browserExpect(page.getByRole("alert")).toHaveCount(0);
}, 60000);

it("Chromium: real job filters, queued-only cancellation and Inspect Output opens the real image viewer", async () => {
  const { page, state } = await mount({ tab: "Jobs" });
  for (const filter of ["All", "Active", "Completed", "Failed", "Cancelled"])
    await browserExpect(
      page.getByRole("button", { name: filter, exact: true }),
    ).toBeVisible();
  await page.getByRole("button", { name: "Active", exact: true }).click();
  await page
    .getByRole("button", { name: "Cancel queued job", exact: true })
    .click();
  await browserExpect(
    page.getByRole("button", { name: "Cancel queued job", exact: true }),
  ).toHaveCount(0);
  expect(
    (await state()).calls.some(
      (call: any) => call.name === "studiotwin_cancel_job",
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Completed", exact: true }).click();
  await page
    .getByRole("button", { name: "Inspect Output", exact: true })
    .click();
  await browserExpect(
    page
      .getByRole("dialog", { name: "Asset inspection" })
      .getByAltText("StudioTwin image"),
  ).toBeVisible();
}, 60000);

it("Chromium: Concepts history/active badge and four composer-only workflows use the captured owner", async () => {
  const { page } = await mount({ tab: "Concepts" });
  await page.getByRole("button", { name: "Hero study", exact: true }).click();
  await page.getByRole("button", { name: /Version 1/ }).click();
  await page.getByRole("button", { name: /Version 2/ }).click();
  await browserExpect(
    page.getByRole("slider", { name: "Before / after" }),
  ).toBeVisible();
  await browserExpect(
    page.getByText("Active asset", { exact: true }),
  ).toBeVisible();
  await page.evaluate(() =>
    (window as any).switchScope("activeSessionId", "different-chat"),
  );
  for (const action of [
    "Generate Image",
    "Edit Concept",
    "Convert to 3D Mesh",
    "Convert to 360° Env",
  ])
    await page.getByRole("button", { name: action, exact: true }).click();
  const messages = await page.evaluate(() => (window as any).messages);
  expect(messages).toHaveLength(4);
  expect(messages.every((m: any) => m.session === "origin-chat")).toBe(true);
  expect(messages.every((m: any) => /credit/i.test(m.text))).toBe(true);
}, 60000);

it("Chromium: local selection and explicit cloud drop upload go through the real router without leaking presigned POST fields", async () => {
  const h = await mount({ tab: "Upload" }),
    { page } = h;
  const bytes = readFileSync("tests/fixtures/media/image/concept-64.png");
  await browserExpect(
    page.getByRole("checkbox", { name: "Cloud upload" }),
  ).not.toBeChecked();
  await page.getByLabel("Reference file", { exact: true }).setInputFiles({
    name: "local-reference.png",
    mimeType: "image/png",
    buffer: bytes,
  });
  await page.getByRole("button", { name: "Use in Chat", exact: true }).click();
  expect((await h.state()).upload_count).toBe(0);
  let messages = await page.evaluate(() => (window as any).messages);
  expect(messages).toHaveLength(1);
  expect(messages[0].session).toBe("origin-chat");
  expect(messages[0].text).toContain("local-reference.png");
  await page.getByRole("checkbox", { name: "Cloud upload" }).check();
  const transfer = await page.evaluateHandle(
    (data) => {
      const dt = new DataTransfer();
      dt.items.add(
        new File([new Uint8Array(data)], "cloud-reference.png", {
          type: "image/png",
        }),
      );
      return dt;
    },
    [...bytes],
  );
  await page
    .getByLabel("Drop reference asset", { exact: true })
    .dispatchEvent("drop", { dataTransfer: transfer });
  await browserExpect.poll(async () => (await h.state()).upload_count).toBe(1);
  await page.getByRole("button", { name: "Use in Chat", exact: true }).click();
  messages = await page.evaluate(() => (window as any).messages);
  expect(messages).toHaveLength(2);
  const uuid = await page.locator("main code").innerText();
  expect(uuid).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
  );
  expect(messages[1].text).toBe(
    `Use uploaded asset ${uuid} (cloud-reference.png) to ...`,
  );
  expect(JSON.stringify(messages)).not.toMatch(
    /X-Amz-Signature|STCANARY|Policy/,
  );
  const state = await h.state();
  expect(
    state.storage_requests
      .filter((r: any) => r.path.startsWith("/storage"))
      .every((r: any) => !r.has_api_key),
  ).toBe(true);
}, 60000);

it("Chromium: cached PBR, cloud HDR, rigged animation, audio and video open their real rich viewers", async () => {
  const { page } = await mount();
  for (const entry of [
    {
      filter: "PBR Material",
      name: "pbr-albedo.png",
      load: "Load material",
      selector: "[data-studiotwin-material-viewer] canvas",
    },
    {
      filter: "360° Env",
      name: "studio.hdr",
      load: "Load environment",
      selector: "[data-studiotwin-env-viewer] canvas",
    },
    {
      filter: "3D & Rigged",
      name: "walker.glb",
      load: "Click to load 3D",
      selector: "[data-studiotwin-model-viewer] canvas",
    },
    { filter: "Audio SFX", name: "wind.wav", selector: "canvas" },
    { filter: "Video", name: "turntable.mp4", selector: "video" },
  ]) {
    await page.getByRole("button", { name: entry.filter, exact: true }).click();
    await page.getByRole("button", { name: entry.name, exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Asset inspection" });
    if (entry.load)
      await dialog
        .getByRole("button", { name: entry.load, exact: true })
        .click();
    await browserExpect(dialog.locator(entry.selector)).toBeVisible();
    if (entry.name === "walker.glb")
      await browserExpect(
        dialog.getByRole("slider", { name: "Animation position" }),
      ).toBeVisible();
    if (entry.name === "turntable.mp4")
      await page.waitForFunction(
        () => document.querySelector("video")!.readyState >= 2,
      );
    await dialog
      .getByRole("button", { name: "Close asset inspection", exact: true })
      .click();
  }
}, 60000);

it("Chromium: every palette command and chip opens the requested registered workspace tab; settings toggle is live", async () => {
  const { page, url } = await mount();
  const expected = ["Library", "Library", "Jobs", "Concepts", "Upload"];
  for (let index = 0; index < 5; index++) {
    await page.evaluate((i) => (window as any).runPalette(i), index);
    await browserExpect(
      page.getByRole("tab", { name: expected[index], exact: true }),
    ).toHaveAttribute("aria-selected", "true");
  }
  await page.evaluate(() => (window as any).runPalette(5));
  expect(await page.evaluate(() => (window as any).settings)).toEqual([
    "hermes-studiotwin",
  ]);
  await page
    .getByRole("button", { name: "1 active StudioTwin jobs", exact: true })
    .click();
  await browserExpect(
    page.getByRole("tab", { name: "Jobs", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page
    .getByRole("button", { name: "StudioTwin 500 credits", exact: true })
    .click();
  await browserExpect(
    page.getByRole("tab", { name: "Library", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await fetch(url + "/__test/credits/false", { method: "POST" });
  await page.evaluate(() =>
    (window as any).emitEvent("plugin.hermes-studiotwin.settings.changed"),
  );
  await browserExpect(
    page.getByRole("button", { name: "StudioTwin 500 credits", exact: true }),
  ).toHaveCount(0);
  await browserExpect(
    page.getByRole("button", { name: "1 active StudioTwin jobs", exact: true }),
  ).toBeVisible();
  await fetch(url + "/__test/credits/true", { method: "POST" });
  await page.evaluate(() =>
    (window as any).emitEvent("plugin.hermes-studiotwin.settings.changed"),
  );
  await browserExpect(
    page.getByRole("button", { name: "StudioTwin 500 credits", exact: true }),
  ).toBeVisible();
  await page.evaluate(() => (window as any).switchScope("profile", "beta"));
  await browserExpect(
    page.getByText(/Profile or connection changed/),
  ).toBeVisible();
  await page.evaluate(() => (window as any).runPalette(0));
  await browserExpect(
    page.getByRole("button", { name: "hero-reference.png", exact: true }),
  ).toBeVisible();
}, 60000);

it("Chromium: all four tabs inherit light/dark theme variables, with no hardcoded color styles", async () => {
  const { page } = await mount();
  for (const light of [false, true]) {
    await page.evaluate((light) => {
      const root = document.documentElement.style;
      root.setProperty("--ui-bg-card", light ? "white" : "black");
      root.setProperty("--ui-bg", light ? "white" : "black");
      root.setProperty("--ui-text-secondary", light ? "dimgray" : "silver");
      document.body.style.background = "var(--ui-bg)";
      root.setProperty("--ui-text-primary", light ? "black" : "white");
    }, light);
    for (const tab of ["Library", "Jobs", "Concepts", "Upload"]) {
      await page.getByRole("tab", { name: tab, exact: true }).click();
      const styles = await page
        .locator("main [style], #chips [style]")
        .evaluateAll((nodes) =>
          nodes.map((n) => n.getAttribute("style") ?? ""),
        );
      expect(styles.join("\n")).not.toMatch(/#[\da-f]{3,8}\b|rgba?\(/i);
      expect(styles.join("\n")).toContain("var(--ui-");
      await browserExpect(page.getByRole("tabpanel")).toBeVisible();
      if (process.env.V06_SCREENSHOT_DIR) {
        mkdirSync(process.env.V06_SCREENSHOT_DIR, { recursive: true });
        await page.screenshot({
          path:
            process.env.V06_SCREENSHOT_DIR +
            "/" +
            tab +
            "-" +
            (light ? "light" : "dark") +
            ".png",
          fullPage: true,
        });
      }
    }
  }
}, 60000);

it.each(["profile", "connectionId"])(
  "Chromium: %s switch permanently revokes captured workspace actions",
  async (kind) => {
    const { page } = await mount();
    await page
      .getByRole("button", { name: "hero-reference.png", exact: true })
      .click();
    const dialog = page.getByRole("dialog", { name: "Asset inspection" });
    await browserExpect(dialog.getByAltText("StudioTwin image")).toBeVisible();
    const initial = await page.evaluate(() => (window as any).requests.length);
    await page.evaluate(
      (kind) => (window as any).switchScope(kind, "other"),
      kind,
    );
    await browserExpect(dialog).toHaveCount(0);
    await page.evaluate(
      (kind) =>
        (window as any).switchScope(kind, kind === "profile" ? "alpha" : null),
      kind,
    );
    await page.waitForTimeout(350);
    await browserExpect(dialog).toHaveCount(0);
    expect(await page.evaluate(() => (window as any).messages)).toEqual([]);
    expect(
      await page.evaluate(
        (start) =>
          (window as any).requests
            .slice(start)
            .filter((r: any) => r.method !== "GET"),
        initial,
      ),
    ).toEqual([]);
  },
  60000,
);

it.each(["profile", "connectionId"])(
  "Chromium: pending upload cannot expose Use in Chat after %s changes away and back",
  async (kind) => {
    const { page } = await mount({ tab: "Upload" });
    let release!: () => void, received!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const started = new Promise<void>((resolve) => {
      received = resolve;
    });
    // Hold an actual backend response, not fabricated upload data.
    await page.route(
      "**/api/plugins/hermes-studiotwin/upload**",
      async (route) => {
        const response = await route.fetch();
        received();
        await held;
        await route.fulfill({ response });
      },
    );
    try {
      await page.getByLabel("Reference file", { exact: true }).setInputFiles({
        name: "pending-reference.png",
        mimeType: "image/png",
        buffer: readFileSync("tests/fixtures/media/image/concept-64.png"),
      });
      await Promise.race([
        started,
        new Promise((_, reject) =>
          setTimeout(
            () => reject(Error("No upload request reached real backend")),
            10000,
          ),
        ),
      ]);
      await page.evaluate(
        (kind) => (window as any).switchScope(kind, "other"),
        kind,
      );
      release();
      await page.evaluate(
        (kind) =>
          (window as any).switchScope(
            kind,
            kind === "profile" ? "alpha" : null,
          ),
        kind,
      );
      await page.waitForTimeout(250);
      await browserExpect(
        page.getByRole("button", { name: "Use in Chat", exact: true }),
      ).toHaveCount(0);
      expect(await page.evaluate(() => (window as any).messages)).toEqual([]);
    } finally {
      release();
    }
  },
  60000,
);

it.each(["profile", "connectionId"])(
  "Chromium: file-read scope change refuses upload before network dispatch (%s)",
  async (kind) => {
    const { page, state } = await mount({ tab: "Upload" });
    await page.evaluate(() => {
      const read = File.prototype.arrayBuffer;
      File.prototype.arrayBuffer = function () {
        const file = this;
        (window as any).reading = true;
        return new Promise((resolve) => {
          (window as any).releaseRead = () => read.call(file).then(resolve);
        }) as Promise<ArrayBuffer>;
      };
    });
    await page.getByLabel("Reference file", { exact: true }).setInputFiles({
      name: "read-race.png",
      mimeType: "image/png",
      buffer: readFileSync("tests/fixtures/media/image/concept-64.png"),
    });
    await page.waitForFunction(() => (window as any).reading);
    await page.evaluate(
      (kind) => (window as any).switchScope(kind, "other"),
      kind,
    );
    await page.evaluate(() => (window as any).releaseRead());
    await page.waitForTimeout(200);
    expect(
      (await state()).requests.filter((r: any) => r.path.endsWith("/upload")),
    ).toEqual([]);
    await browserExpect(
      page.getByRole("button", { name: "Use in Chat", exact: true }),
    ).toHaveCount(0);
  },
  60000,
);

it.each([true, false])(
  "Chromium: missing key setup opens settings with optional settings door=%s",
  async (settingsDoor) => {
    const { page } = await mount({ configured: false, settingsDoor });
    await page
      .getByRole("button", { name: "pbr-albedo.png", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Load material", exact: true })
      .click();
    await browserExpect(
      page.getByRole("dialog", { name: "Asset inspection" }).locator("canvas"),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Close asset inspection", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Open Plugin Settings", exact: true })
      .click();
    const result = await page.evaluate(() => ({
      settings: (window as any).settings,
      paths: (window as any).navigations,
    }));
    if (settingsDoor) expect(result.settings).toContain("hermes-studiotwin");
    else
      expect(
        result.paths.some((path: string) => path.includes("settings")),
      ).toBe(true);
  },
  60000,
);
