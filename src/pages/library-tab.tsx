import * as sdk from "@hermes/plugin-sdk";
import { useState } from "react";
import type { MediaScope } from "../cards/next-actions.ts";
import {
  assetId,
  flow,
  list,
  modality,
  panel,
  type Row,
} from "./workspace-data.ts";
const filters: [string, string[]][] = [
  ["All", []],
  ["3D & Rigged", ["3d_model", "animation"]],
  ["Audio SFX", ["audio"]],
  ["360° Env", ["environment"]],
  ["PBR Material", ["material"]],
  ["Image & Concept", ["image", "jpg", "png"]],
  ["Video", ["video", "image_sequence"]],
];
export function LibraryTab({
  scope,
  onInspect,
}: {
  scope: MediaScope;
  onInspect: (row: Row) => void;
}) {
  const [filter, setFilter] = useState("All"),
    [search, setSearch] = useState("");
  // Load the entire merged library before client-side composite modality/search
  // predicates run. A failed later page fails the read, never a false empty result.
  const query = sdk.useQuery<Row[]>({
    queryKey: ["studiotwin-workspace", scope.key, "complete-library"],
    queryFn: async () => {
      const rows = new Map<string, Row>();
      let offset = 0;
      for (;;) {
        const page = await scope.rest<Row>(`/assets?limit=100&offset=${offset}`);
        for (const row of list(page, "assets"))
          rows.set(assetId(row) ?? row.path, row);
        if (page.next_offset === null) return [...rows.values()];
        if (!Number.isInteger(page.next_offset) || page.next_offset <= offset)
          throw Error("Invalid asset pagination; refresh the library to retry.");
        offset = page.next_offset;
      }
    },
    enabled: scope.current(),
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const allowed = filters.find(([label]) => label === filter)![1];
  const rows = (query.data ?? []).filter(
    (r) =>
      (!allowed.length || allowed.includes(modality(r))) &&
      `${r.name ?? ""} ${r.prompt ?? ""} ${assetId(r) ?? ""}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <section aria-label="Asset Library">
      <div style={flow}>
        {filters.map(([label]) => (
          <sdk.Button
            key={label}
            aria-pressed={label === filter}
            onClick={() => setFilter(label)}
          >
            {label}
          </sdk.Button>
        ))}
      </div>
      <input
        type="search"
        aria-label="Search assets"
        placeholder="Search names, prompts, asset IDs…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{
          width: "min(100%, 420px)",
          padding: 8,
          margin: "16px 0",
          color: "var(--ui-text-primary)",
          background: "var(--ui-bg-card)",
          border: "1px solid var(--ui-stroke-secondary)",
          borderRadius: 8,
        }}
      />
      <sdk.Button onClick={() => void query.refetch()}>
        Refresh library
      </sdk.Button>
      {query.isLoading && <p role="status">Loading assets…</p>}
      {query.isError && (
        <p role="alert">
          Asset library unavailable. Refresh to retry this read.
        </p>
      )}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill,minmax(210px,1fr))",
          gap: 12,
        }}
      >
        {rows.map((row) => (
          <article key={assetId(row) ?? row.path} style={panel}>
            <sdk.Codicon
              name={modality(row) === "audio" ? "unmute" : "symbol-misc"}
              size={28}
            />
            <h3>
              <sdk.Button onClick={() => onInspect(row)}>
                {row.name ?? assetId(row)}
              </sdk.Button>
            </h3>
            <sdk.Badge>
              {row.local_path || row.path ? "Local" : "Cloud"}
            </sdk.Badge>{" "}
            {(row.local_path || row.path) && assetId(row) && (
              <sdk.Badge>Cloud</sdk.Badge>
            )}{" "}
            <sdk.Badge>{modality(row)}</sdk.Badge>
            <p style={{ color: "var(--ui-text-secondary)" }}>
              {row.prompt ??
                row.made_from ??
                "Select to inspect and continue the workflow"}
            </p>
          </article>
        ))}
      </div>
      {!query.isLoading && !query.isError && !rows.length && (
        <p>No matching assets. Try another filter or upload a reference.</p>
      )}
      <p style={{ color: "var(--ui-text-secondary)" }}>
        Cloud links may expire. Cached and staged files remain on the connected
        Hermes host.
      </p>
    </section>
  );
}
