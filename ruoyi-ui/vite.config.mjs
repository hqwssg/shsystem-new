import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import compression from 'vite-plugin-compression'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), 'VUE_APP_'), ...process.env }
  const carbonApi = env.VUE_APP_CARBON_API || '/carbon-api'
  const mainApi = env.VUE_APP_BASE_API || (mode === 'development' ? '/dev-api' : '/prod-api')
  return {
    base: '/', envPrefix: 'VUE_APP_',
    plugins: [vue(), vueJsx(), compression()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }, extensions: ['.mjs', '.js', '.jsx', '.ts', '.tsx', '.json', '.vue'] },
    server: { host: '127.0.0.1', port: Number(env.port || env.npm_config_port || 80), strictPort: true, open: env.VUE_APP_OPEN_BROWSER !== 'false',
      proxy: {
        [carbonApi]: { target: env.VUE_APP_CARBON_TARGET || 'http://localhost:8082', changeOrigin: true, rewrite: p => p.replace(new RegExp('^'+carbonApi), '/api') },
        [mainApi]: { target: env.VUE_APP_MAIN_TARGET || 'http://localhost:8081', changeOrigin: true, rewrite: p => p.replace(new RegExp('^'+mainApi), '') }
      }
    },
    optimizeDeps: { esbuildOptions: { loader: { '.js': 'jsx' } } },
    build: { outDir: 'dist', assetsDir: 'static', sourcemap: false },
  }
})
