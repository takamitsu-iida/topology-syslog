import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          cytoscape: ['cytoscape', 'react-cytoscapejs'],
        },
      },
    },
  },
  server: {
    port: 3000,
    host: true,   // 0.0.0.0 でリッスン（VM外からアクセス可能）
    proxy: {
      // IPv6解決を避けるため 127.0.0.1 を明示
      // ブラウザのナビゲーション（Accept: text/html）はプロキシせず index.html を返す
      '/incidents': {
        target: 'http://127.0.0.1:8080',
        bypass(req) {
          if (req.headers.accept?.includes('text/html')) return '/index.html'
        },
      },
      '^/topology(?:/|$)': {
        target: 'http://127.0.0.1:8080',
        bypass(req) {
          if (req.headers.accept?.includes('text/html')) return '/index.html'
        },
      },
      '/node-states': 'http://127.0.0.1:8080',
      '/ingest':    'http://127.0.0.1:8080',
      '/filter':    'http://127.0.0.1:8080',
      '/knowledge': 'http://127.0.0.1:8080',
      '/raw-logs': {
        target: 'http://127.0.0.1:8080',
        bypass(req) {
          if (req.headers.accept?.includes('text/html')) return '/index.html'
        },
      },
      '/ws': {
        target: 'ws://127.0.0.1:8080',
        ws: true,
      },
    },
  },
})
