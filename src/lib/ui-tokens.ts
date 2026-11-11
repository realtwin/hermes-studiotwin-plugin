import type { CSSProperties } from 'react'

// Scoped inline primitives. Surfaces inherit Hermes colors rather than fixing a dark
// palette on the workspace. Only semantic status/HUD colors need stable fallbacks.
const stroke = '1px solid oklch(from var(--ui-stroke-secondary) l 0 h)'
export const visuallyHidden: CSSProperties = { position: 'absolute', width: 1, height: 1, padding: 0, margin: -1, overflow: 'hidden', clipPath: 'inset(50%)', whiteSpace: 'nowrap', border: 0 }
export const cardShell: CSSProperties = {
  borderRadius: 12, border: stroke, background: 'oklch(from var(--ui-bg-card, var(--ui-bg-secondary)) l 0 h)',
  boxShadow: 'var(--ui-shadow-card, 0 4px 16px color-mix(in srgb, oklch(from var(--ui-text) l 0 h) 14%, transparent))',
  overflow: 'hidden', minWidth: 0, color: 'oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h)',
}
export const cardHeader: CSSProperties = {
  display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8, padding: '10px 14px', borderBottom: stroke,
  background: 'color-mix(in srgb, oklch(from var(--ui-bg-secondary) l 0 h) 65%, transparent)',
}
export const cardTitle: CSSProperties = { fontWeight: 650, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, flex: '1 1 120px' }
export const cardSubtitle: CSSProperties = { fontSize: 11, lineHeight: 1.5, color: 'oklch(from var(--ui-text-secondary) l 0 h)', overflowWrap: 'anywhere', fontVariantNumeric: 'tabular-nums' }
export const cardBody: CSSProperties = { padding: 14, minWidth: 0 }
export const cardFooter: CSSProperties = { padding: '10px 14px', borderTop: stroke }
export const stageShell: CSSProperties = { position: 'relative', minWidth: 0, borderRadius: 10, overflow: 'hidden', border: stroke, background: 'oklch(from var(--ui-bg-secondary) l 0 h)', color: 'oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h)', accentColor: 'oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h)' }
export const glassToolbar: CSSProperties = {
  display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center', padding: '4px 6px', borderRadius: 8,
  background: 'color-mix(in srgb, oklch(from var(--ui-bg) l 0 h) 76%, transparent)', backdropFilter: 'blur(10px)', border: stroke,
}
export const glassStatsPill: CSSProperties = {
  display: 'inline-flex', gap: 6, alignItems: 'center', padding: '3px 8px', borderRadius: 6, fontSize: 11, lineHeight: 1.5,
  fontVariantNumeric: 'tabular-nums', background: 'color-mix(in srgb, oklch(from var(--ui-bg-editor, var(--ui-bg)) l 0 h) 86%, transparent)',
  color: 'oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h)', backdropFilter: 'blur(8px)', border: stroke,
}
export const controlStrip: CSSProperties = {
  display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, padding: '10px 12px', fontSize: 12, minWidth: 0,
  fontVariantNumeric: 'tabular-nums', background: 'color-mix(in srgb, oklch(from var(--ui-bg-secondary) l 0 h) 55%, transparent)',
}
export const styledSelect: CSSProperties = {
  padding: '5px 10px', borderRadius: 6, border: stroke, background: 'oklch(from var(--ui-bg-secondary) l 0 h)',
  color: 'oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h)', fontSize: 12, fontWeight: 500, cursor: 'pointer', minWidth: 0, maxWidth: '100%',
}
export const styledRange: CSSProperties = { accentColor: 'oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h)', cursor: 'pointer', minWidth: 40, maxWidth: '100%', verticalAlign: 'middle' }
export const posterTile: CSSProperties = {
  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10, width: '100%', minHeight: 220,
  padding: 16, boxSizing: 'border-box', borderRadius: 10, border: '1px dashed oklch(from var(--ui-stroke-secondary) l 0 h)',
  background: 'radial-gradient(ellipse at center, color-mix(in srgb, oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h) 7%, transparent), transparent 75%)',
  color: 'oklch(from var(--ui-text-secondary) l 0 h)', cursor: 'pointer',
}
export function filterPillStyle(active: boolean): CSSProperties {
  return {
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6, padding: '6px 11px', borderRadius: 999,
    fontSize: 12, cursor: 'pointer',
    ...(active ? {
      background: 'color-mix(in srgb, var(--ui-accent) 16%, var(--ui-bg-elevated, var(--ui-bg-secondary)))', color: 'var(--ui-text-primary, var(--ui-text))', border: '1px solid color-mix(in srgb, var(--ui-accent) 48%, var(--ui-stroke-secondary))', fontWeight: 600,
      boxShadow: 'var(--ui-shadow-control, 0 1px 4px color-mix(in srgb, var(--ui-text) 18%, transparent))',
    } : { background: 'color-mix(in srgb, var(--ui-bg-secondary) 60%, transparent)', color: 'var(--ui-text-secondary)', border: '1px solid var(--ui-stroke-tertiary, var(--ui-stroke-secondary))', fontWeight: 500 }),
  }
}
export const tabButtonStyle = (active: boolean): CSSProperties => ({
  ...filterPillStyle(false), borderRadius: 8, padding: '8px 18px',
  background: active ? 'var(--ui-bg-elevated, var(--ui-bg-card))' : 'transparent',
  color: active ? 'var(--ui-text-primary, var(--ui-text))' : 'var(--ui-text-secondary)',
  border: active ? stroke : '1px solid transparent', fontWeight: active ? 600 : 500,
  boxShadow: active ? 'var(--ui-shadow-control, 0 1px 3px color-mix(in srgb, var(--ui-text) 10%, transparent))' : 'none',
})
export const secondaryButtonStyle: CSSProperties = { ...filterPillStyle(false), borderRadius: 8, padding: '6px 11px', color: 'var(--ui-text-primary, var(--ui-text))' }
export const ghostButtonStyle: CSSProperties = { ...secondaryButtonStyle, background: 'transparent', border: '1px solid transparent' }
export const neutralBadgeStyle: CSSProperties = { ...secondaryButtonStyle, fontSize: 10, fontWeight: 500, padding: '2px 7px', borderRadius: 5, color: 'var(--ui-text-secondary)' }

