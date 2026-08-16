import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,   // 0.0.0.0 でリッスン（VM外からアクセス可能）
    proxy: {
      // バックエンド API (http://localhost:8080) へ転送
      '/incidents': 'http://localhost:8080',
      '/topology':  'http://localhost:8080',
      '/ingest':    'http://localhost:8080',
      // WebSocket も同じポートへ
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
      },
    },
  },
})
