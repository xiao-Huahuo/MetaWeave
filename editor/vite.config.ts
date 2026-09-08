import { fileURLToPath, URL } from 'node:url'

import { defineConfig, type PluginOption } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import vueDevTools from 'vite-plugin-vue-devtools'

const EDITOR_CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https: http://127.0.0.1:8002 http://localhost:8002",
  "font-src 'self' data:",
  "connect-src 'self' http://127.0.0.1:8002 http://localhost:8002",
  "frame-src 'self' http://127.0.0.1:8002 http://localhost:8002",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
].join('; ')
const DEV_PROXY_TARGET = process.env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8002'
const DEV_SERVER_PORT = Number.parseInt(process.env.VITE_PORT || '5173', 10)

if (!Number.isInteger(DEV_SERVER_PORT) || DEV_SERVER_PORT < 1 || DEV_SERVER_PORT > 65_535) {
  throw new Error(`VITE_PORT must be a valid TCP port, received: ${process.env.VITE_PORT}`)
}

function productionCspPlugin(): PluginOption {
  return {
    name: 'agent-editor-production-csp',
    apply: 'build',
    transformIndexHtml(html) {
      return html.replace(
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        `<meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <meta http-equiv="Content-Security-Policy" content="${EDITOR_CSP}">`,
      )
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), vueJsx(), vueDevTools(), productionCspPlugin()],
  server: {
    host: '127.0.0.1',
    port: DEV_SERVER_PORT,
    strictPort: true,
    proxy: {
      '/agent': {
        target: DEV_PROXY_TARGET,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            /*
             * Agent SSE must stay uncompressed through the dev proxy.
             * If the proxy asks for compressed responses, chunks can be
             * buffered until the request completes, leaving the Agent panel
             * and observability cards spinning with no intermediate updates.
             */
            proxyReq.removeHeader('accept-encoding')
          })
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-cache'
            proxyRes.headers['x-accel-buffering'] = 'no'
            proxyRes.headers.connection = 'keep-alive'
          })
        },
      },
      '/git': DEV_PROXY_TARGET,
      '/knowledge': DEV_PROXY_TARGET,
      '/search': DEV_PROXY_TARGET,
      '/library': DEV_PROXY_TARGET,
      '/component-library': DEV_PROXY_TARGET,
      '/vault': DEV_PROXY_TARGET,
      '/favorites': DEV_PROXY_TARGET,
      '/scanner': DEV_PROXY_TARGET,
      '/privacy': DEV_PROXY_TARGET,
      '/feedback': DEV_PROXY_TARGET,
      '/smart-forms': DEV_PROXY_TARGET,
      '/literature-reading': DEV_PROXY_TARGET,
      '/structured-generation': DEV_PROXY_TARGET,
      '/sessions': DEV_PROXY_TARGET,
      '/settings': DEV_PROXY_TARGET,
      '/skills': DEV_PROXY_TARGET,
      '/downloads': DEV_PROXY_TARGET,
      '/visualizations': DEV_PROXY_TARGET,
      '/todo': DEV_PROXY_TARGET,
      '/automation': DEV_PROXY_TARGET,
      '/agent-queue': DEV_PROXY_TARGET,
      '/activity': DEV_PROXY_TARGET,
      '/debug': DEV_PROXY_TARGET,
      '/health': DEV_PROXY_TARGET,
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
