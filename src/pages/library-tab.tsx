import * as sdk from "@hermes/plugin-sdk";
import { useState } from "react";
import type { MediaScope } from "../cards/next-actions.ts";
import { cardShell, controlStrip, filterPillStyle, modalityLabel, cleanDisplayName, styledSelect } from "../lib/ui-tokens.ts";
import { assetId, flow, list, modality, type Row } from "./workspace-data.ts";
const filters: [string, string[]][] = [
  ["All", []], ["3D & Rigged", ["3d_model", "animation"]], ["Audio SFX", ["audio"]],
  ["360° Env", ["environment"]], ["PBR Material", ["material"]],
  ["Image & Concept", ["image", "jpg", "png"]], ["Video", ["video", "image_sequence"]],
];
export function LibraryTab({ scope, onInspect }: { scope: MediaScope; onInspect: (row: Row) => void }) {
  const [filter, setFilter] = useState("All"), [search, setSearch] = useState("");
  // Read every page before applying composite filters; partial results are not empty results.
  const query = sdk.useQuery<Row[]>({
    queryKey: ["studiotwin-workspace", scope.key, "complete-library"],
    queryFn: async () => {
      const rows = new Map<string, Row>();
      let offset = 0;
      for (;;) {
        const page = await scope.rest<Row>(`/assets?limit=100&offset=${offset}`);
        for (const row of list(page, "assets")) rows.set(assetId(row) ?? row.path, row);
        if (page.next_offset === null) return [...rows.values()];
        if (!Number.isInteger(page.next_offset) || page.next_offset <= offset)
          throw Error("Invalid asset pagination; refresh the library to retry.");
        offset = page.next_offset;
      }
    },
    enabled: scope.current(), retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false,
  });
  const allowed = filters.find(([label]) => label === filter)![1];
  const rows = (query.data ?? []).filter((r) =>
    (!allowed.length || allowed.includes(modality(r))) &&
    `${r.name ?? ""} ${r.prompt ?? ""} ${assetId(r) ?? ""}`.toLowerCase().includes(search.toLowerCase()));
  return (
    <section aria-label="Asset Library">
      <div style={{ ...controlStrip, gap: 8 }}>
        {filters.map(([label]) => (
          <sdk.Button key={label} aria-pressed={label === filter} style={filterPillStyle(label === filter)} onClick={() => setFilter(label)}>{label}</sdk.Button>
        ))}
      <div style={{ ...flow, gap: 8, flex: '1 1 420px' }}>
        <input type="search" aria-label="Search assets" placeholder="Search names, prompts, asset IDs…" value={search} onChange={(e) => setSearch(e.target.value)}
          style={{ ...styledSelect, flex: '1 1 260px', padding: "10px 12px", boxSizing: "border-box" }} />
        <span style={{ color: "var(--ui-text-secondary)", fontSize: 12, marginLeft: "auto" }}>{rows.length} assets</span>
        <sdk.Button onClick={() => void query.refetch()}>Refresh library</sdk.Button>
      </div>
      </div>
      {query.isLoading && <p role="status">Loading assets…</p>}
      {query.isError && <p role="alert">Asset library unavailable. Refresh to retry this read.</p>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(min(100%, 240px),1fr))", gap: 14, marginTop: 14 }}>
        {rows.map((row) => {
          const display = cleanDisplayName(String(row.name ?? assetId(row) ?? "Asset"));
          const shortId = display.shortId || assetId(row)?.slice(0, 8);
          return (
            <article key={assetId(row) ?? row.path} style={{ ...cardShell, padding: 18, minWidth: 0, display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={{ ...flow, justifyContent: "space-between" }}>
                <span style={{ display: "inline-flex", padding: 12, borderRadius: 12, background: "var(--ui-bg-primary)", color: "var(--ui-accent)" }}>
                  <sdk.Codicon name={modality(row) === "audio" ? "unmute" : "symbol-misc"} size={28} />
                </span>
                <sdk.Badge>{row.local_path || row.path ? "Local" : "Cloud"}</sdk.Badge>
              </div>
              <h3 style={{ margin: 0, minWidth: 0 }}>
                <sdk.Button aria-label={String(row.name ?? assetId(row))} onClick={() => onInspect(row)} style={{ ...filterPillStyle(true), display: "flex", flexDirection: "column", alignItems: "flex-start", textAlign: "left", whiteSpace: "normal", width: "100%", padding: 12, borderRadius: 8, gap: 6 }}>
                  <span style={{ fontSize: 15, fontWeight: 650, overflowWrap: "anywhere" }}>{display.title}</span>
                  {shortId && <span style={{ fontFamily: "monospace", fontSize: 11, opacity: .85 }}>{shortId}</span>}
                  {display.title !== (row.name ?? assetId(row)) && <span style={{ fontSize: 11, fontWeight: 400, overflowWrap: "anywhere", lineHeight: 1.5, opacity: .8 }}>{row.name ?? assetId(row)}</span>}
                </sdk.Button>
              </h3>
              {row.prompt && <p style={{ margin: 0, fontSize: 12, lineHeight: 1.5, color: "var(--ui-text-secondary)", overflowWrap: "anywhere" }}>{row.prompt}</p>}
              <div style={{ ...flow, gap: 6, marginTop: "auto" }}>
                {(row.local_path || row.path) && assetId(row) && <sdk.Badge>Cloud</sdk.Badge>}
                <sdk.Badge>{modalityLabel(modality(row))}</sdk.Badge>
                {row.made_from && <sdk.Badge>{String(row.made_from)}</sdk.Badge>}
              </div>
            </article>
          );
        })}
      </div>
      {!query.isLoading && !query.isError && !rows.length && <p>No matching assets. Try another filter or upload a reference.</p>}
      <p style={{ color: "var(--ui-text-secondary)", fontSize: 12, marginTop: 20 }}>Cloud links may expire. Cached and staged files remain on the connected Hermes host.</p>
    </section>
  );
}
