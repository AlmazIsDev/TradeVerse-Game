import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 20300,
    allowedHosts: ['tradeverse.weissx.net'],
    proxy: {
      '/api': {
        target: 'http://localhost:20301',
        changeOrigin: true,
      },
    },
  },
  // Прод-режим: `vite preview` раздаёт собранную папку dist.
  // Опции server сюда НЕ наследуются — дублируем host/port/allowedHosts.
  preview: {
    host: '0.0.0.0',
    port: 20300,
    allowedHosts: ['tradeverse.weissx.net'],
  },
})
