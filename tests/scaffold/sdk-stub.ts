// Test-time stand-in for `@hermes/plugin-sdk` (vitest.config.ts aliases the specifier here).
// Area constants equal pinned core 088f657 and src/sdk.d.ts; scaffold.test.ts enforces both.
// Host members are inert and result-shaped: tests that exercise them use vi.mock or vi.spyOn.
import { createElement, type ReactNode } from 'react'

export { atom, computed } from 'nanostores'
export { useStore as useValue } from '@nanostores/react'
export { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

export const ROUTES_AREA = 'routes'
export const SIDEBAR_NAV_AREA = 'sidebar.nav'
export const STATUSBAR_AREAS = { left: 'statusBar.left', right: 'statusBar.right' } as const
export const PALETTE_AREA = 'palette'
export const KEYBINDS_AREA = 'keybinds'
export const COMPOSER_AREAS = {
  top: 'composer.top',
  bottom: 'composer.bottom',
  underside: 'composer.underside',
  leading: 'composer.leading',
  actions: 'composer.actions',
  middleware: 'composer.middleware',
  attachments: 'composer.attachments',
  microActions: 'composer.microActions',
  atCompletions: 'composer.atCompletions',
  modelPill: 'composer.modelPill',
  contextMenu: 'composer.contextMenu'
} as const
export const TRANSCRIPT_DIRECTIVE_AREA = 'transcript.directives'
export const TOOL_MEDIA_RENDERER_AREA = 'transcript.toolMedia'
export const SETTINGS_PLUGINS_AREA = 'settings.plugins'

export const host = {
  composer: {
    submit: (_sessionId: null | string, _text: string): boolean => false,
    insertText: async (_sessionId: null | string, _text: string): Promise<boolean> => false
  },
  navigate: (_path: string): void => {},
  notify: (_input: { kind?: string; message: string }): string => ''
}

type Props = Record<string, unknown> & { children?: ReactNode }
const element = (tag: string) => (props: Props) => createElement(tag, props)

export const Button = element('button')
export const Badge = element('span')
export const Skeleton = element('div')
export const StatusDot = element('span')
export const DropdownMenu = element('div')
export const DropdownMenuTrigger = element('div')
export const DropdownMenuContent = element('div')
export const DropdownMenuItem = element('div')
export const DropdownMenuSeparator = () => createElement('hr')
export const Codicon = ({ name }: { name: string }) => createElement('i', { 'data-codicon': name })
export const EmptyState = ({ title, description }: { title: string; description?: string }) =>
  createElement('div', { role: 'status' }, title, description ? ` ${description}` : '')
export const ErrorState = ({ title, description }: { title: ReactNode; description?: ReactNode }) =>
  createElement('div', { role: 'alert' }, title, description)
export const SegmentedControl = ({ options, value }: { options: readonly { id: string; label: string }[]; value: string }) =>
  createElement('div', { role: 'tablist' }, options.map(o => createElement('button', { key: o.id, 'aria-selected': o.id === value }, o.label)))
