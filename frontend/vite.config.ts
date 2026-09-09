import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 本地开发时可开代理：npm run dev 后访问 http://localhost:5173
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
