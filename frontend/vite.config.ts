import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,   // 0.0.0.0 でリッスン（VM外からアクセス可能）
    proxy: {
      // IPv6解決を避けるため 127.0.0.1 を明示
      '/incidents': 'http://127.0.0.1:8080',
      '/topology':  'http://127.0.0.1:8080',
      '/ingest':    'http://127.0.0.1:8080',
      '/ws': {
        target: 'ws://127.0.0.1:8080',
        ws: true,
      },
    },
  },
})
