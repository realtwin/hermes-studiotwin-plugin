import { secondaryButtonStyle } from '../lib/ui-tokens.ts';
import * as sdk from "@hermes/plugin-sdk";
import { cardShell, cardHeader, cardTitle, creditBadgeStyle, nextDrawerStyle, nextSummaryStyle, nextActionChipStyle } from '../lib/ui-tokens';
import { studiotwinToolAliases } from './tool-names.ts';
import { costLabel } from './action-costs.ts';
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
  [`Extract PBR Maps from Texture (${costLabel('texture-to-material')})`, "texture-to-material"],
  [`Generate Material Variation (${costLabel('image-to-material')})`, "image-to-material"],
] as const;
const materialAliases: Partial<Record<Channel, string>> = {
  normal: "normals", metalness: "metallic", heightmap: "height",
};
function materialSource(value: unknown): ModelSource | undefined {
  if (typeof value === "string") {
    if (!value.trim()) return;
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
      ? { asset: value } : { path: value };
  }
  return sourceValue(value);
}
function materialTitle(doc: Record<string, unknown>): string | undefined {
  for (const value of [doc.title, doc.name])
    if (typeof value === "string" && value.trim()) return value;
}
export function parseMaterialMaps(value: unknown): MaterialMaps {
  let doc: Record<string, unknown>;
  if (value instanceof URLSearchParams) {
    doc = Object.fromEntries(value);
  } else if (typeof value === "string") {
    const text = value.trim();
    try {
      return parseMaterialMaps(JSON.parse(text));
    } catch {
      // Brace-free maps keep URLs intact: split only before another key.
      if (!text || /[{}]/.test(text)) throw new Error("Invalid material maps");
      // Query strings encode URL punctuation; raw URLs must not be decoded or
      // split at their own signed query parameters.
      const query = /^[a-z][\w-]*=[^?=&,]*%[0-9a-f]{2}/i.test(text) ||
        /&(?:albedo|normal|normals|roughness|metalness|metallic|heightmap|height)=/.test(text);
      if (query && !/,\s*[a-z][\w-]*\s*[:=]/i.test(text)) {
        doc = Object.fromEntries(new URLSearchParams(text));
      } else {
        doc = {};
        for (const entry of text.split(/,\s*(?=[a-z][\w-]*\s*[:=])/i)) {
          const match = /^\s*([a-z][\w-]*)\s*[:=]\s*(.*?)\s*$/i.exec(entry);
          if (!match) throw new Error("Invalid material maps");
          doc[match[1]] = match[2];
        }
      }
    }
  } else {
    doc = resultObject(value);
  }
  const maps: MaterialMaps = {};
  for (const c of channels) {
    const alias = materialAliases[c];
    // A defined canonical value wins, including invalid values.
    const v = doc[c] !== undefined ? doc[c] : alias ? doc[alias] : undefined;
    if (v !== undefined) {
      const s = materialSource(v);
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
  title?: string;
  zip?: ModelSource;
  sessionId?: string | null;
  fallback?: ReactNode;
  webgl_limit?: number;
  scopeState?: ModelScopeState;
}
export function MaterialCard({
  ctx,
  maps,
  title,
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
    <article style={{ ...cardShell, color: 'var(--ui-text)' }}>
      <header style={cardHeader}>
      {sdk.Codicon && <sdk.Codicon name="paintcan" size={16} />}
      <strong style={cardTitle}>{title || "StudioTwin PBR Material"}</strong>{" "}
      <span style={creditBadgeStyle}>PBR Material</span>
      <sdk.Button variant="outline" size="sm" style={secondaryButtonStyle}
        disabled={stale}
        onClick={() => void download("zip").catch(() => setFailed(true))}
      >
        Download zip
      </sdk.Button>
      </header>
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
      <details style={nextDrawerStyle}>
        <summary style={nextSummaryStyle}>Next · review and approve in chat</summary>
        {nextMaterialActions.map(([label, tool]) => (
          <sdk.Button variant="outline" size="sm"
            key={tool}
            style={nextActionChipStyle}
            disabled={stale}
            onClick={() => send(sessionId, workflowMessage(maps, tool))}
          >
            <span>{label}</span><span aria-hidden="true" style={creditBadgeStyle}>{costLabel(tool)}</span>
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
          tools: studiotwinToolAliases(materialTools),
          render: (p: sdk.ToolMediaRendererProps) => {
            if (!materialTool(p.toolName) || !(p.file.kind === 'image' || (p.file.kind === 'file' && /\.(json|zip)$/i.test(p.file.name)))) return p.fallback;
            try {
              const r = resultObject(p.result);
              const maps = parseMaterialMaps(r.maps ?? r);
              return (
                <MaterialCard
                  ctx={ctx}
                  maps={maps}
                  zip={materialSource(r.zip)}
                  title={materialTitle(r)}
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
                maps={parseMaterialMaps(p.attrs.maps !== undefined ? p.attrs.maps : p.attrs)}
                title={materialTitle(p.attrs)}
                zip={materialSource(p.attrs.zip)}
                fallback={<p>{p.source}</p>}
                sessionId={p.sessionId}
                {...options}
              />
            );
          } catch {
            return <p>{p.source}</p>;
          }
        },
      },
    }),
  );
  return () => disposers.forEach((d) => d());
}
