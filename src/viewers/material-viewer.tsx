import { useEffect, useState, type ReactNode } from "react";
import type { PluginContext } from "@hermes/plugin-sdk";
import {
  createMaterialStage,
  channels,
  type Channel,
  type Geometry,
  type MaterialMaps,
} from "./material-stage.ts";
import { usePooledStage, panelStyle, controlStyle } from "./env-lifecycle.ts";
export interface MaterialViewerProps {
  rest: PluginContext["rest"];
  maps: MaterialMaps;
  height?: number;
  webgl_limit?: number;
  fallback?: ReactNode;
  onError?: (e: unknown) => void;
  onDownload?: (channel: Channel | "zip") => Promise<void>;
  zipAvailable?: boolean;
}
export function MaterialViewer({
  rest,
  maps,
  height = 320,
  webgl_limit = 4,
  fallback,
  onError,
  onDownload,
  zipAvailable,
}: MaterialViewerProps) {
  const [channel, setChannel] = useState<Channel | "Combined PBR">(
      "Combined PBR",
    ),
    [geometry, setGeometry] = useState<Geometry>("Sphere"),
    [repeat, setRepeat] = useState(1),
    [scale, setScale] = useState(0),
    [rotation, setRotation] = useState(0),
    [swatch, setSwatch] = useState(false);
  const v = usePooledStage(
    JSON.stringify(maps),
    createMaterialStage,
    (s) => s.load(rest, maps),
    rest,
    webgl_limit,
    onError,
  );
  useEffect(() => {
    v.stage.current?.settings(
      channel,
      geometry,
      repeat,
      scale,
      rotation,
      swatch,
    );
  }, [channel, geometry, repeat, scale, rotation, swatch, v.ready]);
  if (v.error && fallback !== undefined) return <>{fallback}</>;
  return (
    <section
      ref={v.setContainer}
      data-studiotwin-material-viewer
      style={panelStyle}
      onPointerDown={v.touch}
    >
      <div style={{ height, position: "relative" }}>
        <div ref={v.host} style={{ position: "absolute", inset: 0 }} />
        {!v.live && (
          <button
            style={{
              ...controlStyle,
              position: "absolute",
              inset: 0,
              width: "100%",
            }}
            onClick={v.start}
          >
            {v.poster && (
              <img
                alt="Material poster"
                src={v.poster}
                style={{ width: "100%", height: "80%", objectFit: "contain" }}
              />
            )}
            {v.error ? "Preview failed. Retry material" : "Load material"}
          </button>
        )}
        {v.live && !v.ready && <span role="status">Loading material…</span>}
      </div>
      {v.ready && (
        <div
          role="toolbar"
          aria-label="Material controls"
          style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: 8 }}
        >
          <label>
            Channel{" "}
            <select
              style={controlStyle}
              aria-label="Map channel"
              value={channel}
              onChange={(e) => setChannel(e.target.value as typeof channel)}
            >
              <option>Combined PBR</option>
              {channels.map((c) => (
                <option key={c} disabled={!maps[c]} value={c}>
                  {c}
                  {!maps[c] ? " (unavailable)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label>
            Geometry{" "}
            <select
              style={controlStyle}
              aria-label="Geometry"
              value={geometry}
              onChange={(e) => setGeometry(e.target.value as Geometry)}
            >
              {["Sphere", "Cube", "Rounded Plane"].map((g) => (
                <option key={g}>{g}</option>
              ))}
            </select>
          </label>
          <label>
            UV tiling{" "}
            <select
              style={controlStyle}
              aria-label="UV tiling"
              value={repeat}
              onChange={(e) => setRepeat(+e.target.value)}
            >
              {[1, 2, 4].map((n) => (
                <option key={n} value={n}>
                  {n}x
                </option>
              ))}
            </select>
          </label>
          <label>
            Displacement{" "}
            <input
              aria-label="Displacement scale"
              type="range"
              min="0"
              max=".3"
              step=".01"
              disabled={!maps.heightmap}
              value={scale}
              onChange={(e) => setScale(+e.target.value)}
            />
          </label>
          <label>
            Light rig{" "}
            <input
              aria-label="Light rig rotation"
              type="range"
              min="0"
              max="360"
              value={rotation}
              onChange={(e) => setRotation(+e.target.value)}
            />
          </label>
          <button
            style={controlStyle}
            aria-pressed={swatch}
            onClick={() => setSwatch(!swatch)}
          >
            2D tiled swatch
          </button>
          {onDownload && (
            <select
              style={controlStyle}
              aria-label="Download maps"
              defaultValue=""
              onChange={(e) => {
                if (e.target.value)
                  void onDownload(e.target.value as Channel | "zip").catch(
                    onError,
                  );
                e.target.value = "";
              }}
            >
              <option value="">Download…</option>
              {channels.map((c) => (
                <option key={c} disabled={!maps[c]} value={c}>
                  {c}
                </option>
              ))}
              <option value="zip" disabled={!zipAvailable}>
                zip bundle
              </option>
            </select>
          )}
        </div>
      )}
    </section>
  );
}
