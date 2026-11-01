import * as sdk from "@hermes/plugin-sdk";
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
    ? { path: row.local_path || row.path, name: row.name }
    : { asset: assetId(row), name: row.name };
}
export function modality(row: Row): string {
  if (row.maps || row.type === "material" || row.type === "texture")
    return "material";
  if (
    row.type === "environment" ||
    /\.(hdr|exr)$/i.test(row.name ?? row.path ?? "") ||
    row.environment === true
  )
    return "environment";
  return row.type ?? "unknown";
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
