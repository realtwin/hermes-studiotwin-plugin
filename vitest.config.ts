// TypeScript unit runner. Every slice command passes `--pool=forks --poolOptions.forks.singleFork=true`
// (DESIGN §9); the same serial settings are the defaults here so a bare `vitest run` matches.
// `@hermes/plugin-sdk` exists only inside Desktop, so tests resolve it to a small stub whose area
// constants are pinned to core by tests/scaffold/scaffold.test.ts. A test that needs different host
// behaviour replaces it with `vi.mock('@hermes/plugin-sdk', ...)`.
import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vitest/config'

export const SDK_STUB = fileURLToPath(new URL('./tests/scaffold/sdk-stub.ts', import.meta.url))

export default defineConfig({
  resolve: { alias: { '@hermes/plugin-sdk': SDK_STUB } },
  esbuild: { jsx: 'automatic' },
  test: {
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
    exclude: ['node_modules/**', 'tests/playwright/**', 'desktop/**'],
    environment: 'node',
    pool: 'forks',
    poolOptions: {
      // Worker memory cap is 4 GiB (BUILD-BRIEF rule 5); leave headroom for the runner itself.
      forks: { singleFork: true, execArgv: ['--max-old-space-size=3072'] }
    },
    fileParallelism: false,
    testTimeout: 30_000,
    restoreMocks: true,
    unstubEnvs: true,
    unstubGlobals: true
  }
})
