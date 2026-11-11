import * as sdk from "@hermes/plugin-sdk";
import { cleanDisplayName, modalityLabel } from '../lib/ui-tokens.ts';
import {
  object,
  type MediaScope,
  type NextAction,
} from "../cards/next-actions.ts";
export type Row = Record<string, any>;
export const tabs = ["Library", "Jobs", "Concepts", "Upload"] as const;
export type WorkspaceTab = (typeof tabs)[number];
export const panel = {
  padding: 16,
  border: "1px solid var(--ui-stroke-secondary)",
  borderRadius: 12,
  background: "var(--ui-bg-card)",
  color: "var(--ui-text-primary)",
};
export const flow = {
  display: "flex",
  gap: 8,
  flexWrap: "wrap" as const,
  alignItems: "center",
};
export function list(value: unknown, key: string): Row[] {
  if (Array.isArray(value))
    return value.filter((v) => v && typeof v === "object");
  const row = object(value);
  return row[key] === undefined ? [] : list(row[key], key);
}
export function useWorkspaceQuery<T = Row>(
  scope: MediaScope,
  path: string,
  enabled = true,
  interval?: number,
) {
  return sdk.useQuery<T>({
    queryKey: ["studiotwin-workspace", scope.key, path],
    queryFn: () => scope.rest<T>(path),
    enabled: enabled && scope.current(),
    retry: false,
    refetchInterval: interval ?? false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}
export function openSettings(ctx: sdk.PluginContext) {
  // Optional host door is newer than the pinned ambient SDK. Do not alter the frozen SDK contract.
  const door = (
    ctx as sdk.PluginContext & { openPluginSettings?: (id?: string) => void }
  ).openPluginSettings;
  if (typeof door === "function") door.call(ctx, "hermes-studiotwin");
  else sdk.host.navigate("/settings?tab=plugins&agent=hermes-studiotwin");
}
export const assetId = (row: Row) => row.uuid ?? row.assetId;
export function assetSource(row: Row) {
  return row.local_path || row.path
    ? { path: row.local_path || row.path, name: row.name ? cleanDisplayName(row.name).title : undefined }
    : { asset: assetId(row), name: row.name ? cleanDisplayName(row.name).title : undefined };
}
const pbrFile = /^(.*)-(basecolor|albedo|normal|normals|roughness|metalness|metallic|height|heightmap)\.(png|jpg|jpeg|webp)$/i;
export function modality(row: Row): string {
  if (row.maps || row.type === "material" || row.type === "texture") return "material";
  // Explicit non-image types are authoritative; infer richer image modalities from cloud metadata.
  if (row.type && !['image', 'png', 'jpg', 'unknown'].includes(row.type)) return row.type;
  const names = [row.name, row.path, row.local_path, row.s3Uri].filter(Boolean).map(v => String(v).split(/[?#]/)[0]);
  if (/^\.?(hdr|exr)$/i.test(row.extension ?? '') || names.some(n => /\.(hdr|exr)$/i.test(n) || /\/panoramas\//i.test(n)) || row.environment === true) return 'environment';
  if (names.some(n => pbrFile.test(cleanDisplayName(n).title))) return 'material';
  return row.type ?? "unknown";
}
export function assetDisplayName(row: Row): { title: string; shortId: string } {
  const raw = String(row.name || String(row.s3Uri || row.local_path || row.path || '').split(/[?#]/)[0].split('/').pop() || '');
  const display = cleanDisplayName(raw);
  const generated = /^(?:openai[_-])?([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}|[a-f0-9]{32})(?:_\d+)?(?:\.(\w+))?$/i.exec(display.title);
  const shortId = display.shortId || generated?.[1].slice(0, 8) || String(assetId(row) ?? '').slice(0, 8);
  const ext = generated?.[2] || String(row.extension || '').replace(/^\./, '');
  const label = modality(row) === 'image' ? 'Image' : modalityLabel(modality(row));
  return { title: raw && !generated ? display.title : `${label === 'unknown' ? 'Asset' : label} · ${shortId || 'Untitled'}${ext ? '.' + ext : ''}`, shortId };
}
/** Same folder AND material stem: never cross-wire unrelated jobs or materials. */
export function siblingMaterialMaps(row: Row, library: Row[]): Record<string, any> {
  if (row.maps) return row.maps;
  const identity = (r: Row) => {
    const uri = String(r.s3Uri ?? '').split(/[?#]/)[0];
    const slash = uri.lastIndexOf('/');
    const match = pbrFile.exec(uri.slice(slash + 1));
    return slash >= 0 && match ? { folder: uri.slice(0, slash), stem: match[1], channel: match[2].toLowerCase() } : null;
  };
  const target = identity(row), maps: Record<string, any> = {};
  if (!target) return { albedo: assetSource(row) };
  const aliases: Record<string, string> = { basecolor: 'albedo', normals: 'normal', metallic: 'metalness', height: 'heightmap' };
  for (const candidate of [...library, row]) {
    const key = identity(candidate);
    if (key && key.folder === target.folder && key.stem === target.stem) maps[aliases[key.channel] ?? key.channel] = assetSource(candidate);
  }
  return maps;
}
export function modalityIcon(type: string): string {
  return ({ '3d_model': 'symbol-misc', animation: 'person', audio: 'unmute', environment: 'globe', material: 'paintcan', image: 'file-media', video: 'device-camera-video', image_sequence: 'play-circle' } as Record<string, string>)[type] ?? 'file-media';
}
export function formatDate(value: unknown): string {
  if (!value) return '';
  const date = new Date(value as string);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}
export async function copyId(scope: MediaScope, id: string) {
  try {
    scope.assert();
    if (!navigator.clipboard) throw Error('Clipboard unavailable');
    await navigator.clipboard.writeText(id);
    if (scope.current()) sdk.host.notify({ kind: 'success', message: 'ID copied' });
  } catch {
    if (scope.current()) sdk.host.notify({ kind: 'warning', message: 'Could not copy. Select the ID and copy it manually.' });
  }
}
export function compose(
  scope: MediaScope,
  session: string | null | undefined,
  action: NextAction,
) {
  try {
    scope.assert();
    if (!sdk.host.composer?.submit(typeof session === 'string' && session.trim() ? session : null, action.message))
      sdk.host.notify({
        kind: "warning",
        message: "Open the originating chat to continue this workflow.",
      });
  } catch {
    sdk.host.notify({
      kind: "warning",
      message: "Reopen StudioTwin in the originating profile and connection.",
    });
  }
}
export function conceptActions(concept: Row, asset?: string): NextAction[] {
  const ref = `Concept ${concept.uuid ?? concept.id}${asset ? `, asset ${asset}` : ""}`;
  return [
    [
      "generate",
      "Generate Image",
      "studiotwin_conceptlab_generate",
      "approximately 1–74 credits; estimate exact inputs",
    ],
    [
      "edit",
      "Edit Concept",
      "studiotwin_conceptlab_edit",
      "approximately 3–74 credits; estimate exact inputs",
    ],
    ["mesh", "Convert to 3D Mesh", "image-to-3d-mesh", "25 credits"],
    ["env", "Convert to 360° Env", "image-to-environment-map", "25 credits"],
  ].map(([id, label, tool, cost_label]) => ({
    id,
    label,
    tool,
    cost_label,
    message: `StudioTwin ${ref}: ${label} using ${tool} (${cost_label}). Read the live tool schema, verify compatibility, estimate the exact inputs with studiotwin_estimate_cost and ask me to approve credits before submitting.`,
  }));
}
