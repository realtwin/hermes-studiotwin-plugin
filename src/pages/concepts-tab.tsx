import * as sdk from "@hermes/plugin-sdk";
import { cardShell, cardTitle, cardSubtitle, filterPillStyle, nextActionChipStyle, creditBadgeStyle, nextDrawerStyle } from "../lib/ui-tokens.ts";
import { useStudioTwinSettings } from '../cards/settings.ts';
import { useEffect, useRef, useState } from "react";
import { conceptImages } from "../cards/image-card.tsx";
import { ImageViewer } from "../viewers/image-viewer.tsx";
import { object, type MediaScope } from "../cards/next-actions.ts";
import {
  compose,
  conceptActions,
  flow,
  list,

  useWorkspaceQuery,
  type Row,
} from "./workspace-data.ts";
function ConceptDetail({
  scope,
  row,
  session,
}: {
  scope: MediaScope;
  row: Row;
  session?: string | null;
}) {
  const query = useWorkspaceQuery(
    scope,
    "/concepts/" + encodeURIComponent(row.uuid ?? row.id),
  );
  const concept = object(query.data?.concept ?? query.data ?? row),
    history = conceptImages(concept);
  const [version, setVersion] = useState<number | null>(null);
  const activeIndex = Math.max(
      0,
      history.findIndex((v) => v.active),
    ),
    selected = history[version ?? activeIndex];
  return (
    <section style={{ ...cardShell, padding: 20, minWidth: 0 }} aria-label="Concept detail">
      <h2 style={{ ...cardTitle, marginBottom: 12 }}>{concept.name ?? row.name}</h2>
      <sdk.Badge>
        {concept.conceptType ?? row.conceptType ?? "Concept"}
      </sdk.Badge>
      {query.isError && <p role="alert">Could not load Concept history.</p>}
      <nav aria-label="Concept versions" style={{ ...flow, gap: 8, margin: "18px 0" }}>
        {history.map((v, i) => (
          <sdk.Button
            key={i}
            aria-pressed={i === (version ?? activeIndex)}
            style={filterPillStyle(i === (version ?? activeIndex))}
            onClick={() => setVersion(i)}
          >
            Version {i + 1}
          </sdk.Button>
        ))}
      </nav>
      {selected?.active && <sdk.Badge>Active asset</sdk.Badge>}
      {selected ? (
        <ImageViewer
          key={selected.source.asset}
          scope={scope}
          source={selected.source}
          before={selected.before}
        />
      ) : (
        <p>No generated image yet.</p>
      )}
      <section aria-label="Concept workflows" style={{ ...nextDrawerStyle, marginTop: 20, padding: 16 }}>
        <h3 style={{ ...cardTitle, margin: "0 0 12px" }}>Next</h3>
        {conceptActions(concept, selected?.source.asset).map((a) => (
          <div key={a.id} style={{ ...flow, justifyContent: "space-between", gap: 12, padding: "10px 0", borderBottom: "1px solid var(--ui-stroke-secondary)" }}>
            <sdk.Button style={nextActionChipStyle} onClick={() => compose(scope, session, a)}>
              {a.label}
            </sdk.Button>
            <small style={creditBadgeStyle}>{a.cost_label}</small>
          </div>
        ))}
        <p style={{ ...cardSubtitle, margin: "14px 0 0" }}>
          Drafts and active assets are separate. These actions only hand off to
          chat.
        </p>
      </section>
    </section>
  );
}
export function ConceptsTab({
  scope,
  configured,
  session,
}: {
  scope: MediaScope;
  configured: boolean;
  session?: string | null;
}) {
  const [selected, setSelected] = useState<Row | null>(null),
    [offset, setOffset] = useState(0);
  const layout = useRef<HTMLDivElement>(null);
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const node = layout.current;
    if (!node) return;
    const update = () => setNarrow(node.clientWidth < 660);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const { gallery_limit: limit } = useStudioTwinSettings(scope);
  useEffect(() => setOffset(0), [limit]);
  const query = useWorkspaceQuery(
      scope,
      `/concepts?limit=${limit}&offset=${offset}`,
      configured,
    ),
    rows = list(query.data, "concepts");
  return (
    <section aria-label="ConceptLab browser">
      <h2 style={{ ...cardTitle, margin: "0 0 8px" }}>ConceptLab</h2>
      <p style={{ ...cardSubtitle, margin: "0 0 20px" }}>Typed drafts, active assets and version history.</p>
      {!configured && <p>Configure StudioTwin to browse cloud Concepts.</p>}
      {query.isLoading && <p>Loading Concepts…</p>}
      {query.isError && <p role="alert">Could not load Concepts.</p>}
      <div
        ref={layout}
        style={{
          display: "grid",
          gridTemplateColumns: narrow ? "minmax(0,1fr)" : "minmax(240px,300px) minmax(0,1fr)",
          gap: 20,
          alignItems: "start",
        }}
      >
        <div style={{ display: "grid", gap: 10, minWidth: 0 }}>
        {rows.map((row) => (
          <article style={{ ...cardShell, padding: 16, minWidth: 0, borderColor: (selected?.uuid ?? selected?.id) === (row.uuid ?? row.id) ? "var(--ui-accent)" : "var(--ui-stroke-secondary)" }} key={row.uuid ?? row.id}>
            <sdk.Button style={{ ...filterPillStyle((selected?.uuid ?? selected?.id) === (row.uuid ?? row.id)), display: "block", textAlign: "left", whiteSpace: "normal", overflowWrap: "anywhere", marginBottom: 12 }} onClick={() => setSelected(row)}>
              {row.name ?? row.uuid}
            </sdk.Button>
            <sdk.Badge>{row.conceptType ?? row.type ?? "Concept"}</sdk.Badge>
            {row.activeAssetId && <p style={{ ...cardSubtitle, overflowWrap: "anywhere", fontSize: 11 }}>Active asset: {row.activeAssetId}</p>}
          </article>
        ))}
        </div>
      {selected && (
        <ConceptDetail
          key={selected.uuid ?? selected.id}
          scope={scope}
          row={selected}
          session={session}
        />
      )}
      </div>
      <nav aria-label="Concept pages" style={{ ...flow, gap: 8, marginTop: 20 }}>
        <sdk.Button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - limit))}
        >
          Previous Concepts
        </sdk.Button>
        <sdk.Button
          disabled={rows.length < limit}
          onClick={() => setOffset(offset + limit)}
        >
          Next Concepts
        </sdk.Button>
        <sdk.Button disabled={!configured} onClick={() => void query.refetch()}>
          Refresh Concepts
        </sdk.Button>
      </nav>
    </section>
  );
}
