import * as sdk from "@hermes/plugin-sdk";
import { useEffect, useState, type ReactNode } from "react";
import { EnvViewer } from "../viewers/env-viewer.tsx";
import {
  bindModelScope,
  type ModelSource,
  type ModelScopeState,
} from "../viewers/model-source.ts";
import { parseStickers, type Sticker } from "../viewers/env-stage.ts";
import { downloadSource } from "../viewers/material-download.ts";
export const envTools = [
  "text-to-environment-map",
  "image-to-environment-map",
  "environment-map-upscale-cpu",
  "pano-sticker-placement",
  "pano-stickers",
];
export const cleanTool = (n: string) =>
  n
    .replace(/^mcp__studiotwin__/, "")
    .replace(/^mcp_studiotwin_/, "")
    .replace(/^studiotwin_/, "")
    .replace(/_/g, "-");
export const envTool = (n: string) => envTools.includes(cleanTool(n));
export const nextEnvActions = [
  ["Upscale Environment (10 cr)", "environment-map-upscale-cpu"],
  ["Place Pano Stickers (15 cr)", "pano-sticker-placement"],
  ["Composite Pano Stickers (20 cr)", "pano-stickers"],
  ["Generate 3D World (80 cr)", "environment-map-to-world"],
];
export function workflowMessage(source: unknown, tool: string) {
  return `Use ${tool} with StudioTwin source ${JSON.stringify(source)}. Read the live schema, verify compatibility, estimate the exact inputs and ask me to approve credits before submitting. Ask before uploading any local file.`;
}
export function useCardScope(
  ctx: sdk.PluginContext,
  state: ModelScopeState = sdk.host.state ?? {},
) {
  const [scope] = useState(() => bindModelScope(ctx.rest, state));
  const [stale, setStale] = useState(!scope.current());
  useEffect(() => scope.watch(() => setStale(true)), [scope]);
  return {
    scope,
    stale,
    send(sessionId: string | null | undefined, text: string) {
      try {
        scope.assert();
        if (!sessionId || !sdk.host.composer?.submit(sessionId, text))
          sdk.host.notify({
            kind: "warning",
            message: "Open the originating chat to continue.",
          });
      } catch {
        setStale(true);
      }
    },
  };
}
export function resultObject(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    try {
      return resultObject(JSON.parse(value));
    } catch {
      return {};
    }
  }
  if (!value || typeof value !== "object") return {};
  const v = value as Record<string, unknown>;
  if (v.structuredContent) return resultObject(v.structuredContent);
  if (Array.isArray(v.content)) {
    for (const c of v.content) {
      if (c?.type === "text") {
        const o = resultObject(c.text);
        if (Object.keys(o).length) return o;
      }
    }
  }
  return v;
}
export function sourceValue(v: unknown): ModelSource | undefined {
  if (typeof v === "string" && v) return { path: v };
  if (!v || typeof v !== "object") return;
  const s = v as ModelSource;
  if (
    Boolean(s.path) === Boolean(s.asset) ||
    (s.path !== undefined && typeof s.path !== "string") ||
    (s.asset !== undefined && typeof s.asset !== "string")
  )
    return;
  return { path: s.path, asset: s.asset, name: s.name };
}
export interface EnvCardProps {
  ctx: sdk.PluginContext;
  source: ModelSource;
  stickers?: Sticker[];
  sessionId?: string | null;
  fallback?: ReactNode;
  webgl_limit?: number;
  scopeState?: ModelScopeState;
}
export function EnvCard({
  ctx,
  source,
  stickers,
  sessionId,
  fallback,
  webgl_limit,
  scopeState,
}: EnvCardProps) {
  const { scope, stale, send } = useCardScope(ctx, scopeState),
    [failed, setFailed] = useState(false);
  if (failed)
    return (
      <>
        {fallback ?? <span role="alert">Environment preview unavailable.</span>}
      </>
    );
  return (
    <article style={{ color: "var(--ui-text)", padding: 8 }}>
      <strong>StudioTwin Environment</strong>{" "}
      <sdk.Button
        disabled={stale}
        onClick={() =>
          void downloadSource(scope.rest, source, scope.assert).catch(() =>
            setFailed(true),
          )
        }
      >
        Download
      </sdk.Button>
      {stale ? (
        <p role="status">
          Reopen this card in its originating profile and connection.
        </p>
      ) : (
        <EnvViewer
          rest={scope.rest}
          source={source}
          stickers={stickers}
          webgl_limit={webgl_limit}
          fallback={fallback}
          onError={() => setFailed(true)}
        />
      )}
      <details>
        <summary>Next · review and approve in chat</summary>
        {nextEnvActions.map(([label, tool]) => (
          <sdk.Button
            key={tool}
            disabled={stale}
            onClick={() => send(sessionId, workflowMessage(source, tool))}
          >
            {label}
          </sdk.Button>
        ))}
      </details>
    </article>
  );
}
export function registerEnvCards(
  ctx: sdk.PluginContext,
  options: { webgl_limit?: number } = {},
) {
  const disposers: (() => void)[] = [];
  if (typeof sdk.TOOL_MEDIA_RENDERER_AREA === "string")
    disposers.push(
      ctx.register({
        id: "studiotwin-env-media",
        area: sdk.TOOL_MEDIA_RENDERER_AREA,
        data: {
          tools: [...envTools, ...envTools.map((n) => "mcp__studiotwin__" + n)],
          render: (p: sdk.ToolMediaRendererProps) => {
            if (!envTool(p.toolName)) return p.fallback;
            try {
              const r = resultObject(p.result),
                stickers =
                  r.stickers === undefined ? [] : parseStickers(r.stickers),
                source = /\.(hdr|exr|png|jpe?g|webp)$/i.test(p.file.name)
                  ? { path: p.file.path, name: p.file.name }
                  : sourceValue(r.environment ?? r.panorama);
              if (!source) return p.fallback;
              return (
                <EnvCard
                  ctx={ctx}
                  source={source}
                  stickers={stickers}
                  sessionId={p.sessionId}
                  fallback={p.fallback}
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
      id: "studiotwin-env-directive",
      area: sdk.TRANSCRIPT_DIRECTIVE_AREA,
      data: {
        name: "studiotwin-env",
        render: (p: sdk.TranscriptDirectiveProps) => {
          try {
            const source = sourceValue(p.attrs);
            if (p.streaming || !source) return null;
            return (
              <EnvCard
                ctx={ctx}
                source={source}
                stickers={
                  p.attrs.stickers
                    ? parseStickers(JSON.parse(p.attrs.stickers))
                    : []
                }
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
