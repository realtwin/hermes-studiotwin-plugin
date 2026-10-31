import * as sdk from "@hermes/plugin-sdk";
import { useStudioTwinSettings } from '../cards/settings.ts';
import { useEffect, useRef, useState } from "react";
import { jobStatus } from "../cards/task-card.tsx";
import { object, type MediaScope } from "../cards/next-actions.ts";
import {
  flow,
  list,
  panel,
  useWorkspaceQuery,
  type Row,
} from "./workspace-data.ts";
export function normalizedJobs(value: unknown): Row[] {
  return list(value, "jobs").map((r) => {
    try {
      return { ...r, status: jobStatus(r.status) };
    } catch {
      return { ...r, status: "unknown" };
    }
  });
}
export function JobsTab({
  scope,
  configured,
  onInspect,
}: {
  scope: MediaScope;
  configured: boolean;
  onInspect: (row: Row) => void;
}) {
  const [filter, setFilter] = useState("All"),
    [offset, setOffset] = useState(0),
    [busy, setBusy] = useState(""),
    [error, setError] = useState("");
  const lock = useRef(false);
  const { gallery_limit: limit } = useStudioTwinSettings(scope);
  useEffect(() => setOffset(0), [limit]);
  const query = useWorkspaceQuery(
    scope,
    `/jobs?limit=${limit}&offset=${offset}`,
    configured,
    5000,
  );
  const rows = normalizedJobs(query.data),
    shown = rows.filter(
      (r) =>
        filter === "All" ||
        (filter === "Active"
          ? ["queued", "running"].includes(r.status)
          : r.status === filter.toLowerCase()),
    );
  const cancel = async (id: string) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(id);
    setError("");
    try {
      scope.assert();
      await scope.rest("/cancel", { method: "POST", body: { id } });
      await query.refetch();
    } catch {
      if (scope.current())
        setError(
          "Cancellation could not be confirmed. Check the existing job before retrying.",
        );
    } finally {
      lock.current = false;
      setBusy("");
    }
  };
  const inspect = async (row: Row) => {
    setError("");
    try {
      const full = {
        ...row,
        ...object(
          await scope.rest("/jobs/" + encodeURIComponent(row.uuid ?? row.id)),
        ),
      };
      const outputs = object(full.outputs),
        asset =
          outputs.assetId ??
          outputs.assetIds?.[0] ??
          full.assetId ??
          full.outputAssetIds?.[0];
      if (asset)
        onInspect(
          object(await scope.rest("/assets/" + encodeURIComponent(asset))),
        );
      else if (outputs.imageUrl)
        onInspect({
          type: "image",
          url: outputs.imageUrl,
          name: "Completed job output",
        });
      else if (outputs.videoUrl)
        onInspect({
          type: "video",
          url: outputs.videoUrl,
          name: "Completed job output",
        });
      else
        setError(
          "Completed job has no previewable output asset. Inspect its output links in chat.",
        );
    } catch {
      setError("Output unavailable. The existing job was not resubmitted.");
    }
  };
  return (
    <section aria-label="StudioTwin jobs">
      <div style={flow}>
        {["All", "Active", "Completed", "Failed", "Cancelled"].map((label) => (
          <sdk.Button
            key={label}
            aria-pressed={label === filter}
            onClick={() => setFilter(label)}
          >
            {label}
          </sdk.Button>
        ))}
        <sdk.Button onClick={() => void query.refetch()} disabled={!configured}>
          Refresh jobs
        </sdk.Button>
      </div>
      {!configured && <p>Configure StudioTwin to read cloud jobs.</p>}
      {query.isLoading && <p>Loading jobs…</p>}
      {query.isError && <p role="alert">Could not load jobs.</p>}
      {error && <p role="alert">{error}</p>}
      {shown.map((row) => {
        const id = row.uuid ?? row.id;
        const pct =
          typeof row.progress === "number" && Number.isFinite(row.progress)
            ? Math.max(0, Math.min(100, row.progress))
            : undefined;
        return (
          <article key={id} style={{ ...panel, marginTop: 12 }}>
            <header style={flow}>
              <strong>
                {row.tool ??
                  row.functionName ??
                  row.function_name ??
                  "StudioTwin job"}
              </strong>
              <sdk.Badge>{row.status}</sdk.Badge>
              <span>
                {row.cost ??
                  row.creditCost ??
                  row.credits ??
                  row.estimate ??
                  "Unknown"}{" "}
                credits
              </span>
            </header>
            <code>{id}</code>
            {["queued", "running"].includes(row.status) && (
              <>
                <progress
                  aria-label="Job progress"
                  max="100"
                  value={pct}
                  style={{ width: "100%", accentColor: "var(--ui-accent)" }}
                />
                {pct === undefined ? (
                  <small>Progress not reported</small>
                ) : (
                  <small>{pct}%</small>
                )}
              </>
            )}
            {row.status === "queued" && (
              <sdk.Button
                disabled={Boolean(busy)}
                onClick={() => void cancel(id)}
              >
                Cancel queued job
              </sdk.Button>
            )}
            {row.status === "completed" && (
              <sdk.Button onClick={() => void inspect(row)}>
                Inspect Output
              </sdk.Button>
            )}
          </article>
        );
      })}
      {!query.isLoading && configured && !shown.length && (
        <p>No matching jobs on this page.</p>
      )}
      <nav aria-label="Job pages" style={flow}>
        <sdk.Button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - limit))}
        >
          Previous jobs
        </sdk.Button>
        <span>Offset {offset}</span>
        <sdk.Button
          disabled={rows.length < limit}
          onClick={() => setOffset(offset + limit)}
        >
          Next jobs
        </sdk.Button>
      </nav>
    </section>
  );
}