// Inspection primitives strip chroma, never asset pixels. Relative colors preserve
// host lightness in both themes without importing the theme's accent into the room.
const neutralText = 'oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h)'
const neutralStroke = '1px solid oklch(from var(--ui-stroke-tertiary, var(--ui-stroke-secondary)) l 0 h)'
export const inspectorBackdropStyle: CSSProperties = { background: 'color-mix(in srgb, oklch(from var(--ui-bg-editor, var(--ui-bg-card, var(--ui-bg))) l 0 h) 84%, transparent)', backdropFilter: 'blur(12px)' }
export const inspectorDialogStyle: CSSProperties = { background: 'var(--theme-neutral-card, oklch(from var(--ui-bg-elevated, var(--ui-bg-card, var(--ui-bg))) l 0 h))', border: neutralStroke, color: neutralText, boxShadow: '0 24px 80px color-mix(in srgb, oklch(from var(--ui-stroke-secondary) l 0 h) 35%, transparent)' }
export const inspectorSectionStyle: CSSProperties = { background: 'var(--theme-neutral-chrome, oklch(from var(--ui-bg-secondary, var(--ui-bg-card)) l 0 h))', border: neutralStroke, color: neutralText, borderRadius: 10 }
export const inspectorStageStyle: CSSProperties = { ...inspectorSectionStyle, position: 'relative', minWidth: 0, overflow: 'hidden' }
export const inspectorButtonStyle: CSSProperties = { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6, padding: '6px 11px', borderRadius: 8, fontSize: 12, fontWeight: 500, cursor: 'pointer', background: 'color-mix(in srgb, oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h) 6%, transparent)', border: neutralStroke, color: neutralText, outlineColor: neutralText, accentColor: neutralText }
export const inspectorChipStyle: CSSProperties = { ...inspectorButtonStyle, padding: '2px 7px', borderRadius: 5, fontSize: 10, fontWeight: 500 }
export const inspectorCloseStyle: CSSProperties = { ...inspectorButtonStyle, padding: '6px 12px', borderRadius: 8, background: 'color-mix(in srgb, oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h) 10%, transparent)', border: '1px solid color-mix(in srgb, oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h) 28%, transparent)', fontWeight: 600, marginLeft: 'auto', flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 6 }
export const inspectorToggleStyle = (active: boolean): CSSProperties => ({ ...inspectorButtonStyle, borderRadius: 999, ...(active ? { background: 'color-mix(in srgb, oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h) 14%, transparent)', border: '1px solid color-mix(in srgb, oklch(from var(--ui-text-primary, var(--ui-text)) l 0 h) 38%, transparent)', fontWeight: 600 } : {}) })
export function statusBadgeStyle(status: string): CSSProperties {
  const tone = status === 'completed' ? 'var(--ui-success, hsl(160 84% 39%))'
    : ['failed', 'cancelled'].includes(status) ? 'var(--ui-danger, hsl(0 84% 60%))'
      : status === 'queued' ? 'var(--ui-warning, hsl(41 80% 47%))' : 'var(--ui-accent)'
  return {
    display: 'inline-flex', alignItems: 'center', padding: '2px 8px', borderRadius: 999, fontSize: 11, letterSpacing: 0.4,
    textTransform: 'uppercase', fontWeight: 650, color: 'var(--ui-text-primary, var(--ui-text))',
    border: `1px solid color-mix(in srgb, ${tone} 55%, transparent)`, background: `color-mix(in srgb, ${tone} 16%, transparent)`,
  }
}
export function modalityLabel(type: string): string {
  return ({ '3d_model': '3D Model', animation: 'Animation', audio: 'Audio SFX', environment: '360° Environment', material: 'PBR Material', image: 'Image / Concept', video: 'Video', image_sequence: 'Frame Sequence' } as Record<string, string>)[type] ?? type.replace(/[_-]/g, ' ')
}
export function cleanDisplayName(raw: string): { title: string; shortId: string } {
  const suffix = raw.match(/^(.+)@([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$/i)
  const name = suffix?.[1] ?? raw
  const match = name.match(/^([a-f0-9]{32}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})-(.+)$/i)
  return { title: match?.[2] ?? name, shortId: (suffix?.[2] ?? match?.[1] ?? '').slice(0, 8) }
}
export const nextDrawerStyle: CSSProperties = { ...inspectorSectionStyle, margin: '10px 12px 12px', padding: '8px 12px', borderRadius: 8 }
export const nextSummaryStyle: CSSProperties = { fontSize: 12, fontWeight: 600, color: 'oklch(from var(--ui-text-secondary) l 0 h)', cursor: 'pointer' }
export const nextActionChipStyle: CSSProperties = { ...inspectorButtonStyle, borderRadius: 7, margin: '8px 6px 0 0', flexWrap: 'wrap', textAlign: 'left' }
export const creditBadgeStyle: CSSProperties = { ...inspectorChipStyle, display: 'inline-flex', alignItems: 'center', gap: 4, borderRadius: 999, fontSize: 11, fontVariantNumeric: 'tabular-nums' }
