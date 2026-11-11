// Ambient types for the parts of `@hermes/plugin-sdk` this package uses (typecheck only; the host
// supplies the real module at runtime and only `@hermes/plugin-sdk`, `react` and `react/jsx-runtime`
// resolve in a disk plugin). Shapes mirror hermes-agent 088f657 apps/desktop/src/sdk/index.ts and
// the modules it re-exports (contrib/plugin.ts, app/routes.ts, lib/tool-media-renderers.ts, ...).
//
// Every member newer than the oldest supported Desktop is optional and feature-detected at the call
// site (DESIGN §4.4). Area constants are typed as their exact strings so tests can pin them to core.
// Add a member here only when a slice uses it; S01 owns this file.
import type { ComponentProps, CSSProperties, ReactNode } from 'react'

// ── Plugin contract (contrib/plugin.ts) ──────────────────────────────────────

export interface PluginRestOptions {
  method?: string
  body?: unknown
  /** Single-file multipart upload (newer Desktops; older ones drop it and send no body). */
  upload?: { filename: string; contentType?: string; bytes: ArrayBuffer }
  timeoutMs?: number
}

export interface PluginFileDialogOptions {
  defaultPath?: string
  filters?: Array<{ extensions: string[]; name: string }>
  title?: string
}

/** Result-shaped OS door: members resolve false/null instead of throwing when unavailable. */
export interface PluginOs {
  openExternal: (url: string) => Promise<boolean>
  revealPath: (path: string) => Promise<boolean>
  pickOpenPath?: (options?: PluginFileDialogOptions) => Promise<null | string>
  pickSavePath?: (options?: PluginFileDialogOptions) => Promise<null | string>
  writeClipboard?: (text: string) => Promise<boolean>
}

export interface PluginStorage {
  get<T>(key: string, fallback: T): T
  set(key: string, value: unknown): void
  remove(key: string): void
}

export type PluginMessageValue = string | ((...args: never[]) => string)
export interface PluginMessages {
  [key: string]: PluginMessages | PluginMessageValue
}
export type PluginLocaleBundles = { [locale: string]: PluginMessages | undefined }
export type PluginTranslate = (key: string, ...args: unknown[]) => string

export interface PluginI18n {
  register: (bundles: PluginLocaleBundles) => () => void
  t: PluginTranslate
  onLocaleChange: (listener: () => void) => () => void
}

export interface GatewayEvent {
  type: string
  payload?: unknown
  session_id?: string
  /** Renderer-side tags: the profile/connection in front when it arrived. */
  profile?: string
  connectionId?: string
  /** Client-local: recovered/held during a reconnect, not fresh work. */
  replayed?: boolean
}
export type GatewayEventListener = (event: GatewayEvent) => void

export interface ReadableAtom<T> {
  get: () => T
  subscribe: (fn: (value: T) => void) => () => void
}

export interface PluginContribution {
  id: string
  area: string
  title?: string
  order?: number
  when?: () => boolean
  enabled?: boolean
  data?: unknown
  render?: () => ReactNode
}

export interface PluginSettingsSubpage {
  id: string
  title: string
  render: () => ReactNode
}
export interface PluginSettingsPage {
  id: string
  title: string
  icon?: string
  order?: number
  render: () => ReactNode
  children?: PluginSettingsSubpage[]
}

export interface PluginContext {
  readonly source: string
  register: (c: PluginContribution) => () => void
  registerMany: (cs: PluginContribution[]) => () => void
  /** Newer Desktops: feature-detect `ctx.registerSettingsPage?.(...)`. */
  registerSettingsPage?: (page: PluginSettingsPage) => () => void
  onDispose: (fn: () => void) => void
  onEvent: (type: string, listener: GatewayEventListener) => () => void
  /** Scoped timers/listeners, cleared on unload. Never use bare globals (Desktop SDK pitfalls). */
  setTimeout?: (fn: () => void, ms: number) => () => void
  setInterval?: (fn: () => void, ms: number) => () => void
  addEventListener?: (
    target: EventTarget,
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: AddEventListenerOptions | boolean
  ) => () => void
  /** REST to this plugin's own backend namespace `/api/plugins/<id>`. */
  rest: <T>(path: string, opts?: PluginRestOptions) => Promise<T>
  /** Accelerator only: a no-op on OAuth remotes, so always keep a polling fallback. */
  socket?: (path: string, onMessage: (data: unknown) => void) => () => void
  os: PluginOs
  storage?: PluginStorage
  i18n?: PluginI18n
}

