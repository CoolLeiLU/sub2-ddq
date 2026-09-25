import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

import antdStaticStyles from './plugin-antd-static-styles'

// The console is served by the Python service at /guardian/, so the build
// emits relative asset URLs and lands directly in the packaged static folder.
//
// antdStaticStyles runs first: the service sends `style-src 'self'`, which
// blocks the <style> tags antd injects at runtime, so its component CSS has to
// exist as a real stylesheet before the bundle references it.
export default defineConfig({
  plugins: [antdStaticStyles(), react()],
  base: '/guardian/',
  build: {
    outDir: '../src/sub2api_mcp/guardian/static',
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:5310',
      '/guardian': 'http://127.0.0.1:5310',
    },
  },
})
