import { secondaryButtonStyle } from '../lib/ui-tokens.ts';
import * as sdk from "@hermes/plugin-sdk";
import { cardShell, cardTitle, cardSubtitle, controlStrip, filterPillStyle } from "../lib/ui-tokens.ts";
import { useRef, useState } from "react";
import type { UploadLifecycleState } from "../lib/state-machines.ts";
import { object, type MediaScope } from "../cards/next-actions.ts";
import { compose, type Row } from "./workspace-data.ts";
export async function uploadReference(
  scope: MediaScope,
  file: File,
  cloud: boolean,
) {
  scope.assert();
  if (!file.size || file.size > 50 * 1024 * 1024)
    throw Error("Choose a nonempty file no larger than 50 MiB.");
  if (
    !/^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}$/.test(file.name) ||
    file.name.includes("..")
  )
    throw Error("Use a plain file name.");
  if (
    !/\.(glb|fbx|obj|hdr|exr|png|jpe?g|webp|wav|mp3|ogg|opus|flac|mp4|tar|json)$/i.test(
      file.name,
    )
  )
    throw Error("Unsupported reference file type.");
  // Read first, then assert BEFORE dispatch: ctx.rest routes synchronously to the selected backend.
  const bytes = new Uint8Array(await file.arrayBuffer());
  scope.assert();
  let binary = "";
  for (let i = 0; i < bytes.length; i += 32768)
    binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
  const result = object(
    await scope.rest("/upload", {
      method: "POST",
      body: { filename: file.name, data: btoa(binary), cloud },
      timeoutMs: 180000,
    }),
  );
  scope.assert();
  // Whitelist final asset metadata. Presigned POST session fields never belong in a UI result.
  const asset = result.assets?.[0]?.uuid ?? result.assetIds?.[0] ?? result.uuid;
  if (
    cloud &&
    (typeof asset !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        asset,
      ))
  )
    throw Error(
      "Upload completion did not return an asset UUID. Inspect the library before retrying.",
    );
  return {
    name: file.name,
    path: result.path,
    uuid: cloud ? asset : undefined,
    cloud,
  };
}
export function UploadDrawer({
  scope,
  configured,
  session,
  onUploaded,
}: {
  scope: MediaScope;
  configured: boolean;
  session?: string | null;
  onUploaded?: () => void;
}) {
  const [cloud, setCloud] = useState(false);
  const [state, setState] = useState<UploadLifecycleState<Row>>({ phase: 'idle' });
  const busy = state.phase === 'uploading';
  const result = state.phase === 'succeeded' ? state.result : null;
  const lock = useRef(false);
  const upload = async (file?: File) => {
    if (!file || lock.current) return;
    if (cloud && !configured) {
      setState({ phase: 'failed', message: "Configure StudioTwin before uploading to the cloud." });
      return;
    }
    lock.current = true;
    setState({ phase: 'uploading', filename: file.name, destination: cloud ? 'cloud' : 'local' });
    try {
      const saved = await uploadReference(scope, file, cloud);
      scope.assert();
      setState({ phase: 'succeeded', result: saved });
      onUploaded?.();
    } catch (e) {
      setState({ phase: 'failed', message:
          scope.current() && e instanceof Error
            ? /^(Choose a|Use a plain|Unsupported reference|Upload completion)/.test(
                e.message,
              )
              ? e.message
              : "Upload could not be confirmed. Inspect the library before retrying."
            : "Upload could not be confirmed. Inspect the library before retrying.",
        });
    } finally {
      lock.current = false;
    }
  };
  return (
    <section data-upload-state={state.phase} aria-label="Upload reference" style={{ ...cardShell, padding: 24, maxWidth: 920, margin: "0 auto" }}>
      <h2 style={{ ...cardTitle, margin: "0 0 10px" }}>Upload a reference</h2>
      <p style={{ ...cardSubtitle, lineHeight: 1.6, marginBottom: 20 }}>
        Stage on the connected Hermes host, or explicitly send the file to
        StudioTwin. No generation is submitted.
      </p>
      <div style={{ ...controlStrip, justifyContent: "space-between", gap: 12 }}>
        <span style={cardSubtitle}>Destination · {cloud ? 'StudioTwin cloud' : 'Local staging'}</span>
      <label style={{ ...filterPillStyle(cloud), cursor: 'pointer' }}>
        <input
          type="checkbox"
          checked={cloud}
          disabled={busy || !configured}
          onChange={(e) => setCloud(e.target.checked)}
        />
        Cloud upload
      </label>
      </div>
      <div
        aria-label="Drop reference asset"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          void upload(e.dataTransfer.files[0]);
        }}
        style={{
          padding: "48px 20px",
          marginTop: 20,
          border: "2px dashed var(--ui-stroke-secondary)",
          borderRadius: 16,
          textAlign: "center",
          background: "var(--ui-bg-primary)",
        }}
      >
        <span style={{ display: "inline-flex", padding: 18, background: "color-mix(in srgb, var(--ui-text-primary) 6%, var(--ui-bg-secondary))", borderRadius: 18, color: "var(--ui-text-secondary)" }}><sdk.Codicon name="cloud-upload" size={40} /></span>
        <p style={{ fontSize: 16, fontWeight: 600, margin: "20px 0 16px" }}>Drop a reference here or choose a file</p>
        <label style={{ ...secondaryButtonStyle, position: 'relative', cursor: busy ? 'wait' : 'pointer', padding: '10px 18px', borderRadius: 8 }}>
        Choose file…
        <input
          type="file"
          aria-label="Reference file"
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0, cursor: busy ? 'wait' : 'pointer' }}
          disabled={busy}
          accept=".glb,.fbx,.obj,.hdr,.exr,.png,.jpg,.jpeg,.webp,.wav,.mp3,.ogg,.opus,.flac,.mp4,.tar,.json"
          onChange={(e) => {
            void upload(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        </label>
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 6, marginTop: 24 }}>
          {["GLB · FBX · OBJ", "HDR · EXR", "PNG · JPG · WEBP", "WAV · MP3 · OGG · OPUS · FLAC", "MP4", "TAR · JSON"].map((format) => <span key={format} style={{ ...filterPillStyle(false), fontSize: 11, padding: '3px 9px', cursor: "default" }}>{format}</span>)}
        </div>
        <p style={{ ...cardSubtitle, margin: "16px 0 0", fontSize: 11 }}>Up to 50 MiB · {cloud ? "StudioTwin cloud" : "Connected Hermes host"}</p>
      </div>
      {state.phase === 'uploading' && <p role="status">Uploading reference… {state.filename} · {state.destination === 'cloud' ? 'StudioTwin cloud' : 'Local staging'}</p>}
      {state.phase === 'failed' && <p role="alert">{state.message}</p>}
      {result && (
        <div style={{ ...cardShell, padding: 16, marginTop: 20 }}>
          <p>
            {result.name} ·{" "}
            {result.cloud ? "Cloud assetId" : "Local staging path"}
          </p>
          <code style={{ overflowWrap: "anywhere" }}>
            {result.uuid ?? result.path}
          </code>
          <sdk.Button variant="outline" size="sm" style={secondaryButtonStyle}
            onClick={() =>
              compose(scope, session, {
                id: "upload",
                label: "Use in Chat",
                message: result.uuid
                  ? `Use uploaded asset ${result.uuid} (${result.name}) to ...`
                  : `Use staged local reference ${result.path} (${result.name}) to ... Ask before uploading this file or spending credits.`,
              })
            }
          >
            Use in Chat
          </sdk.Button>
        </div>
      )}
    </section>
  );
}
