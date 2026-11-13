import { useEffect, useState, type ReactNode } from "react";
import type { PluginContext } from "@hermes/plugin-sdk";
import * as sdk from '@hermes/plugin-sdk';
import { fetchModel, type ModelSource } from "./model-source.ts";
import { createEnvStage, parseStickers, type Sticker } from "./env-stage.ts";
import { usePooledStage } from "./env-lifecycle.ts";
import { stageShell, glassToolbar, glassStatsPill, controlStrip, styledRange, posterTile, inspectorToggleStyle as filterPillStyle } from '../lib/ui-tokens';

export interface EnvViewerProps {
  rest: PluginContext["rest"];
  source: ModelSource;
  stickers?: Sticker[];
  height?: number;
  webgl_limit?: number;
  fallback?: ReactNode;
  onError?: (e: unknown) => void;
}
export function EnvViewer({
  rest,
  source,
  stickers = [],
  height = 320,
  webgl_limit = 4,
  fallback,
  onError,
}: EnvViewerProps) {
  const [ev, setEV] = useState(0),
    [spin, setSpin] = useState(false),
    [flat, setFlat] = useState(false),
    [lighting, setLighting] = useState(false),
    [overlay, setOverlay] = useState(true),
    [selected, setSelected] = useState("");
  const v = usePooledStage(
    JSON.stringify([source, stickers]),
    (h) => createEnvStage(h, parseStickers(stickers), setSelected),
    async (s) => {
      const f = await fetchModel(rest, source);
      // source.name is a user-facing label, not the fetched file's format.
      await s.load(f.buffer, f.name);
    },
    rest,
    webgl_limit,
    onError,
  );
  useEffect(() => {
    v.stage.current?.settings(ev, flat, lighting, overlay);
  }, [ev, flat, lighting, overlay, v.ready]);
  useEffect(() => {
    v.stage.current?.autoRotate(spin);
  }, [spin, v.ready]);
  useEffect(() => {
    v.stage.current?.select(selected);
  }, [selected, v.ready]);
  if (v.error && fallback !== undefined) return <section data-stage-state={v.phase}>{fallback}</section>;
  return (
    <section
      ref={v.setContainer}
      data-studiotwin-env-viewer
      data-stage-state={v.phase}
      style={{ ...stageShell, color: 'oklch(from var(--ui-text) l 0 h)' }}
      onPointerDown={v.touch}
    >
      <div style={{ height, position: "relative" }}>
        <div ref={v.host} style={{ position: "absolute", inset: 0 }} />
        {!v.live && (
          <button
            style={{
              ...posterTile,
              position: "absolute",
              inset: 0,
              width: "100%",
            }}
            onClick={v.start}
          >
            {v.poster && (
              <img
                alt="Panorama poster"
                src={v.poster}
                style={{ width: "100%", height: "80%", objectFit: "contain" }}
              />
            )}
            <span style={filterPillStyle(true)}>{Object.hasOwn(sdk, 'Codicon') && <sdk.Codicon name="globe" size={16} />}{v.error ? "Preview failed. Retry environment" : "Load environment"}</span>
          </button>
        )}
        {v.live && !v.ready && <span role="status">Loading environment…</span>}
      </div>
      {v.ready && (
        <div
          role="toolbar"
          aria-label="Environment controls"
          style={glassToolbar}
        >
          <button type="button" style={filterPillStyle(spin)} aria-pressed={spin} onClick={() => setSpin(!spin)}>Auto-rotate</button>
          <button type="button" style={filterPillStyle(false)} onClick={() => { setSpin(false); v.stage.current?.reset(); }}>Reset view</button>
          <label style={controlStrip}>
            Exposure EV{" "}
            <input
              aria-label="Exposure EV"
              style={styledRange}
              type="range"
              min="-5"
              max="5"
              step=".1"
              value={ev}
              onChange={(e) => setEV(+e.target.value)}
            />
            <output style={glassStatsPill}>{ev}</output>
          </label>
          <button
            style={filterPillStyle(flat)}
            aria-pressed={flat}
            onClick={() => setFlat(!flat)}
          >
            Flat 2:1
          </button>
          <button
            style={filterPillStyle(lighting)}
            aria-pressed={lighting}
            onClick={() => setLighting(!lighting)}
          >
            Chrome / matte preview
          </button>
          <button
            style={filterPillStyle(overlay)}
            aria-pressed={overlay}
            onClick={() => setOverlay(!overlay)}
          >
            Sticker overlay
          </button>
          {overlay &&
            stickers.map((s, i) => (
              <button
                key={i}
                style={filterPillStyle(selected === s.assetId)}
                aria-pressed={selected === s.assetId}
                onClick={() => setSelected(s.assetId)}
              >
                <span>Sticker {s.assetId}</span>
                <span aria-hidden="true" style={{ ...glassStatsPill, fontSize: 10 }}>{s.hFovDeg}°</span>
              </button>
            ))}
          {selected && (
            <output style={{ ...glassStatsPill, overflowWrap: "anywhere" }} aria-label="Selected sticker">{selected}</output>
          )}
        </div>
      )}
    </section>
  );
}
