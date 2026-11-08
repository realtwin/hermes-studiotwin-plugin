import { inspectorBackdropStyle, inspectorDialogStyle, inspectorSectionStyle, inspectorCloseStyle, inspectorChipStyle, inspectorButtonStyle } from '../lib/ui-tokens.ts';
import * as sdk from "@hermes/plugin-sdk";
import { downloadSource } from '../viewers/material-download.ts';
import { saveUrl } from '../cards/next-actions.ts';
import { modalityLabel } from '../lib/ui-tokens.ts';
import { assetDisplayName, copyId, formatDate, modalityIcon, siblingMaterialMaps } from './workspace-data.ts';
import { cardShell, cardTitle, cardSubtitle } from "../lib/ui-tokens.ts";
import { useStudioTwinSettings } from '../cards/settings.ts';
import { useEffect, useRef, useState } from "react";
import { useAssetLibrary } from './asset-library.ts';
import { sourceValue } from '../cards/env-card.tsx';
import { ModelViewer } from "../viewers/model-viewer.tsx";
import { AnimationViewer } from "../viewers/animation-viewer.tsx";
import { AudioCard } from "../cards/audio-card.tsx";
import { EnvViewer } from "../viewers/env-viewer.tsx";
import { MaterialViewer } from "../viewers/material-viewer.tsx";
import { ImageViewer } from "../viewers/image-viewer.tsx";
import { VideoViewer } from "../viewers/video-viewer.tsx";
import { parseMaterialMaps } from "../cards/material-card.tsx";
import {
  object,
  type MediaScope,
  type NextAction,
} from "../cards/next-actions.ts";
import {
  assetId,
  assetSource,
  compose,
  flow,
  modality,

  useWorkspaceQuery,
  type Row,
} from "./workspace-data.ts";
export function AssetPreview({
  ctx,
  scope,
  row,
  session,
  limit,
}: {
  ctx: sdk.PluginContext;
  scope: MediaScope;
  row: Row;
  session?: string | null;
  limit?: number;
}) {
  const settings = useStudioTwinSettings(scope);
  const environmentAssets = useAssetLibrary(scope, ['3d_model', 'material'].includes(modality(row)));
  if (row.type === 'rig_check') return <section aria-label="Rig compatibility" style={{ ...cardShell, padding: 20 }}>
    <h3>Rig compatibility</h3><p>{row.riggable ? `Riggable: ${row.rigType || 'yes'}` : 'Not riggable'}</p>
    {row.rigType && <sdk.Badge variant="muted" style={inspectorChipStyle}>{row.rigType}</sdk.Badge>}
  </section>;
  const environments = (environmentAssets.data ?? []).filter(r => modality(r) === 'environment').map(r => ({ label: r.name || assetId(r) || 'Panorama', source: assetSource(r) }));
  const source = assetSource(row),
    kind = modality(row),
    fallback = (
      <p role="status">
        Preview unavailable. Download the original asset instead.
      </p>
    );
  if (kind === "animation")
    return (
      <AnimationViewer
        rest={scope.rest}
        source={source}
        webgl_limit={limit}
        auto_rotate={settings.auto_rotate}
        fallback={fallback}
      />
    );
  if (kind === "3d_model")
    return (
      <ModelViewer
        rest={scope.rest}
        source={source}
        sessionId={session}
        onReskin={text => compose(scope, session, { id: 'reskin', label: 'Reskin 3D in Chat', message: text })}
        environments={environments}
        envSource={sourceValue(row.envSource) ?? undefined}
        webgl_limit={limit}
        auto_rotate={settings.auto_rotate}
        fallback={fallback}
      />
    );
  if (kind === "audio")
    return (
      <AudioCard
        ctx={{ ...ctx, rest: scope.rest }}
        source={source}
        sessionId={session}
        fallback={fallback}
      />
    );
  if (kind === "environment")
    return (
      <EnvViewer
        rest={scope.rest}
        source={source}
        webgl_limit={limit}
        fallback={fallback}
      />
    );
  if (kind === "material") {
    try {
      return (
        <MaterialViewer
          rest={scope.rest}
          maps={parseMaterialMaps(siblingMaterialMaps(row, environmentAssets.data ?? []))}
          webgl_limit={limit}
          fallback={fallback}
        />
      );
    } catch {
      return fallback;
    }
  }
  if (["video", "image_sequence"].includes(kind))
    return (
      <VideoViewer
        ctx={ctx}
        scope={scope}
        source={row.url ? { url: row.url } : source}
        fps={row.fps}
        frames={row.frames}
        fallback={fallback}
      />
    );
  if (kind === "image" || kind === "png" || kind === "jpg")
    return (
      <ImageViewer
        scope={scope}
        source={
          row.url && !assetId(row) && !source.path ? { url: row.url } : source
        }
        fallback={fallback}
      />
    );
  return fallback;
}
export function AssetInspector({
  ctx,
  scope,
  selected,
  onClose,
  session,
  limit,
}: {
  ctx: sdk.PluginContext;
  scope: MediaScope;
  selected: Row;
  onClose: () => void;
  session?: string | null;
  limit?: number;
}) {
  const [picked, setRow] = useState(selected),
    [error, setError] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const id = assetId(picked);
  const resolved = useWorkspaceQuery(
    scope,
    "/assets/" + encodeURIComponent(id ?? ""),
    Boolean(id) && !picked.local_path && !picked.path,
  );
  const row = { ...picked, ...resolved.data };
  const lineage = useWorkspaceQuery(
    scope,
    "/provenance?id=" + encodeURIComponent(id ?? ""),
    Boolean(id),
  );
  const actions = useWorkspaceQuery<{ actions: NextAction[] }>(
    scope,
    "/actions?" +
      new URLSearchParams({
        id: id ?? "",
        type: modality(row) === "material" ? "texture" : modality(row),
      }),
    Boolean(id),
  );
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    return () => previous?.focus();
  }, []);
  const pick = async (parent: Row) => {
    setError("");
    try {
      if (parent.relation === "job") {
        const result = object(
          await scope.rest("/details?id=" + encodeURIComponent(parent.id)),
        );
        const source = result.parents?.find(
          (p: Row) => p.relation === "source",
        );
        if (!source) {
          setError("Producing job has no recorded source assets.");
          return;
        }
        parent = source;
      }
      const found = object(
        await scope.rest("/assets/" + encodeURIComponent(parent.id)),
      );
      scope.assert();
      setRow(found);
    } catch {
      setError(
        "Could not resolve this lineage entry. Local provenance remains available.",
      );
    }
  };
  const record = object(lineage.data?.record);
  return (
    <div data-asset-backdrop onClick={e => { if (e.target === e.currentTarget) onClose(); }} style={{ ...inspectorBackdropStyle, position: 'fixed', inset: 0, zIndex: 120, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2vh 3vw' }}>
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Asset inspection"
      tabIndex={-1}
      ref={ref}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
        if (e.key === "Tab") {
          const items = ref.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled),a[href],input,select,[tabindex="0"]',
          );
          if (!items?.length) return;
          if (
            e.shiftKey &&
            (document.activeElement === items[0] ||
              document.activeElement === ref.current)
          ) {
            e.preventDefault();
            items[items.length - 1].focus();
          } else if (
            !e.shiftKey &&
            document.activeElement === items[items.length - 1]
          ) {
            e.preventDefault();
            items[0].focus();
          }
        }
      }}
      style={{
        ...cardShell,
        ...inspectorDialogStyle,
        maxHeight: '92vh',
        width: 'min(1120px, 100%)',
        boxSizing: 'border-box',
        overflowY: 'auto',
        padding: "0 clamp(16px, 3vw, 28px) 24px",
      }}
    >
      <header style={{ ...flow, ...inspectorDialogStyle, position: 'sticky', top: 0, zIndex: 2, border: 0, boxShadow: 'none', gap: 12, padding: '16px 0', marginBottom: 8 }}>
        <span style={{ ...inspectorChipStyle, padding: 10, borderRadius: 10 }}><sdk.Codicon name={modalityIcon(modality(row))} size={24} /></span>
        <div style={{ flex: '1 1 220px', minWidth: 0 }}>
        <h2 style={{ ...cardTitle, whiteSpace: 'normal', fontSize: 18, overflowWrap: "anywhere", minWidth: 0, flex: "1 1 240px" }}>{assetDisplayName(row).title}</h2>
        <sdk.Badge variant="muted" style={inspectorChipStyle}>{modalityLabel(modality(row))}</sdk.Badge>
        <sdk.Badge variant="muted" style={inspectorChipStyle}>{row.path || row.local_path ? 'Local' : 'Cloud'}</sdk.Badge>
        </div>
        <div style={{ ...flow, gap: 8, marginLeft: 'auto' }}>
        {id && <sdk.Button variant="outline" size="sm" style={inspectorButtonStyle} onClick={() => void copyId(scope, String(id))}><sdk.Codicon name="copy" size={14} />Copy ID</sdk.Button>}
        {(id || row.path || row.local_path || row.downloadUrl || row.url) && <sdk.Button variant="outline" size="sm" style={inspectorButtonStyle} onClick={() => {
          void (async () => {
            try {
              scope.assert();
              if (row.downloadUrl || row.url) saveUrl(scope, row.downloadUrl || row.url, assetDisplayName(row).title);
              else await downloadSource(scope.rest, assetSource(row), scope.assert);
            } catch { if (scope.current()) setError('Download unavailable. The original asset was not changed.'); }
          })();
        }}><sdk.Codicon name="cloud-download" size={14} />Download original</sdk.Button>}
        <span aria-hidden="true" style={{ ...inspectorSectionStyle, width: 1, height: 24 }} />
        <sdk.Button aria-label="Close asset inspection" variant="outline" size="sm" style={inspectorCloseStyle} onClick={onClose}><sdk.Codicon name="close" size={16} />Close <kbd style={inspectorChipStyle}>ESC</kbd></sdk.Button>
        </div>
      </header>
      <div style={{ ...flow, ...cardSubtitle, gap: 12, marginBottom: 16 }}>
        {id && <code style={{ userSelect: 'text' }}>{id}</code>}
        {row.extension && <sdk.Badge variant="muted" style={inspectorChipStyle}>.{String(row.extension).toUpperCase()}</sdk.Badge>}
        {formatDate(row.createdAt) && <time>{formatDate(row.createdAt)}</time>}
        {typeof row.bytes === 'number' && <span>{(row.bytes / 1024).toFixed(1)} KB</span>}
      </div>
      <AssetPreview
        key={id ?? row.path ?? row.url}
        ctx={ctx}
        scope={scope}
        row={row}
        session={session}
        limit={limit}
      />

      <section aria-label="Made from" style={{ ...inspectorSectionStyle, padding: 18, marginTop: 18, overflowWrap: "anywhere" }}>
        <h3 style={cardTitle}>Made from</h3>
        {!id ? (
          <p>No cloud lineage for this local file.</p>
        ) : lineage.isError ? (
          <p role="alert">Lineage unavailable.</p>
        ) : !lineage.data ? (
          <p>Loading lineage…</p>
        ) : (
          <>
            <p>
              {record.prompt ??
                lineage.data.made_from ??
                "No provenance recorded yet."}
            </p>
            {record.prompt && <sdk.Button variant="outline" size="sm" style={inspectorButtonStyle} onClick={() => compose(scope, session, { id: 'reuse', label: 'Reuse Prompt', message: record.prompt })}>Reuse Prompt</sdk.Button>}
            {record.tool && <p>Tool: {record.tool}</p>}
            {record.jobId && <p>Producing job: {record.jobId}</p>}
            <div style={flow}>
              {(lineage.data.parents ?? []).map((p: Row) => (
                <sdk.Button variant="outline" size="sm" style={inspectorButtonStyle}
                  key={p.relation + p.id}
                  onClick={() => void pick(p)}
                >
                  {p.relation === "job" ? "Producing job" : "Parent asset"}{" "}
                  {p.id}
                </sdk.Button>
              ))}
            </div>
          </>
        )}
        {error && <p role="alert">{error}</p>}
      </section>
      <section aria-label="Next" style={{ ...inspectorSectionStyle, padding: 18, marginTop: 18 }}>
        <h3 style={cardTitle}>Next</h3>
        <p style={cardSubtitle}>
          Composer handoff only. Review compatibility and approve cost in chat.
        </p>
        {actions.data?.actions.map((a) => (
          <sdk.Button variant="outline" size="sm" style={{ ...inspectorButtonStyle, margin: "8px 8px 0 0", whiteSpace: "normal", textAlign: "left" }} key={a.id} onClick={() => compose(scope, session, a)}>
            {a.label} ·{" "}
            {a.cost_label ?? "input-dependent credits; estimate first"}
          </sdk.Button>
        ))}
        {actions.isError && (
          <p>Next actions unavailable. Nothing was submitted.</p>
        )}
      </section>
    </div>
    </div>
  );
}
