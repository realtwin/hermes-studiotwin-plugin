import * as sdk from "@hermes/plugin-sdk";
import { creditBadgeStyle, statusBadgeStyle, tabButtonStyle } from "../lib/ui-tokens.ts";
import { connectSettings, useStudioTwinSettings } from '../cards/settings.ts';
import { useEffect, useState } from "react";
import { useMediaScope } from "../cards/next-actions.ts";
import { LibraryTab } from "./library-tab.tsx";
import { JobsTab } from "./jobs-tab.tsx";
import { ConceptsTab } from "./concepts-tab.tsx";
import { UploadDrawer } from "./upload-drawer.tsx";
import { AssetInspector } from "./asset-inspector.tsx";
import {
  flow,
  openSettings,
  panel,
  tabs,
  useWorkspaceQuery,
  type Row,
  type WorkspaceTab,
} from "./workspace-data.ts";
export interface WorkspaceNavigation {
  get: () => WorkspaceTab;
  subscribe: (fn: (tab: WorkspaceTab) => void) => () => void;
}
export function StudioTwinPage({
  ctx,
  initialTab = "Library",
  navigation,
}: {
  ctx: sdk.PluginContext;
  initialTab?: WorkspaceTab;
  navigation?: WorkspaceNavigation;
}) {
  const { scope, stale } = useMediaScope(ctx);
  useEffect(() => connectSettings(ctx), [ctx]);
  const settings = useStudioTwinSettings(scope);
  const [tab, setTab] = useState<WorkspaceTab>(navigation?.get() ?? initialTab),
    [selected, setSelected] = useState<Row | null>(null);
  const [session] = useState(
    () => sdk.host.state?.activeSessionId?.get() ?? null,
  );
  const status = useWorkspaceQuery(scope, "/status", !stale, 30000);
  useEffect(() => navigation?.subscribe(setTab), [navigation]);
  const configured = status.data?.configured === true;
  // Permanent invalidation prevents away-and-back scope resurrection, including pending file reads.
  if (stale)
    return (
      <section style={panel}>
        <h1>StudioTwin</h1>
        <p role="status">
          Profile or connection changed. Reopen the StudioTwin workspace to load
          assets from that scope.
        </p>
      </section>
    );
  return (
    <main
      style={{
        padding: "24px clamp(16px, 3vw, 40px)",
        boxSizing: "border-box",
        height: "100%",
        overflowY: "auto",
        color: "var(--ui-text-primary)",
      }}
    >
      <header style={{ ...flow, justifyContent: "space-between", gap: 20 }}>
        <div>
          <h1 style={{ margin: "0 0 8px", fontSize: 28, letterSpacing: "-0.04em" }}>StudioTwin</h1>
          <p style={{ color: "var(--ui-text-secondary)", margin: 0, fontSize: 13 }}>
            Your creative workspace · inspect, trace and continue
          </p>
        </div>
        <div style={{ ...flow, gap: 10 }}>
          <span style={statusBadgeStyle(configured ? "completed" : "unknown")}>
            <span aria-hidden="true">● </span>{configured ? "Connected" : status.isLoading ? "Connecting…" : "Local workspace"}
          </span>
          {configured && status.data?.settings?.show_credits !== false && typeof status.data?.balance === "number" && (
            <span style={creditBadgeStyle}>{status.data.balance.toLocaleString()} credits</span>
          )}
          <sdk.Button onClick={() => openSettings(ctx)}>Plugin Settings</sdk.Button>
        </div>
      </header>
      {status.data?.configured === false && (
        <section aria-label="StudioTwin setup" style={panel}>
          <h2>Connect StudioTwin</h2>
          <p>
            Add STUDIOTWIN_API_KEY in Plugin Settings to browse cloud assets and
            jobs. Your cached and staged local assets are still available below.
          </p>
          <sdk.Button onClick={() => openSettings(ctx)}>
            Open Plugin Settings
          </sdk.Button>{" "}
          <a href="https://studiotwin.ai" target="_blank" rel="noreferrer">
            Visit StudioTwin
          </a>
        </section>
      )}
      {status.isError && (
        <p role="alert">
          StudioTwin status unavailable. You can still try the local asset
          library.
        </p>
      )}
      <nav
        role="tablist"
        aria-label="StudioTwin workspace"
        style={{ ...flow, gap: 4, margin: "24px 0", padding: 5, border: "1px solid var(--ui-stroke-secondary)", borderRadius: 12, background: "var(--ui-bg-card)", width: "fit-content", maxWidth: "100%" }}
      >
        {tabs.map((label) => (
          <sdk.Button
            key={label}
            role="tab"
            aria-selected={tab === label}
            style={tabButtonStyle(tab === label)}
            id={"studiotwin-tab-" + label}
            aria-controls="studiotwin-panel"
            onClick={() => {
              setSelected(null);
              setTab(label);
            }}
            onKeyDown={(e) => {
              if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
                e.preventDefault();
                const next =
                  tabs[
                    (tabs.indexOf(tab) + (e.key === "ArrowRight" ? 1 : 3)) % 4
                  ];
                setTab(next);
                document.getElementById("studiotwin-tab-" + next)?.focus();
              }
            }}
          >
            {label}
          </sdk.Button>
        ))}
      </nav>
      <div
        role="tabpanel"
        id="studiotwin-panel"
        aria-labelledby={"studiotwin-tab-" + tab}
      >
        {tab === "Library" && (
          <LibraryTab scope={scope} onInspect={setSelected} />
        )}
        {tab === "Jobs" && (
          <JobsTab
            scope={scope}
            session={session}
            configured={configured}
            onInspect={setSelected}
          />
        )}
        {tab === "Concepts" && (
          <ConceptsTab
            scope={scope}
            configured={configured}
            session={session}
          />
        )}
        {tab === "Upload" && (
          <UploadDrawer
            scope={scope}
            configured={configured}
            session={session}
            onUploaded={() => {
              void sdk.queryClient.invalidateQueries({
                queryKey: ["studiotwin-workspace", scope.key],
              });
            }}
          />
        )}
      </div>
      {selected && (
        <AssetInspector
          key={selected.uuid ?? selected.path ?? selected.url}
          ctx={ctx}
          scope={scope}
          selected={selected}
          onClose={() => setSelected(null)}
          session={session}
          limit={settings.webgl_limit}
        />
      )}
    </main>
  );
}
