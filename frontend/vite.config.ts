import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        // Override to point a second dev server at another backend (e.g. an
        // isolated test instance): ATHER_API_TARGET=http://127.0.0.1:8021
        target: process.env.ATHER_API_TARGET || 'http://127.0.0.1:8001',
        changeOrigin: true,
      }
    }
  }
});