export interface HermesPlugin {
  id: string
  name?: string
  description?: string
  defaultEnabled?: boolean
  capabilities?: readonly string[]
  register: (ctx: PluginContext) => void
}

// ── Area constants and payloads ──────────────────────────────────────────────

export const ROUTES_AREA: 'routes'
export const SIDEBAR_NAV_AREA: 'sidebar.nav'
export const STATUSBAR_AREAS: { readonly left: 'statusBar.left'; readonly right: 'statusBar.right' }
export const PALETTE_AREA: 'palette'
export const KEYBINDS_AREA: 'keybinds'
export const COMPOSER_AREAS: {
  readonly top: 'composer.top'
  readonly bottom: 'composer.bottom'
  readonly underside: 'composer.underside'
  readonly leading: 'composer.leading'
  readonly actions: 'composer.actions'
  readonly middleware: 'composer.middleware'
  readonly attachments: 'composer.attachments'
  readonly microActions: 'composer.microActions'
  readonly atCompletions: 'composer.atCompletions'
  readonly modelPill: 'composer.modelPill'
  readonly contextMenu: 'composer.contextMenu'
}
export const TRANSCRIPT_DIRECTIVE_AREA: 'transcript.directives'
/** Desktops with the tool-media renderer seam only; undefined on older ones (feature-detect it). */
export const TOOL_MEDIA_RENDERER_AREA: 'transcript.toolMedia' | undefined
/** Newer Desktops only; undefined on older ones. */
export const SETTINGS_PLUGINS_AREA: 'settings.plugins' | undefined

export interface RouteContribution {
  /** Absolute path, one segment, no params (e.g. `/studiotwin`). */
  path: string
}
export interface SidebarNavContribution {
  /** Codicon name. */
  codicon: string
  label: string
  path: string
  tier?: string
}
export interface StatusbarItem {
  id: string
  render?: () => ReactNode
  label?: ReactNode
  detail?: ReactNode
  icon?: ReactNode
  disabled?: boolean
  hidden?: boolean
  title?: string
  to?: string
  onSelect?: () => void
  variant?: 'action' | 'link' | 'menu' | 'text'
  toggleLabel?: string
}
export interface PaletteContribution {
  id: string
  label: string
  action?: string
  keywords?: string[]
  run: () => void
  detail?: () => string
  keepOpen?: boolean
}
export type KeybindCategory = 'composer' | 'profiles' | 'session' | 'navigation' | 'view'
export interface KeybindContribution {
  id: string
  category?: KeybindCategory
  /** Canonical combos (e.g. `mod+shift+s`). Empty leaves the action unbound. */
  defaults?: readonly string[]
  label: string
  run: () => void
}
export interface ComposerAttachmentContext {
  insertText: (text: string) => void
}
export interface ComposerAttachmentProvider {
  label: string
  icon?: string
  run: (ctx: ComposerAttachmentContext) => void | Promise<void>
}

/** Props a transcript directive's render receives. `sessionId` is undefined on hosts before the
 *  directive-owner seam: feature-detect `props.sessionId !== undefined`. */
export interface TranscriptDirectiveProps {
  attrs: Readonly<Record<string, string>>
  source: string
  streaming: boolean
  sessionId?: null | string
}
export interface TranscriptDirectiveContribution {
  /** `::<name>{...}`: lowercase `[a-z0-9-]`, unique across plugins. */
  name: string
  render: (props: TranscriptDirectiveProps) => ReactNode
}

