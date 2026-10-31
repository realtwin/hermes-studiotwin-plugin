// S01 TypeScript scaffold: locked serial Vitest runner, SDK declarations pinned to core, build config,
// and an import graph with no future Desktop leaf. Imports only node built-ins, vitest, vite and the
// test-only SDK stub (through the `@hermes/plugin-sdk` alias); nothing under src/ is loaded.
import { execFileSync } from 'node:child_process'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import * as sdk from '@hermes/plugin-sdk'
import { describe, expect, it } from 'vitest'

import viteConfig, { HOST_PROVIDED } from '../../vite.config.ts'
import vitestConfig, { SDK_STUB } from '../../vitest.config.ts'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const CORE = '/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent/apps/desktop/src'
const read = (path: string) => readFileSync(path, 'utf8')
const json = (path: string) => JSON.parse(read(join(ROOT, path)))

describe('locked runner', () => {
  it('is the pinned Vitest 3.2.7 in a single forked worker', () => {
    // 3.x is required: Vitest 4.1.12 rejects `--poolOptions` ("Unknown option"), which every §9 command passes.
    expect(json('node_modules/vitest/package.json').version).toBe('3.2.7')
    expect(json('package.json').devDependencies.vitest).toBe('3.2.7')
    expect(typeof process.send).toBe('function') // forks pool: a child_process with an IPC channel
    expect(process.env.VITEST_POOL_ID).toBe('1') // singleFork: exactly one worker
    const forks = vitestConfig.test?.poolOptions?.forks
    expect(vitestConfig.test?.pool).toBe('forks')
    expect(forks?.singleFork).toBe(true)
    expect(vitestConfig.test?.fileParallelism).toBe(false)
  })

  it('runs on the supported Node line', () => {
    expect(json('package.json').engines.node).toBe('>=24.0.0')
    expect(Number(process.versions.node.split('.')[0])).toBeGreaterThanOrEqual(24)
  })

  it('has no Jest-only runner or flag anywhere in the project manifest', () => {
    const pkg = read(join(ROOT, 'package.json'))
    expect(pkg).not.toMatch(/jest|runInBand/i)
  })
})

describe('@hermes/plugin-sdk declarations', () => {
  // Pinned core 088f657 source of each area constant.
  const CORE_AREAS: Array<[name: string, file: string, pattern: RegExp]> = [
    ['ROUTES_AREA', 'app/routes.ts', /export const ROUTES_AREA = '([^']+)'/],
    ['SIDEBAR_NAV_AREA', 'app/routes.ts', /export const SIDEBAR_NAV_AREA = '([^']+)'/],
    ['PALETTE_AREA', 'app/command-palette/contrib.ts', /export const PALETTE_AREA = '([^']+)'/],
    ['KEYBINDS_AREA', 'lib/keybinds/actions.ts', /export const KEYBINDS_AREA = '([^']+)'/],
    ['TRANSCRIPT_DIRECTIVE_AREA', 'lib/transcript-directives.ts', /export const TRANSCRIPT_DIRECTIVE_AREA = '([^']+)'/],
    ['TOOL_MEDIA_RENDERER_AREA', 'lib/tool-media-renderers.ts', /export const TOOL_MEDIA_RENDERER_AREA = '([^']+)'/],
    ['SETTINGS_PLUGINS_AREA', 'contrib/settings-pages.ts', /export const SETTINGS_PLUGINS_AREA = '([^']+)'/]
  ]
  const declarations = read(join(ROOT, 'src/sdk.d.ts'))
  const coreAvailable = existsSync(CORE)

  it.each(CORE_AREAS)('%s matches pinned core, the declaration and the test stub', (name, file, pattern) => {
    const declared = new RegExp(`export const ${name}: '([^']+)'`).exec(declarations)?.[1]
    expect(declared, `${name} declared in src/sdk.d.ts`).toBeDefined()
    expect((sdk as Record<string, unknown>)[name]).toBe(declared)
    if (coreAvailable) {
      expect(pattern.exec(read(join(CORE, file)))?.[1]).toBe(declared)
    }
  })

  it('pins the grouped areas to core', () => {
    expect(sdk.STATUSBAR_AREAS).toEqual({ left: 'statusBar.left', right: 'statusBar.right' })
    if (coreAvailable) {
      expect(read(join(CORE, 'sdk/areas.ts'))).toContain(
        "export const STATUSBAR_AREAS = { left: 'statusBar.left', right: 'statusBar.right' } as const"
      )
      const block = /export const COMPOSER_AREAS = \{([^}]+)\}/.exec(read(join(CORE, 'app/chat/composer/contrib.ts')))?.[1] ?? ''
      const core = Object.fromEntries([...block.matchAll(/(\w+): '([^']+)'/g)].map(m => [m[1], m[2]]))
      expect(sdk.COMPOSER_AREAS).toEqual(core)
      for (const [key, value] of Object.entries(core)) {
        expect(declarations).toContain(`readonly ${key}: '${value}'`)
      }
    }
  })

  it('feature-detects every seam newer than the oldest supported Desktop', () => {
    for (const member of ['composer?:', 'registerSettingsPage?:', 'setInterval?:', 'socket?:', 'writeClipboard?:']) {
      expect(declarations).toContain(member)
    }
    expect(declarations).toContain("TOOL_MEDIA_RENDERER_AREA: 'transcript.toolMedia' | undefined")
    expect(declarations).toContain('submit: (sessionId: null | string, text: string) => boolean')
  })

  it('typechecks the declarations, configs and the SDK usage contract with the locked TypeScript', () => {
    const tsc = join(ROOT, 'node_modules/typescript/bin/tsc')
    expect(json('node_modules/typescript/package.json').version).toBe('5.9.2')
    // Throws with tsc's diagnostics on any type error.
    execFileSync(process.execPath, [tsc, '--noEmit', '-p', join(ROOT, 'tsconfig.json')], { cwd: ROOT, stdio: 'pipe' })
  }, 120_000)
})

