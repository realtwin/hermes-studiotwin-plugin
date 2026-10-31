import * as sdk from "@hermes/plugin-sdk";
import { useStudioTwinSettings } from '../cards/settings.ts';
import { useEffect, useState } from "react";
import { conceptImages } from "../cards/image-card.tsx";
import { ImageViewer } from "../viewers/image-viewer.tsx";
import { object, type MediaScope } from "../cards/next-actions.ts";
import {
  compose,
  conceptActions,
  flow,
  list,
  panel,
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
    <section style={panel} aria-label="Concept detail">
      <h2>{concept.name ?? row.name}</h2>
      <sdk.Badge>
        {concept.conceptType ?? row.conceptType ?? "Concept"}
      </sdk.Badge>
      {query.isError && <p role="alert">Could not load Concept history.</p>}
      <nav aria-label="Concept versions" style={flow}>
        {history.map((v, i) => (
          <sdk.Button
            key={i}
            aria-pressed={i === (version ?? activeIndex)}
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
      <section aria-label="Concept workflows">
        <h3>Next</h3>
        {conceptActions(concept, selected?.source.asset).map((a) => (
          <div key={a.id} style={flow}>
            <sdk.Button onClick={() => compose(scope, session, a)}>
              {a.label}
            </sdk.Button>
            <small>{a.cost_label}</small>
          </div>
        ))}
        <p>
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
      <h2>ConceptLab</h2>
      <p>Typed drafts, active assets and version history.</p>
      {!configured && <p>Configure StudioTwin to browse cloud Concepts.</p>}
      {query.isLoading && <p>Loading Concepts…</p>}
      {query.isError && <p role="alert">Could not load Concepts.</p>}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))",
          gap: 12,
        }}
      >
        {rows.map((row) => (
          <article style={panel} key={row.uuid ?? row.id}>
            <sdk.Button onClick={() => setSelected(row)}>
              {row.name ?? row.uuid}
            </sdk.Button>
            <sdk.Badge>{row.conceptType ?? row.type ?? "Concept"}</sdk.Badge>
            {row.activeAssetId && <p>Active asset: {row.activeAssetId}</p>}
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
      <nav aria-label="Concept pages">
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
