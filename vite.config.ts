// Desktop bundle: src/plugin.tsx -> desktop/plugin.js, one ESM file the Desktop loads uncompiled.
// A disk plugin may import only these three specifiers; everything else (three.js, our code) is
// bundled. src/plugin.tsx is written by S28; `npm run build` has nothing to build before then.
import { defineConfig } from 'vite'

export const HOST_PROVIDED = ['@hermes/plugin-sdk', 'react', 'react/jsx-runtime'] as const

export default defineConfig({
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  esbuild: { jsx: 'automatic', legalComments: 'eof' },
  build: {
    target: 'es2022',
    outDir: 'desktop',
    emptyOutDir: true,
    sourcemap: false,
    minify: 'esbuild',
    copyPublicDir: false,
    lib: {
      entry: 'src/plugin.tsx',
      formats: ['es'],
      fileName: () => 'plugin.js'
    },
    rollupOptions: {
      external: [...HOST_PROVIDED],
      output: { inlineDynamicImports: true }
    }
  }
})
