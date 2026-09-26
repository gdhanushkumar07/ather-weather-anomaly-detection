import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
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
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      }
    }
  }
});
