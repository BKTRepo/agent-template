#!/usr/bin/env node
/**
 * 智能服务调度集生产静态服务器与反向代理。
 *
 * 【前后端分离】
 *   - 本进程在【前端端口】对外提供已构建的前端静态资源（dist/）。
 *   - 同时把接口路径（/api、/docs、/redoc、/openapi.json、/swagger-assets）
 *     反向代理到后端服务（默认 http://127.0.0.1:8519），从而与后端解耦。
 *   - 用户只需访问【前端端口】即可使用，无需直接访问后端端口。
 *
 * 用法:
 *   npm run build          # 先生成 dist/
 *   node server.js         # 默认端口 3000
 *   PORT=8080 node server.js
 *   BACKEND_URL=http://10.0.0.5:8519 node server.js   # 后端不在本机时指定
 */
import http from 'node:http'
import https from 'node:https'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DIST = path.join(__dirname, 'dist')
const PORT = Number(process.env.PORT || 3000)
const BACKEND = process.env.SKILL_BACKEND_TARGET || process.env.BACKEND_URL || 'http://127.0.0.1:8519'
const backend = new URL(BACKEND)
const backendRequest = backend.protocol === 'https:' ? https.request : http.request
const realtimeBackend = new URL(process.env.REALTIME_DEBUG_TARGET || BACKEND)

// 需要反向代理到后端的路径前缀
const PROXY_PREFIXES = ['/api', '/base', '/skills', '/knowledge-bases', '/health', '/docs', '/redoc', '/openapi.json', '/swagger-assets', '/realtime-test-case-gen']

// 不应逐跳转发的请求头
const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade', 'host', 'content-length',
])

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.otf': 'font/otf',
  '.txt': 'text/plain; charset=utf-8',
  '.pdf': 'application/pdf',
}

function buildProxyHeaders(req, target, realtime) {
  const headers = {}
  for (const [key, value] of Object.entries(req.headers)) {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers[key] = value
  }
  headers.host = target.host
  if (realtime && process.env.REALTIME_DEBUG_TOKEN) headers.token = process.env.REALTIME_DEBUG_TOKEN
  if (!realtime && (process.env.SKILL_API_TOKEN || process.env.REALTIME_DEBUG_TOKEN)) {
    headers.token = process.env.SKILL_API_TOKEN || process.env.REALTIME_DEBUG_TOKEN
  }
  return headers
}

// 反向代理，保留流式响应。
function proxy(req, res) {
  const realtime = req.url.split('?')[0].startsWith('/realtime-test-case-gen/')
  const target = realtime ? realtimeBackend : backend
  const request = realtime ? (target.protocol === 'https:' ? https.request : http.request) : backendRequest
  const proxyReq = request(
    {
      hostname: target.hostname,
      port: target.port || (target.protocol === 'https:' ? 443 : 80),
      path: req.url,
      method: req.method,
      headers: buildProxyHeaders(req, target, realtime),
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode || 502, proxyRes.headers)
      proxyRes.pipe(res)
    },
  )
  proxyReq.on('error', (err) => {
    if (!res.headersSent) {
      res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
    }
    res.end(JSON.stringify({ error: 'Bad Gateway', detail: String(err?.message || err) }))
  })
  req.pipe(proxyReq)
}

function sendFile(res, filePath) {
  const ext = path.extname(filePath).toLowerCase()
  const stream = fs.createReadStream(filePath)
  stream.on('open', () => {
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' })
    stream.pipe(res)
  })
  stream.on('error', () => {
    res.writeHead(404)
    res.end('Not Found')
  })
}

// SPA 兜底：未命中的非接口路径一律返回 index.html（前端路由/刷新友好）
function spaFallback(res) {
  const index = path.join(DIST, 'index.html')
  if (fs.existsSync(index)) {
    sendFile(res, index)
  } else {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
    res.end('未找到 dist/index.html，请先执行 `npm run build` 生成构建产物。')
  }
}

const server = http.createServer((req, res) => {
  let pathname
  try {
    pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname)
  } catch {
    res.writeHead(400)
    return res.end('Bad Request')
  }

  // 接口路径 → 反向代理到后端
  if (PROXY_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + '/'))) {
    return proxy(req, res)
  }

  // 静态资源
  const rel = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '')
  const filePath = path.normalize(path.join(DIST, rel))
  // 防止目录穿越
  if (!filePath.startsWith(DIST)) {
    res.writeHead(403)
    return res.end('Forbidden')
  }

  fs.stat(filePath, (err, stat) => {
    if (!err && stat.isDirectory()) return sendFile(res, path.join(filePath, 'index.html'))
    if (!err && stat.isFile()) return sendFile(res, filePath)
    return spaFallback(res)
  })
})

// Skill 调试可能耗时较长，保留长连接。
server.requestTimeout = 0
server.headersTimeout = 0
server.keepAliveTimeout = 65_000

server.listen(PORT, () => {
  const line = '-'.repeat(56)
  console.log(line)
  console.log('[znfwdd] 前端静态资源目录 :', DIST)
  console.log(`[znfwdd] 前端访问地址     : http://localhost:${PORT}`)
  console.log(`[znfwdd] 后端接口代理     : ${PROXY_PREFIXES.join(', ')}  ->  ${BACKEND}`)
  console.log(line)
})
