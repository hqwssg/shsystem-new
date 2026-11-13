import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/prediction/',
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/prediction-api': {
        target: 'http://127.0.0.1:8086',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1600
  }
})