describe('build and test config', () => {
  it('bundles one ESM desktop/plugin.js with only the host-provided specifiers external', () => {
    expect([...HOST_PROVIDED]).toEqual(['@hermes/plugin-sdk', 'react', 'react/jsx-runtime'])
    const build = viteConfig.build!
    expect(build.outDir).toBe('desktop')
    expect(build.lib && build.lib.formats).toEqual(['es'])
    expect(build.lib && build.lib.entry).toBe('src/plugin.tsx')
    expect(build.rollupOptions?.external).toEqual([...HOST_PROVIDED])
    expect(json('package.json').scripts.build).toBe('vite build')
  })

  it('resolves @hermes/plugin-sdk to the test stub only under Vitest', () => {
    expect(relative(ROOT, SDK_STUB)).toBe('tests/scaffold/sdk-stub.ts')
    const tsconfig = json('tsconfig.json')
    expect(tsconfig.compilerOptions.paths['@hermes/plugin-sdk']).toEqual(['./src/sdk.d.ts'])
  })
})

// Every static/dynamic import specifier in a TypeScript source (type-only imports included).
const SPECIFIER = /(?:^|\n)\s*(?:import|export)\s[^;]*?from\s+'([^']+)'|import\(\s*'([^']+)'\s*\)/g
const specifiers = (source: string) => [...source.matchAll(SPECIFIER)].map(m => m[1] ?? m[2])

/** Repository files reachable from `entries` through relative imports and the SDK alias. */
export function localImportGraph(entries: string[]): Set<string> {
  const seen = new Set<string>()
  const queue = [...entries]
  while (queue.length) {
    const file = queue.pop()!
    if (seen.has(file)) continue
    seen.add(file) // recorded even when absent, so a future-leaf import shows up in the graph diff
    if (!existsSync(file)) continue
    for (const spec of specifiers(read(file))) {
      if (spec === '@hermes/plugin-sdk') queue.push(SDK_STUB)
      else if (spec.startsWith('.')) queue.push(resolve(dirname(file), spec))
    }
  }
  return seen
}

describe('import isolation', () => {
  const scaffoldDir = join(ROOT, 'tests/scaffold')
  const PACKAGES = new Set(['node:child_process', 'node:fs', 'node:path', 'node:url', 'vitest', 'vitest/config', 'vite',
    '@hermes/plugin-sdk', 'react', 'nanostores', '@nanostores/react', '@tanstack/react-query'])

  it('the scaffold test graph reaches only scaffold and config files, never src/', () => {
    const tsFiles = readdirSync(scaffoldDir).filter(f => f.endsWith('.ts')).sort()
    expect(tsFiles).toEqual(['scaffold.test.ts', 'sdk-contract.ts', 'sdk-stub.ts'])
    const graph = [...localImportGraph(tsFiles.map(f => join(scaffoldDir, f)))].map(f => relative(ROOT, f)).sort()
    expect(graph).toEqual([
      'tests/scaffold/scaffold.test.ts', 'tests/scaffold/sdk-contract.ts', 'tests/scaffold/sdk-stub.ts',
      'vite.config.ts', 'vitest.config.ts'
    ])
    for (const file of graph) {
      for (const spec of specifiers(read(join(ROOT, file)))) {
        if (!spec.startsWith('.')) expect(PACKAGES, `${file} imports ${spec}`).toContain(spec)
      }
    }
  })

  it('src/ holds only the SDK declaration file at S01', () => {
    expect(readdirSync(join(ROOT, 'src')).filter(name => !['cards', 'viewers', 'pages', 'chrome'].includes(name))).toEqual(['sdk.d.ts'])
  })

  it('the graph walker does catch a future-leaf import (self-check)', () => {
    // Built at runtime so this file's own text holds no import of src/ for the walker to follow.
    const leaf = ['..', '..', 'src', 'plugin.tsx'].join('/')
    const registry = ['..', '..', 'src', 'registry.ts'].join('/')
    const FROM = ['fr', 'om'].join('')
    const fixture = ['import { x } ', FROM, ` '${leaf}'\nconst y = await import`, `('${registry}')`].join('')
    expect(specifiers(fixture)).toEqual([leaf, registry])
    expect(specifiers("import type { A } from '@hermes/plugin-sdk'")).toEqual(['@hermes/plugin-sdk'])
  })

  it('the graph walker follows a future-leaf import into src/ (self-check)', async () => {
    const { mkdtempSync, writeFileSync } = await import('node:fs')
    const dir = mkdtempSync(join(process.env.TMPDIR ?? '/tmp', 'st-graph-'))
    const entry = join(dir, 'probe.test.ts')
    writeFileSync(entry, ['import { x } ', ['fr', 'om'].join(''), ` '${['.', 'src', 'leaf.ts'].join('/')}'\n`].join(''))
    expect([...localImportGraph([entry])]).toContain(join(dir, 'src', 'leaf.ts'))
  })
})
