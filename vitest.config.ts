// Vitest 4 serial fork runner. `--pool=forks --maxWorkers=1` is the CLI equivalent.
// Keep one worker and the 3 GiB worker heap cap; do not expose a browser/API server.
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
    maxWorkers: 1,
    execArgv: ['--max-old-space-size=3072'],
    fileParallelism: false,
    testTimeout: 30_000,
    restoreMocks: true,
    unstubEnvs: true,
    unstubGlobals: true
  }
})
