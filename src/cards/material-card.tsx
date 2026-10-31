import * as sdk from "@hermes/plugin-sdk";
import { useState, type ReactNode } from "react";
import { MaterialViewer } from "../viewers/material-viewer.tsx";
import {
  channels,
  type Channel,
  type MaterialMaps,
} from "../viewers/material-stage.ts";
import {
  fetchModel,
  type ModelScopeState,
  type ModelSource,
} from "../viewers/model-source.ts";
import {
  mapZip,
  downloadSource,
  saveBytes,
} from "../viewers/material-download.ts";
import {
  cleanTool,
  useCardScope,
  resultObject,
  sourceValue,
  workflowMessage,
} from "./env-card.tsx";
export const materialTools = [
  "text-to-material",
  "image-to-material",
  "texture-to-material",
];
export const materialTool = (n: string) => materialTools.includes(cleanTool(n));
export const nextMaterialActions = [
  ["Extract PBR Maps from Texture (20 cr)", "texture-to-material"],
  ["Generate Material Variation (estimate in chat)", "image-to-material"],
];
export function parseMaterialMaps(value: unknown): MaterialMaps {
  const doc = resultObject(value),
    maps: MaterialMaps = {};
  for (const c of channels) {
    const v = doc[c];
    if (v !== undefined) {
      const s = sourceValue(v);
      if (!s) throw new Error("Invalid material channel");
      maps[c] = s;
    }
  }
  if (!maps.albedo) throw new Error("Missing albedo map");
  return maps;
}
export interface MaterialCardProps {
  ctx: sdk.PluginContext;
  maps: MaterialMaps;
  zip?: ModelSource;
  sessionId?: string | null;
  fallback?: ReactNode;
  webgl_limit?: number;
  scopeState?: ModelScopeState;
}
export function MaterialCard({
  ctx,
  maps,
  zip,
  sessionId,
  fallback,
  webgl_limit,
  scopeState,
}: MaterialCardProps) {
  const { scope, stale, send } = useCardScope(ctx, scopeState),
    [failed, setFailed] = useState(false);
  if (failed)
    return (
      <>{fallback ?? <span role="alert">Material preview unavailable.</span>}</>
    );
  const download = async (c: Channel | "zip") => {
    if (c !== "zip") {
      if (!maps[c]) throw new Error("Unavailable map");
      await downloadSource(scope.rest, maps[c]!, scope.assert);
      return;
    }
    if (zip) {
      await downloadSource(scope.rest, zip, scope.assert);
      return;
    }
    const files = await Promise.all(
      channels
        .filter((c) => maps[c])
        .map(async (c) => {
          const f = await fetchModel(scope.rest, maps[c]!);
          return {
            name: c + "." + (f.name.split(".").pop() || "png"),
            buffer: f.buffer,
          };
        }),
    );
    scope.assert();
    saveBytes(mapZip(files), "studiotwin-material.zip");
  };
  return (
    <article style={{ color: "var(--ui-text)", padding: 8 }}>
      <strong>StudioTwin PBR Material</strong>{" "}
      <sdk.Button
        disabled={stale}
        onClick={() => void download("zip").catch(() => setFailed(true))}
      >
        Download zip
      </sdk.Button>
      {stale ? (
        <p role="status">
          Reopen this card in its originating profile and connection.
        </p>
      ) : (
        <MaterialViewer
          rest={scope.rest}
          maps={maps}
          zipAvailable
          onDownload={download}
          webgl_limit={webgl_limit}
          fallback={fallback}
          onError={() => setFailed(true)}
        />
      )}
      <details>
        <summary>Next · review and approve in chat</summary>
        {nextMaterialActions.map(([label, tool]) => (
          <sdk.Button
            key={tool}
            disabled={stale}
            onClick={() => send(sessionId, workflowMessage(maps, tool))}
          >
            {label}
          </sdk.Button>
        ))}
      </details>
    </article>
  );
}
export function registerMaterialCards(
  ctx: sdk.PluginContext,
  options: { webgl_limit?: number } = {},
) {
  const disposers: (() => void)[] = [];
  if (typeof sdk.TOOL_MEDIA_RENDERER_AREA === "string")
    disposers.push(
      ctx.register({
        id: "studiotwin-material-media",
        area: sdk.TOOL_MEDIA_RENDERER_AREA,
        data: {
          tools: [
            ...materialTools,
            ...materialTools.map((n) => "mcp__studiotwin__" + n),
          ],
          render: (p: sdk.ToolMediaRendererProps) => {
            if (!materialTool(p.toolName)) return p.fallback;
            try {
              const r = resultObject(p.result);
              const maps = parseMaterialMaps(r.maps ?? r);
              return (
                <MaterialCard
                  ctx={ctx}
                  maps={maps}
                  zip={sourceValue(r.zip)}
                  fallback={p.fallback}
                  sessionId={p.sessionId}
                  {...options}
                />
              );
            } catch {
              return p.fallback;
            }
          },
        },
      }),
    );
  disposers.push(
    ctx.register({
      id: "studiotwin-material-directive",
      area: sdk.TRANSCRIPT_DIRECTIVE_AREA ?? 'transcript.directives',
      data: {
        name: "studiotwin-material",
        render: (p: sdk.TranscriptDirectiveProps) => {
          try {
            if (p.streaming) return null;
            return (
              <MaterialCard
                ctx={ctx}
                maps={parseMaterialMaps(JSON.parse(p.attrs.maps))}
                sessionId={p.sessionId}
                {...options}
              />
            );
          } catch {
            return null;
          }
        },
      },
    }),
  );
  return () => disposers.forEach((d) => d());
}
