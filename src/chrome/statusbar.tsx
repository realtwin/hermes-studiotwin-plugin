import * as sdk from "@hermes/plugin-sdk";
import { creditBadgeStyle } from "../lib/ui-tokens.ts";
import { connectSettings } from '../cards/settings.ts';
import { useEffect, useState, type ReactNode } from "react";
import { modelScopeKey } from "../viewers/model-source.ts";
import { useMediaScope } from "../cards/next-actions.ts";
function ScopedChrome({ children }: { children: ReactNode }) {
  const [key, setKey] = useState(() => modelScopeKey(sdk.host.state));
  useEffect(() => {
    const update = () => setKey(modelScopeKey(sdk.host.state));
    const stops = [sdk.host.state?.profile, sdk.host.state?.connectionId].map(
      (a) => a?.subscribe(update),
    );
    return () => stops.forEach((stop) => stop?.());
  }, []);
  return <span key={key}>{children}</span>;
}
import { useWorkspaceQuery } from "../pages/workspace-data.ts";
import { normalizedJobs } from "../pages/jobs-tab.tsx";
const chip = {
  ...creditBadgeStyle,
  border: "1px solid var(--ui-stroke-secondary)",
  background: "var(--ui-bg-card)",
  color: "var(--ui-text-primary)",
  borderRadius: 999,
  padding: "3px 9px",
  fontSize: 11,
  font: "inherit",
  cursor: "pointer",
  display: "inline-flex",
  gap: 6,
  alignItems: "center",
};
export function CreditsChip({
  ctx,
  onOpen,
}: {
  ctx: sdk.PluginContext;
  onOpen: () => void;
}) {
  const { scope, stale } = useMediaScope(ctx),
    query = useWorkspaceQuery(scope, "/status", !stale, 30000);
  if (
    stale ||
    !query.data?.configured ||
    query.data?.settings?.show_credits === false ||
    typeof query.data?.balance !== "number"
  )
    return null;
  return (
    <button type="button" style={chip} onClick={onOpen}>
      StudioTwin {query.data.balance.toLocaleString()} credits
    </button>
  );
}
export function ActiveJobsChip({
  ctx,
  onOpen,
}: {
  ctx: sdk.PluginContext;
  onOpen: () => void;
}) {
  const { scope, stale } = useMediaScope(ctx),
    status = useWorkspaceQuery(scope, "/status", !stale, 30000);
  const jobs = sdk.useQuery({
    queryKey: ["studiotwin-workspace", scope.key, "active-job-count"],
    enabled: !stale && status.data?.configured === true,
    retry: false,
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const active = new Set<string>();
      for (let offset = 0; ; offset += 100) {
        const rows = normalizedJobs(
          await scope.rest(`/jobs?limit=100&offset=${offset}`),
        );
        rows
          .filter((r) => ["queued", "running"].includes(r.status))
          .forEach((r) => active.add(r.uuid ?? r.id));
        if (rows.length < 100) return active.size;
      }
    },
  });
  const count = jobs.data ?? 0;
  if (stale || !count) return null;
  return (
    <button type="button" style={chip} onClick={onOpen}>
      <sdk.Codicon name="loading" spinning />
      {count} active StudioTwin jobs
    </button>
  );
}
export function registerStatusbar(
  ctx: sdk.PluginContext,
  open: (tab?: "Library" | "Jobs") => void,
) {
  const refresh = () =>
    void sdk.queryClient.invalidateQueries({
      queryKey: ["studiotwin-workspace", modelScopeKey(sdk.host.state)],
    });
  // Settings only change /status. Refetching asset detail here can replace an
  // active cloud model source with its newly cached local path and dispose it.
  connectSettings(ctx);
  ctx.onEvent("tool.complete", refresh);
  ctx.register({
    id: "studiotwin-credits",
    area: sdk.STATUSBAR_AREAS?.right ?? 'statusBar.right',
    order: 80,
    render: () => (
      <ScopedChrome>
        <CreditsChip ctx={ctx} onOpen={() => open("Library")} />
      </ScopedChrome>
    ),
  });
  ctx.register({
    id: "studiotwin-active-jobs",
    area: sdk.STATUSBAR_AREAS?.right ?? 'statusBar.right',
    order: 81,
    render: () => (
      <ScopedChrome>
        <ActiveJobsChip ctx={ctx} onOpen={() => open("Jobs")} />
      </ScopedChrome>
    ),
  });
}
