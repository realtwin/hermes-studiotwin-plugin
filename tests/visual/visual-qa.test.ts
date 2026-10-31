// @vitest-environment node
import { expect, it } from "vitest";
import { expect as pw } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { openVisual, upload } from "./bundle-harness";
const evidence = "evidence/v08";

it("real Chromium: production bundle, eight viewers, four tabs, themes and mixed WebGL budget", async () => {
  const h = await openVisual(),
    { page } = h;
  const consoleErrors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  const captures: any[] = [];
  const findings: any[] = [];
  mkdirSync(evidence + "/screenshots", { recursive: true });
  try {
    const fixtures: Record<string, string> = {
      model: "model/static-cube.glb",
      animation: "model/rigged-animated.glb",
      audio: "audio/tone-48k.wav",
      env: "env/equirect-64x32.hdr",
      image: "image/concept-64.png",
      video: "video/testsrc-32.mp4",
    };
    const saved: Record<string, string> = {};
    for (const [kind, path] of Object.entries(fixtures))
      saved[kind] = await upload(h, path);
    const maps: Record<string, { path: string }> = {};
    for (const c of ["albedo", "normal", "roughness", "metalness"])
      maps[c] = { path: await upload(h, "material/pbr-" + c + ".png") };
    const state = await h.state();
    // Real provenance route, not an invented badge in a test wrapper.
    await fetch(h.url + "/api/plugins/hermes-studiotwin/provenance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: state.parent,
        sourceAssetIds: [state.mesh],
        prompt: "Concept comparison reference",
        session_id: "origin-chat",
      }),
    });
    const render = async (kind: string, attrs: any) => {
      await page.evaluate(async () => {
        (window as any).mount(null);
        await new Promise(requestAnimationFrame);
      });
      await page.evaluate(
        ({ kind, attrs }) => (window as any).renderDirective(kind, attrs),
        { kind, attrs },
      );
    };
    const slider = async (label: string, value: string) => {
      const control = page.getByRole("slider", { name: label, exact: true });
      await control.fill(value);
      await pw(control).toHaveValue(value);
    };
    const capture = async (name: string, theme: string) => {
      await page.evaluate(
        () =>
          new Promise<void>((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
          ),
      );
      const layout = await page.evaluate(() => ({
        width: document.documentElement.clientWidth,
        scroll: document.documentElement.scrollWidth,
        bg: getComputedStyle(document.body).backgroundColor,
        fg: getComputedStyle(document.getElementById("root")!).color,
        canvases: [...document.querySelectorAll("canvas")].map((c) => ({
          width: c.width,
          height: c.height,
          cssWidth: c.clientWidth,
          cssHeight: c.clientHeight,
        })),
      }));
      expect(layout.scroll, name + " horizontal overflow").toBeLessThanOrEqual(
        layout.width,
      );
      expect(layout.bg).not.toBe(layout.fg);
      for (const c of layout.canvases) {
        expect(c.width).toBeGreaterThan(0);
        expect(c.cssWidth).toBeGreaterThan(0);
      }
      const file = name + "-" + theme + ".png";
      await page.screenshot({
        path: evidence + "/screenshots/" + file,
        fullPage: true,
        animations: "disabled",
      });
      captures.push({ file, theme, ...layout });
    };
    for (const theme of ["light", "dark"]) {
      await page.addStyleTag({
        content: `:root{--ui-bg:${theme === "light" ? "#f6f7fb" : "#15181e"};--ui-bg-card:${theme === "light" ? "#ffffff" : "#20252e"};--ui-bg-secondary:${theme === "light" ? "#e9edf4" : "#1c222b"};--ui-text:${theme === "light" ? "#172033" : "#e3e9f4"};--ui-text-primary:var(--ui-text);--ui-text-secondary:${theme === "light" ? "#4c5b73" : "#b5c2d8"};--ui-text-tertiary:var(--ui-text-secondary);--ui-text-quaternary:var(--ui-text-secondary);--ui-stroke-secondary:${theme === "light" ? "#a7b3c5" : "#526079"};--ui-accent:${theme === "light" ? "#285dd6" : "#8bb2ff"};color-scheme:${theme}}body{margin:24px;background:var(--ui-bg);color:var(--ui-text);font:14px system-ui}#root{color:var(--ui-text);max-width:1360px;margin:auto}button,input,select,summary{font:inherit;color:var(--ui-text);accent-color:var(--ui-accent)}button,select{background:var(--ui-bg-secondary);border:1px solid var(--ui-stroke-secondary);border-radius:6px;padding:7px 10px;margin:3px}button{cursor:pointer}button:disabled{opacity:.55}summary{padding:8px}#chips,nav[aria-label="Plugin sidebar"],aside{display:flex;gap:8px;flex-wrap:wrap;padding:12px 0}`,
      });
      await render("model", { path: saved.model, name: "static-cube.glb" });
      await page
        .getByRole("button", { name: "Click to load 3D", exact: true })
        .click();
      await pw(page.locator("[data-model-stats]")).toContainText(
        "12 triangles",
      );
      await page
        .getByLabel("Shading mode", { exact: true })
        .selectOption("wireframe");
      await pw(page.getByLabel("Shading mode", { exact: true })).toHaveValue(
        "wireframe",
      );
      await page
        .getByLabel("Shading mode", { exact: true })
        .selectOption("clay");
      await pw(
        page.getByLabel("Download format", { exact: true }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "Auto-rotate", exact: true })
        .click();
      const canvas = page.locator("canvas");
      const box = await canvas.boundingBox();
      expect(box).toBeTruthy();
      await page.mouse.move(box!.x + 100, box!.y + 100);
      await page.mouse.down();
      await page.mouse.move(box!.x + 170, box!.y + 130, { steps: 6 });
      await page.mouse.up();
      await capture("3d-model", theme);
      await render("model", {
        path: saved.animation,
        name: "rigged-animated.glb",
      });
      await page
        .getByRole("button", { name: "Click to load 3D", exact: true })
        .click();
      await pw(
        page.getByLabel("Animation clip", { exact: true }),
      ).toBeVisible();
      expect(
        await page
          .getByLabel("Animation clip", { exact: true })
          .locator("option")
          .allTextContents(),
      ).toEqual(["Wave", "Idle"]);
      await page
        .getByLabel("Animation clip", { exact: true })
        .selectOption({ label: "Wave" });
      await slider("Animation position", "0.5");
      await pw(page.locator("[data-model-stats]")).toContainText(
        "bones/joints",
      );
      if ((await page.getByText(/Rig audit:/).count()) === 0)
        findings.push({
          theme,
          surface: "animation",
          missing:
            "Rig audit badge is not wired through production directive/media registration",
        });
      await capture("animation-rigged", theme);
      await render("audio", { path: saved.audio });
      await pw(page.locator("canvas")).toBeVisible();
      await pw
        .poll(() =>
          page.locator("canvas").evaluate((c: HTMLCanvasElement) => {
            const data = c
              .getContext("2d")!
              .getImageData(0, 0, c.width, c.height).data;
            let n = 0;
            for (let i = 3; i < data.length; i += 4) if (data[i]) n++;
            return n;
          }),
        )
        .toBeGreaterThan(100);
      await page
        .getByRole("button", { name: "Loop audition", exact: true })
        .click();
      await pw(
        page.getByRole("button", { name: "Loop audition", exact: true }),
      ).toHaveAttribute("aria-pressed", "true");
      await page.getByRole("button", { name: "Play", exact: true }).click();
      await pw(
        page.getByRole("button", { name: "Pause", exact: true }),
      ).toBeVisible();
      await page.getByRole("button", { name: "Pause", exact: true }).click();
      await page.getByText("Download / Convert", { exact: true }).click();
      for (const fmt of ["WAV", "MP3", "OGG", "FLAC"])
        await pw(
          page.getByRole("button", { name: "Download " + fmt, exact: true }),
        ).toBeVisible();
      await capture("audio-sfx", theme);
      await render("env", {
        path: saved.env,
        stickers: JSON.stringify([
          {
            assetId: "reference-sticker",
            yawDeg: 0,
            pitchDeg: 0,
            rollDeg: 15,
            hFovDeg: 50,
            sourceAspect: 1.5,
          },
        ]),
      });
      await page
        .getByRole("button", { name: "Load environment", exact: true })
        .click();
      await pw(
        page.getByRole("toolbar", {
          name: "Environment controls",
          exact: true,
        }),
      ).toBeVisible();
      await slider("Exposure EV", "1.2");
      const overlay = page.getByRole("button", {
        name: "Sticker overlay",
        exact: true,
      });
      if ((await overlay.getAttribute("aria-pressed")) === "false")
        await overlay.click();
      await page
        .getByRole("button", { name: "Sticker reference-sticker", exact: true })
        .click();
      await pw(page.getByLabel("Selected sticker", { exact: true })).toHaveText(
        "reference-sticker",
      );
      await capture("env-360-stickers", theme);
      await render("material", { maps: JSON.stringify(maps) });
      await page
        .getByRole("button", { name: "Load material", exact: true })
        .click();
      await pw(
        page.getByRole("toolbar", { name: "Material controls", exact: true }),
      ).toBeVisible();
      for (const geometry of ["Cube", "Rounded Plane", "Sphere"]) {
        await page
          .getByLabel("Geometry", { exact: true })
          .selectOption(geometry);
        await pw(page.getByLabel("Geometry", { exact: true })).toHaveValue(
          geometry,
        );
      }
      for (const c of [
        "albedo",
        "normal",
        "roughness",
        "metalness",
        "Combined PBR",
      ]) {
        await page.getByLabel("Map channel", { exact: true }).selectOption(c);
        await pw(page.getByLabel("Map channel", { exact: true })).toHaveValue(
          c,
        );
      }
      await pw(
        page.getByLabel("Displacement scale", { exact: true }),
      ).toBeDisabled();
      await capture("pbr-material", theme);
      // Use the concept's active image as the before source.
      const concept = await fetch(
        h.url + "/api/plugins/hermes-studiotwin/concepts/" + state.concept,
      ).then((r) => r.json());
      const images = concept.assets ?? concept.concept?.assets;
      const before = images?.at(-1)?.assetId;
      await render("image", {
        asset: state.parent,
        before,
        title: "ConceptLab · Before / after",
      });
      await pw(
        page.getByRole("slider", { name: "Before / after", exact: true }),
      ).toBeVisible();
      await slider("Before / after", "35");
      await pw(page.getByText(/Made from/)).toBeVisible();
      await capture("image-concept-compare", theme);
      await render("video", { path: saved.video });
      await page.waitForFunction(
        () => document.querySelector("video")?.readyState! >= 2,
      );
      await pw(
        page.getByRole("button", { name: "+1f", exact: true }),
      ).toBeEnabled();
      await page.getByRole("button", { name: "+1f", exact: true }).click();
      await pw
        .poll(() =>
          page
            .locator("video")
            .evaluate((v: HTMLVideoElement) => v.currentTime),
        )
        .toBeGreaterThan(0);
      await page.getByRole("button", { name: "-1f", exact: true }).click();
      await pw
        .poll(() =>
          page
            .locator("video")
            .evaluate((v: HTMLVideoElement) => v.currentTime),
        )
        .toBe(0);
      await slider("Timeline", "0.4");
      const download = page.waitForEvent("download");
      await page
        .getByRole("button", { name: "Capture PNG", exact: true })
        .click();
      expect((await download).suggestedFilename()).toMatch(/\.png$/);
      await capture("video-player", theme);
      await fetch(h.url + "/__test/visual-job/queued", { method: "POST" });
      await render("task", { id: state.jobs.queued });
      await pw(page.locator("[data-studiotwin-task]")).toHaveAttribute(
        "data-studiotwin-task",
        "queued",
      );
      await capture("task-progress-queued", theme);
      await fetch(h.url + "/__test/visual-job/running", { method: "POST" });
      await pw(page.locator("[data-studiotwin-task]")).toHaveAttribute(
        "data-studiotwin-task",
        "running",
        { timeout: 10000 },
      );
      await capture("task-progress-running", theme);
      await fetch(h.url + "/__test/visual-job/done", { method: "POST" });
      await pw(page.locator("[data-studiotwin-task]")).toHaveAttribute(
        "data-studiotwin-task",
        "completed",
        { timeout: 10000 },
      );
      await pw(
        page.getByAltText("StudioTwin image", { exact: true }),
      ).toBeVisible();
      await page
        .getByText("Next · review and approve in chat", { exact: true })
        .click();
      await capture("task-progress-card", theme);
      await page.evaluate(() => (window as any).workspace());
      for (const tab of ["Library", "Jobs", "Concepts", "Upload"]) {
        await page.getByRole("tab", { name: tab, exact: true }).click();
        await pw(page.getByRole("tabpanel")).toBeVisible();
        await pw(
          page.getByRole("button", {
            name: "StudioTwin 500 credits",
            exact: true,
          }),
        ).toBeVisible();
        if (tab === "Concepts")
          await page
            .getByRole("button", { name: "Hero study", exact: true })
            .click();
        await capture("workspace-" + tab.toLowerCase(), theme);
      }
      await page.evaluate(() => {
        const w = window as any;
        w.registrations.filter((r: any) => r.area === "palette")[2].data.run();
      });
      await pw(
        page.getByRole("tab", { name: "Jobs", exact: true }),
      ).toHaveAttribute("aria-selected", "true");
      await page
        .getByRole("navigation", { name: "Plugin sidebar" })
        .getByRole("button")
        .click();
      expect(await page.evaluate(() => (window as any).navigations)).toContain(
        "/studiotwin",
      );
      await page.evaluate(async () => {
        (window as any).mount(null);
        await new Promise(requestAnimationFrame);
      });
      await page.evaluate(
        ({ saved, maps }) => {
          const w = window as any,
            R = w.R;
          w.mount(
            R.createElement(
              "div",
              {
                style: {
                  display: "grid",
                  gridTemplateColumns: "repeat(3,minmax(0,1fr))",
                  gap: 12,
                },
              },
              ...["model", "env", "material", "model", "env", "material"].map(
                (kind, i) =>
                  R.createElement(
                    "section",
                    { key: i, "data-pool-slot": i },
                    w.directive(
                      kind,
                      kind === "material"
                        ? { maps: JSON.stringify(maps) }
                        : { path: saved[kind] },
                    ),
                  ),
              ),
            ),
          );
        },
        { saved, maps },
      );
      for (let i = 0; i < 6; i++) {
        const slot = page.locator('[data-pool-slot="' + i + '"]');
        await slot
          .getByRole("button", {
            name: /^(Click to load 3D|Load environment|Load material)$/,
          })
          .click();
        await pw(slot.locator("canvas")).toHaveCount(1);
        await pw(slot.getByRole("toolbar")).toBeVisible();
      }
      await pw(page.locator("canvas")).toHaveCount(4);
      await pw(
        page.locator(
          'img[alt="Model preview"],img[alt="Panorama poster"],img[alt="Material poster"]',
        ),
      ).toHaveCount(2);
      await capture("webgl-pool-six", theme);
    }
    for (const name of new Set(
      captures.map((c) => c.file.replace(/-(light|dark)\.png$/, "")),
    )) {
      const pair = captures.filter((c) => c.file.startsWith(name + "-"));
      expect(pair).toHaveLength(2);
      expect(pair[0].bg).not.toBe(pair[1].bg);
      expect(pair[0].fg).not.toBe(pair[1].fg);
    }
    const final = await h.state();
    expect(final.submissions).toEqual([]);
    expect(final.ledger.filter((r: any) => r.event === "debit")).toEqual([]);
    expect(h.errors).toEqual([]);
    expect(h.blocked).toEqual([]);
    expect(consoleErrors).toEqual([]);
    writeFileSync(
      evidence + "/visual-manifest.json",
      JSON.stringify(
        {
          captures,
          findings,
          errors: h.errors,
          consoleErrors,
          blocked: h.blocked,
          submissions: final.submissions,
        },
        null,
        2,
      ) + "\n",
    );
    expect(
      findings,
      "Required production surfaces must be wired, not fabricated in the harness",
    ).toEqual([]);
  } finally {
    writeFileSync(
      evidence + "/visual-partial.json",
      JSON.stringify(
        { captures, findings, errors: h.errors, consoleErrors },
        null,
        2,
      ) + "\n",
    );
    await h.close();
  }
}, 240000);
