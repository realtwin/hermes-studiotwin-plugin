import { secondaryButtonStyle, neutralBadgeStyle } from '../lib/ui-tokens.ts';
import * as sdk from '@hermes/plugin-sdk';
import { useEffect, useRef, useState } from 'react';
import { imageFile, type MediaScope } from '../cards/next-actions.ts';
import { cardShell, controlStrip, filterPillStyle, modalityLabel, styledSelect } from '../lib/ui-tokens.ts';
import { assetId, assetDisplayName, assetSource, flow, formatDate, modality, modalityIcon, type Row } from './workspace-data.ts';
import { useAssetLibrary } from './asset-library.ts';
const filters: [string, string[]][] = [
  ['All', []], ['3D & Rigged', ['3d_model', 'animation']], ['Audio SFX', ['audio']],
  ['360° Env', ['environment']], ['PBR Material', ['material']],
  ['Image & Concept', ['image', 'jpg', 'png']], ['Video', ['video', 'image_sequence']],
];
/** No WebGL in the grid. Fetch only admitted image posters, and only as they approach the viewport. */
function AssetPoster({ scope, row, thumbnail }: { scope: MediaScope; row: Row; thumbnail: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [url, setUrl] = useState('');
  const [failed, setFailed] = useState(false);
  const kind = modality(row);
  useEffect(() => {
    if (!thumbnail) return;
    let live = true, started = false;
    const load = () => {
      if (started) return;
      started = true;
      imageFile(scope, assetSource(row)).then(f => {
        if (live && scope.current()) setUrl(f.dataUrl);
      }).catch(() => { if (live) setFailed(true); });
    };
    const observer = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) { load(); observer?.disconnect(); }
    }, { rootMargin: '160px' });
    if (observer && ref.current) observer.observe(ref.current); else load();
    const stop = scope.watch(() => { live = false; setUrl(''); });
    return () => { live = false; observer?.disconnect(); stop(); };
  }, [scope, thumbnail, row.local_path, row.path, row.uuid, row.assetId]);
  const extension = String(row.extension || assetDisplayName(row).title.match(/\.(\w+)$/)?.[1] || '').toUpperCase();
  return <div ref={ref} data-asset-poster={kind} style={{ height: 132, borderRadius: 10, background: 'var(--ui-bg-secondary)', border: '1px solid var(--ui-stroke-tertiary, var(--ui-stroke-secondary))', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative', overflow: 'hidden' }}>
    {url && !failed ? <img alt="" src={url} loading="lazy" onError={() => setFailed(true)} style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : <span style={{ width: 48, height: 48, display: 'grid', placeItems: 'center', borderRadius: 999, background: 'color-mix(in srgb, var(--ui-text-primary) 7%, transparent)', border: '1px solid var(--ui-stroke-tertiary, var(--ui-stroke-secondary))', color: 'var(--ui-text-secondary)' }}><sdk.Codicon name={modalityIcon(kind)} size={24} /></span>}
    <div style={{ ...flow, position: 'absolute', inset: 'auto 6px 6px', gap: 4 }}>
      {[modalityLabel(kind), row.local_path || row.path ? 'Local' : 'Cloud', extension && '.' + extension].filter(Boolean).map(label => <span key={label} style={{ ...neutralBadgeStyle, background: 'color-mix(in srgb, var(--ui-bg-editor, var(--ui-bg-card)) 86%, transparent)', backdropFilter: 'blur(6px)' }}>{label}</span>)}
    </div>
  </div>;
}
export function LibraryTab({ scope, onInspect }: { scope: MediaScope; onInspect: (row: Row) => void }) {
  const [filter, setFilter] = useState('All'), [search, setSearch] = useState('');
  const query = useAssetLibrary(scope);
  const allowed = filters.find(([label]) => label === filter)![1];
  const rows = (query.data ?? []).filter(r => (!allowed.length || allowed.includes(modality(r))) &&
    `${assetDisplayName(r).title} ${r.name ?? ''} ${r.prompt ?? ''} ${assetId(r) ?? ''}`.toLowerCase().includes(search.toLowerCase()));
  let imageIndex = 0;
  return <section aria-label="Asset Library">
    <div style={{ ...controlStrip, gap: 8 }}>
      {filters.map(([label]) => <sdk.Button variant="ghost" size="sm" key={label} aria-pressed={label === filter} style={filterPillStyle(label === filter)} onClick={() => setFilter(label)}>{label}</sdk.Button>)}
      <div style={{ ...flow, gap: 8, flex: '1 1 420px' }}>
        <input type="search" aria-label="Search assets" placeholder="Search names, prompts, asset IDs…" value={search} onChange={e => setSearch(e.target.value)} style={{ ...styledSelect, flex: '1 1 260px', background: 'var(--ui-bg-input, var(--ui-bg-secondary))', border: '1px solid var(--ui-stroke-tertiary, var(--ui-stroke-secondary))', borderRadius: 8, padding: '7px 12px', boxSizing: 'border-box' }} />
        <span style={{ color: 'var(--ui-text-secondary)', fontSize: 12, marginLeft: 'auto' }}>{rows.length} assets</span>
        <sdk.Button variant="outline" size="sm" style={secondaryButtonStyle} onClick={() => void query.refetch()}><sdk.Codicon name="refresh" size={14} />Refresh library</sdk.Button>
      </div>
    </div>
    {query.isLoading && <p role="status">Loading assets…</p>}
    {query.isError && <p role="alert">Asset library unavailable. Refresh to retry this read.</p>}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(min(100%, 240px),1fr))', gap: 14, marginTop: 14 }}>
      {rows.map(row => {
        const display = assetDisplayName(row);
        const image = ['image', 'jpg', 'png'].includes(modality(row));
        const thumbnail = image && (Boolean(row.local_path || row.path) || imageIndex++ < 8);
        return <article key={assetId(row) ?? row.path} style={{ ...cardShell, background: 'color-mix(in srgb, var(--ui-bg-elevated, var(--ui-bg-card)) 75%, var(--ui-bg-secondary))', border: '1px solid var(--ui-stroke-tertiary, var(--ui-stroke-secondary))', padding: 10, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <AssetPoster scope={scope} row={row} thumbnail={thumbnail} />
          <h3 style={{ margin: 0, minWidth: 0 }}>
            <sdk.Button variant="ghost" size="sm" aria-label={String(row.name ?? assetId(row))} onClick={() => onInspect(row)}
              style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', textAlign: 'left', whiteSpace: 'normal', width: '100%', height: 'auto', padding: '4px 2px', borderRadius: 8, gap: 6, background: 'transparent', color: 'var(--ui-text-primary)', border: 0, cursor: 'pointer', outlineColor: 'var(--ui-accent)' }}>
              <span style={{ fontSize: 14, fontWeight: 650, overflowWrap: 'anywhere' }}>{display.title}</span>
              <span style={{ ...flow, gap: 6, fontSize: 11, fontWeight: 400, color: 'var(--ui-text-secondary)' }}>
                {display.shortId && <span>#{display.shortId}</span>}
                {formatDate(row.createdAt) && <time>{formatDate(row.createdAt)}</time>}
                {typeof row.bytes === 'number' && <span>{(row.bytes / 1024).toFixed(1)} KB</span>}
              </span>
            </sdk.Button>
          </h3>
          {row.prompt && <p style={{ margin: 0, fontSize: 12, lineHeight: 1.5, color: 'var(--ui-text-secondary)', overflowWrap: 'anywhere' }}>{row.prompt}</p>}
          {row.made_from && <sdk.Badge variant="muted" style={neutralBadgeStyle}>{String(row.made_from)}</sdk.Badge>}
        </article>;
      })}
    </div>
    {!query.isLoading && !query.isError && !rows.length && <p>No matching assets. Try another filter or upload a reference.</p>}
    <p style={{ color: 'var(--ui-text-secondary)', fontSize: 12, marginTop: 20 }}>Cloud links may expire. Cached and staged files remain on the connected Hermes host.</p>
  </section>;
}
