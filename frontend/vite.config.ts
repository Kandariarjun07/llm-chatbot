import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        // Explicitly configure the proxy to NOT buffer streaming
        // responses (SSE). http-proxy pipes by default, but we add
        // the configure hook to preserve chunked-transfer headers.
        configure: (proxy, _options) => {
          proxy.on('proxyRes', (proxyRes, _req, _res) => {
            // Ensure Content-Type and Transfer-Encoding headers from
            // the backend are forwarded intact so the browser treats
            // the response as a true stream rather than buffering.
            const ct = proxyRes.headers['content-type']
            if (ct && ct.includes('text/event-stream')) {
              proxyRes.headers['x-proxy-streaming'] = 'true'
            }
          })
        },
      },
    },
  },
})
