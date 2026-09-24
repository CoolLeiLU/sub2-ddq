import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The console is served by the Python service at /guardian/, so the build
// emits relative asset URLs and lands directly in the packaged static folder.
export default defineConfig({
  plugins: [react()],
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