export type MediaKind = 'audio' | 'image' | 'video' | 'file'
/** The file a tool-media renderer draws. `path` is on the BACKEND's machine; load via `resolveUrl`. */
export interface ToolMediaFile {
  path: string
  name: string
  kind: MediaKind
  mime: string
  resolveUrl: () => Promise<string>
}
export interface ToolMediaRendererProps {
  file: ToolMediaFile
  toolName: string
  toolCallId: string
  args: Readonly<Record<string, unknown>>
  result: unknown
  sessionId: null | string
  /** The built-in player: return it for anything this package does not draw. */
  fallback: ReactNode
}
export interface ToolMediaRendererContribution {
  /** Exact names or a trailing-`*` prefix such as `mcp__studiotwin__*`; only this package's tools. */
  tools: readonly string[]
  render: (props: ToolMediaRendererProps) => ReactNode
}

// ── Host ─────────────────────────────────────────────────────────────────────

export interface ConnectionRow {
  id: string
  kind?: string
  label?: string
  primary?: boolean
}

export const host: {
  /** Composer bus: `null` = the composer the user is typing in. Newer Desktops only. */
  composer?: {
    /** Synchronous: true only when an addressed visible composer accepted the text (DESIGN §4.3). */
    submit: (sessionId: null | string, text: string) => boolean
    insertText?: (sessionId: null | string, text: string, opts?: { mode?: 'block' | 'inline' | 'prefix' }) => Promise<boolean>
    setDraft?: (sessionId: null | string, text: string) => Promise<boolean>
    focus?: (sessionId?: null | string) => void
  }
  state?: {
    profile?: ReadableAtom<string>
    connectionId?: ReadableAtom<null | string>
    activeSessionId?: ReadableAtom<null | string>
  }
  connections?: () => Promise<ConnectionRow[]>
  navigate: (path: string) => void
  notify: (input: { kind?: 'error' | 'info' | 'success' | 'warning'; message: string; title?: string }) => string
}

// ── React / state re-exports ─────────────────────────────────────────────────

export function useValue<T>(store: ReadableAtom<T>): T
export function atom<T>(initial: T): ReadableAtom<T> & { set: (value: T) => void }
export { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
export const queryClient: import('@tanstack/react-query').QueryClient

// ── UI kit (theme-aware; never hardcode colors) ──────────────────────────────

export function Button(
  props: ComponentProps<'button'> & {
    asChild?: boolean
    size?: 'default' | 'icon' | 'sm' | 'xs' | 'lg'
    variant?: 'default' | 'destructive' | 'ghost' | 'link' | 'outline' | 'secondary'
  }
): ReactNode
export function Badge(props: ComponentProps<'span'> & { variant?: string; size?: string }): ReactNode
export function Codicon(props: { name: string; size?: number | string; spinning?: boolean; className?: string; style?: CSSProperties }): ReactNode
export function EmptyState(props: { title: string; description?: string; className?: string; icon?: ReactNode; action?: ReactNode }): ReactNode
export function ErrorState(props: { title: ReactNode; description?: ReactNode; icon?: ReactNode; className?: string; children?: ReactNode }): ReactNode
export function Skeleton(props: ComponentProps<'div'>): ReactNode
export type StatusTone = 'good' | 'muted' | 'warn' | 'bad'
export function StatusDot(props: ComponentProps<'span'> & { tone: StatusTone }): ReactNode
export interface SegmentedControlOption<T extends string> {
  id: T
  label: string
}
export function SegmentedControl<T extends string>(props: {
  options: readonly SegmentedControlOption<T>[]
  value: T
  onChange: (id: T) => void
  className?: string
  disabled?: boolean
}): ReactNode
export function DropdownMenu(props: { children?: ReactNode; open?: boolean; onOpenChange?: (open: boolean) => void }): ReactNode
export function DropdownMenuTrigger(props: { asChild?: boolean; children?: ReactNode }): ReactNode
export function DropdownMenuContent(props: { align?: 'center' | 'end' | 'start'; children?: ReactNode; style?: CSSProperties }): ReactNode
export function DropdownMenuItem(
  props: { children?: ReactNode; disabled?: boolean; onSelect?: (event: Event) => void; title?: string } & Record<`data-${string}`, string>
): ReactNode
export function DropdownMenuSeparator(): ReactNode
