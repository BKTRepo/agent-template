#!/usr/bin/env node
/**
 * 开发入口: 并行运行「CSS watch 编译」与「Vite dev server」。
 * 直接用当前 Node 可执行文件拉起两个子进程（不经 npm/shell, 离线可用）:
 * - CSS 由 scripts/build-css.mjs --watch 增量编译到 public/app.css;
 * - Vite 侧插件检测到 app.css 变化后自动整页刷新。
 *
 * 注意: watch 子进程在启动时加载 scripts/ 下的 postcss 插件并常驻内存——
 * 修改 postcss-legacy-*.mjs 等编译脚本后必须重启本入口（Ctrl+C 再 npm run dev）,
 * 否则旧进程仍按旧插件增量编译, 会把新修复覆盖回 public/app.css
 * （表现为"手动 build 后正常、改个 src 文件又复现"）。
 */
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const NODE = process.execPath

const css = spawn(
  NODE,
  [path.join(ROOT, 'scripts/build-css.mjs'), '--watch'],
  { cwd: ROOT, stdio: 'inherit' },
)
const vite = spawn(
  NODE,
  [path.join(ROOT, 'node_modules/vite/bin/vite.js')],
  { cwd: ROOT, stdio: 'inherit' },
)

let shuttingDown = false
function shutdown(code) {
  if (shuttingDown) return
  shuttingDown = true
  css.kill()
  vite.kill()
  process.exit(code ?? 0)
}

css.on('exit', (code) => {
  console.error(`[dev] CSS 编译进程退出 (${code})`)
  shutdown(code)
})
vite.on('exit', (code) => shutdown(code))
process.on('SIGINT', () => shutdown(0))
process.on('SIGTERM', () => shutdown(0))
