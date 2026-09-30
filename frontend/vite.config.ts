import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import legacy from '@vitejs/plugin-legacy'
import path from 'path'

// 【离线兼容目标】无网环境的旧版 Chrome/Edge 90~110:
// - CSS 不走 Vite 处理, 由 scripts/build-css.mjs 预编译为 public/app.css,
//   index.html 以 <link> 直接加载（dev / build 同一机制, 不经 JS 注入样式）;
// - JS 经 esbuild 降级到 chrome90 语法, 构建时再由 plugin-legacy 注入
//   目标浏览器缺失的 core-js API 补丁; 个别 Web API（checkVisibility 等）
//   由 src/lib/legacy-shims.ts 手动垫片（dev 同样生效）。

/** public/app.css 由 CSS watch 进程重新生成后, 触发浏览器整页刷新 */
function appCssReload(): Plugin {
  const target = path.resolve(__dirname, 'public/app.css')
  return {
    name: 'app-css-reload',
    configureServer(server) {
      server.watcher.add(target)
      server.watcher.on('change', (file) => {
        if (path.resolve(file) === target) {
          server.ws.send({ type: 'full-reload' })
        }
      })
    },
  }
}

// 【前后端分离】构建产物输出到本目录下的 dist/（独立于后端 static/），
// 由前端自身的静态服务器（server.js）在独立端口对外提供，并把 /api 等接口
// 反向代理到后端服务（默认 http://127.0.0.1:8519）。用户访问的是【前端端口】。
// assetsDir 保持默认 "assets"。
export default defineConfig({
  plugins: [
    react(),
    appCssReload(),
    // 目标浏览器均支持 ES 模块, 无需 nomodule 遗留包; 仅按 targets 给
    // 现代产物注入缺失的 stdlib API 补丁（core-js）
    legacy({
      targets: ['chrome >= 90', 'edge >= 90'],
      renderLegacyChunks: false,
      modernPolyfills: true,
    }),
  ],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  // 旧浏览器兼容: dev 源码转译与依赖预构建都降级到 chrome90 语法
  esbuild: { target: 'chrome90' },
  optimizeDeps: {
    esbuildOptions: { target: 'chrome90' },
  },
  server: {
    host: '0.0.0.0',
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8519',
        changeOrigin: true,
      },
      '/docs': {
        target: 'http://127.0.0.1:8519',
        changeOrigin: true,
      },
      '/redoc': {
        target: 'http://127.0.0.1:8519',
        changeOrigin: true,
      },
      // 离线 Swagger UI / ReDoc 的本地静态资源（后端 static_vendor/swagger/）;
      // 不代理会被 Vite SPA 兜底返回 index.html, 导致 /docs 页报
      // "Unexpected token '<'" / "SwaggerUIBundle is not defined"
      '/swagger-assets': {
        target: 'http://127.0.0.1:8519',
        changeOrigin: true,
      },
      '/openapi.json': {
        target: 'http://127.0.0.1:8519',
        changeOrigin: true,
      },
    },
  },
  // `vite preview` 同样代理接口, 便于本地以接近生产的方式自前端端口验证
  preview: {
    port: 4173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8519', changeOrigin: true },
      '/docs': { target: 'http://127.0.0.1:8519', changeOrigin: true },
      '/redoc': { target: 'http://127.0.0.1:8519', changeOrigin: true },
      '/swagger-assets': { target: 'http://127.0.0.1:8519', changeOrigin: true },
      '/openapi.json': { target: 'http://127.0.0.1:8519', changeOrigin: true },
    },
  },
  build: {
    // 前后端分离: 输出到独立 dist/, 由 server.js 在独立端口提供服务
    outDir: path.resolve(__dirname, 'dist'),
    emptyOutDir: true,
    // 旧浏览器兼容: 现代产物语法降级到 chrome90
    target: ['chrome90'],
    // 离线内网工具, 单包体积可接受; 提高告警阈值避免噪音
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        // 将 React 运行时与 Markdown/高亮(体积较大)拆为独立 chunk, 利于缓存与并行加载
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          const seg = (id.split('node_modules/').pop() || '').replace(/^@/, '')
          if (/^(react|react-dom|scheduler)([/]|$)/.test(seg)) return 'react'
          if (/^(react-markdown|highlight\.js|remark-|rehype-|lowlight)/.test(seg)) return 'markdown'
          return undefined
        },
      },
    },
  },
})
