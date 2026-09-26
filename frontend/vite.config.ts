import { defineConfig, Plugin } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * `vite preview` gzips responses. On proxied API responses that compression
 * layer intermittently stalls large bodies (the ~330 KB /api/network/state
 * snapshot stopped at 261,120 bytes in 8 of 12 tries; the 1 MB station list
 * failed most tries) and holds back the live-event stream (/api/stream),
 * leaving the dashboard on "CONNECTING". Without Accept-Encoding every
 * download completed. Removing it from /api requests BEFORE the compression
 * middleware runs (configurePreviewServer pre-hook) serves the API
 * uncompressed; static assets are still compressed. Dev mode is unaffected.
 */
const apiWithoutPreviewCompression = (): Plugin => ({
  name: 'ather-api-without-preview-compression',
  configurePreviewServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (req.url?.startsWith('/api')) delete req.headers['accept-encoding'];
      next();
    });
  },
});

export default defineConfig({
  plugins: [react(), apiWithoutPreviewCompression()],
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      }
    }
  },
  // `npm run build && npm run preview` serves the production build with the
  // same backend proxy (useful for demos: no on-the-fly dependency optimization).
  preview: {
    port: 3000,
    host: true,
    // Allow access through Tailscale Serve/Funnel (https://<machine>.<tailnet>.ts.net).
    allowedHosts: ['.ts.net'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      }
    }
  }
});
