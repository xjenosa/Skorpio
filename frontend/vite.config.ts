import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 3000,
    // Dev-only: allow trycloudflare.com tunnels for mobile-device testing
    // (the campus Wi-Fi blocks LAN device-to-device, so iPhone testing
    // goes over a Cloudflare quick-tunnel). Scoped to the trycloudflare
    // suffix so this isn't a blanket allow-all.
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
