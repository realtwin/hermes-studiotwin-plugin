import { secondaryButtonStyle, neutralBadgeStyle } from '../lib/ui-tokens.ts';
import * as sdk from '@hermes/plugin-sdk';
import { cardShell, controlStrip, filterPillStyle, statusBadgeStyle, creditBadgeStyle } from '../lib/ui-tokens.ts';
import { useStudioTwinSettings } from '../cards/settings.ts';
import { useEffect, useRef, useState } from 'react';
import { normalizeJobStatus } from '../lib/state-machines.ts';
import { deliveryUrl, object, type MediaScope } from '../cards/next-actions.ts';
import { compose, copyId, flow, formatDate, list, useWorkspaceQuery, type Row } from './workspace-data.ts';
export function normalizedJobs(value: unknown): Row[] {
  return list(value, 'jobs').map(r => ({ ...r, status: normalizeJobStatus(r.status) }));
}
export function jobPrompt(row: Row): string {
  const prompt = row.inputs?.prompt ?? row.outputs?.prompt?.user ?? row.prompt;
  return typeof prompt === 'string' ? prompt : '';
}
function JobThumbnail({ row }: { row: Row }) {
  const url = row.outputs?.imageUrl ?? row.inputs?.imageUrl;
  if (typeof url !== 'string') return null;
  try {
    return <img alt="Job image preview" src={deliveryUrl(url)} loading="lazy" onError={e => { e.currentTarget.hidden = true; }} style={{ width: 72, height: 72, objectFit: 'cover', borderRadius: 8, background: 'var(--ui-bg-secondary)' }} />;
  } catch { return null; }
}
export function jobToolLabel(tool: string): string {
  if (/rigg?ab|rig-check/i.test(tool)) return 'Rig compatibility';
  if (/rig/i.test(tool)) return 'Auto-rig';
  if (/motion|animat/i.test(tool)) return 'Animation';
  if (/material|texture/i.test(tool)) return 'PBR Material';
  if (/environment|pano|hdr/i.test(tool)) return '360° Environment';
  if (/mesh|3d/i.test(tool)) return '3D Model';
  if (/audio|sound/i.test(tool)) return 'Audio SFX';
  if (/video/i.test(tool)) return 'Video';
  if (/image|concept/i.test(tool)) return 'Image / Concept';
  return tool.replace(/[-_]/g, ' ').replace(/\bfn\b$/, '').trim();
}
export function jobMetadata(row: Row): string[] {
  const input = object(row.inputs), out = object(row.outputs);
  const time = out.metadata?.generationTime ?? out.processingTime;
  return [time !== undefined ? `Generation: ${time}${typeof time === 'number' ? 's' : ''}` : '',
    out.model, input.mode, input.size, input.quality,
    out.riggable !== undefined ? `riggable: ${out.riggable ? out.rigType || 'yes' : 'no'}` : '',
  ].filter(v => typeof v === 'string' && v.trim());
}
export function JobsTab({ scope, configured, onInspect, session }: {
  scope: MediaScope; configured: boolean; onInspect: (row: Row) => void; session?: string | null;
}) {
  const [filter, setFilter] = useState('All'), [offset, setOffset] = useState(0), [busy, setBusy] = useState(''), [error, setError] = useState('');
  const lock = useRef(false);
  const { gallery_limit: limit } = useStudioTwinSettings(scope);
  useEffect(() => setOffset(0), [limit]);
  const query = useWorkspaceQuery(scope, `/jobs?limit=${limit}&offset=${offset}`, configured, 5000);
  const rows = normalizedJobs(query.data), shown = rows.filter(r => filter === 'All' || (filter === 'Active' ? ['queued', 'running'].includes(r.status) : r.status === filter.toLowerCase()));
  const cancel = async (id: string) => {
    if (lock.current) return;
    lock.current = true; setBusy(id); setError('');
    try { scope.assert(); await scope.rest('/cancel', { method: 'POST', body: { id } }); await query.refetch(); }
    catch { if (scope.current()) setError('Cancellation could not be confirmed. Check the existing job before retrying.'); }
    finally { lock.current = false; setBusy(''); }
  };
  const inspect = async (row: Row) => {
    setError('');
    try {
      const output = object(await scope.rest('/jobs/' + encodeURIComponent(row.uuid ?? row.id) + '/output'));
      scope.assert();
      onInspect(output);
    } catch { if (scope.current()) setError('Output unavailable. The existing job was not resubmitted.'); }
  };
  return <section aria-label="StudioTwin jobs">
    <div style={{ ...controlStrip, gap: 8 }}>
      {['All', 'Active', 'Completed', 'Failed', 'Cancelled'].map(label => <sdk.Button variant="ghost" size="sm" key={label} aria-pressed={label === filter} style={filterPillStyle(label === filter)} onClick={() => setFilter(label)}>{label}</sdk.Button>)}
      <sdk.Button variant="outline" size="sm" style={secondaryButtonStyle} onClick={() => void query.refetch()} disabled={!configured}>Refresh jobs</sdk.Button>
    </div>
    {!configured && <p>Configure StudioTwin to read cloud jobs.</p>}
    {query.isLoading && <p>Loading jobs…</p>}
    {query.isError && <p role="alert">Could not load jobs.</p>}
    {error && <p role="alert">{error}</p>}
    {shown.map(row => {
      const id = row.uuid ?? row.id, prompt = jobPrompt(row), tool = row.tool ?? row.functionName ?? row.function_name ?? 'StudioTwin job';
      const pct = typeof row.progress === 'number' && Number.isFinite(row.progress) ? Math.max(0, Math.min(100, row.progress)) : undefined;
      return <article key={id} style={{ ...cardShell, marginTop: 12, padding: 18, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 16 }}>
        <JobThumbnail row={row} />
        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <header style={{ ...flow, gap: 10, marginBottom: 10 }}>
            <sdk.Badge variant="muted" style={neutralBadgeStyle}>{jobToolLabel(tool)}</sdk.Badge><strong style={{ fontSize: 12, overflowWrap: 'anywhere' }}>{tool}</strong>
            <sdk.Badge variant="muted" style={statusBadgeStyle(row.status)}>{row.status}</sdk.Badge>
            <span style={creditBadgeStyle}>{row.cost ?? row.creditCost ?? row.credits ?? row.estimate ?? 'Unknown'} credits</span>
          </header>
          {row.inputs_truncated === true && <p style={{ fontSize: 12, color: 'var(--ui-text-secondary)' }}>Inputs too large to display. Large input values were omitted.</p>}
          {prompt && <p style={{ fontSize: 14, lineHeight: 1.6, margin: '0 0 10px', overflowWrap: 'anywhere' }}>{prompt}</p>}
          <div style={{ ...flow, gap: 6, marginBottom: 10 }}>
            {jobMetadata(row).map(text => <span key={text} style={creditBadgeStyle}>{text}</span>)}
            {formatDate(row.finishedAt) && <time style={{ fontSize: 11, color: 'var(--ui-text-secondary)' }}>{formatDate(row.finishedAt)}</time>}
          </div>
          <code style={{ fontSize: 11, color: 'var(--ui-text-secondary)', overflowWrap: 'anywhere', userSelect: 'text' }}>{id}</code>
          {['queued', 'running'].includes(row.status) && <><progress aria-label="Job progress" max="100" value={pct} style={{ width: '100%', accentColor: 'var(--ui-accent)' }} /><small>{pct === undefined ? 'Progress not reported' : `${pct}%`}</small></>}
        </div>
        <div style={{ ...flow, marginLeft: 'auto', gap: 8 }}>
          <sdk.Button variant="outline" size="sm" style={secondaryButtonStyle} onClick={() => void copyId(scope, String(id))}>Copy ID</sdk.Button>
          {prompt && <sdk.Button variant="outline" size="sm" style={secondaryButtonStyle} onClick={() => compose(scope, session, { id: 'reuse', label: 'Reuse Prompt', message: prompt })}>Reuse Prompt</sdk.Button>}
          {row.status === 'queued' && <sdk.Button variant="outline" size="sm" style={secondaryButtonStyle} disabled={Boolean(busy)} onClick={() => void cancel(id)}>Cancel queued job</sdk.Button>}
          {row.status === 'completed' && <sdk.Button variant="secondary" size="sm" style={secondaryButtonStyle} onClick={() => void inspect(row)}><sdk.Codicon name="eye" size={14} />Inspect Output</sdk.Button>}
        </div>
      </article>;
    })}
    {!query.isLoading && configured && !shown.length && <p>No matching jobs on this page.</p>}
    <nav aria-label="Job pages" style={{ ...flow, marginTop: 20, gap: 12 }}>
      <sdk.Button variant="outline" size="sm" style={secondaryButtonStyle} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous jobs</sdk.Button>
      <span>Offset {offset}</span>
      <sdk.Button variant="outline" size="sm" style={secondaryButtonStyle} disabled={rows.length < limit} onClick={() => setOffset(offset + limit)}>Next jobs</sdk.Button>
    </nav>
  </section>;
}
