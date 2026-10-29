import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// @types/node is intentionally not a dependency; this config runs under
// node, so declare only the env access it needs.
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      // R-06: the isolated Playwright config sets AGENTBOUNDARY_E2E_API_PORT
      // so the test frontend proxies /api at the TEST backend. Normal dev
      // (env unset) keeps the demo backend on :8000, unchanged.
      '/api': {
        target: `http://127.0.0.1:${process.env.AGENTBOUNDARY_E2E_API_PORT ?? 8000}`,
        changeOrigin: true,
      },
    },
  },
});
