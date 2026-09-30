#!/usr/bin/env node
/**
 * 离线 CSS 管线: 把 src/index.css（含 Tailwind v4 / @heroui/styles / 高亮主题）
 * 编译为单文件 public/app.css, 由 index.html 以 <link> 直接加载——
 * dev 与 build 共用同一机制, 不经过 JS 注入样式, 兼容无网环境与旧浏览器。
 *
 * 处理链（顺序敏感）:
 *   1. @tailwindcss/postcss          —— Tailwind v4 编译 + @import 解析
 *   2. postcss-nesting               —— 展平原生 CSS 嵌套（& 选择器, Chrome 120 才支持）
 *   3. postcss-oklab-function        —— 静态 oklch()/oklab() → rgb 回退（保留原声明）
 *   4. postcss-color-mix-function    —— 静态 color-mix() → 回退（保留原声明）
 *   5. postcss-legacy-color（自研）  —— color-mix(var() N%, transparent) 动态混色回退、
 *                                       主题变量 -rgb 三值、:has() 选择器列表拆分
 *   6. postcss-cascade-layers        —— @layer 级联层转为选择器优先级（Chrome 99 才支持
 *                                       @layer, 不支持的浏览器会整块丢弃层内规则）
 *   7. postcss-legacy-media（自研）  —— @media (width >= 40rem) 区间语法（Chrome 104+）
 *                                       降级为 min-/max-width（否则 sm/md 响应式规则
 *                                       整块被丢弃: 分页竖排、弹窗贴底等）
 *   8. postcss-legacy-transform（自研）—— calc(infinity)（rounded-full, Chrome 105+）
 *                                       与 translate/rotate/scale 独立 transform 属性
 *                                       （Chrome 104+）的旧浏览器回退, 含引用这些属性的
 *                                       transition/will-change（否则抽屉开合等过渡失效）
 *   9. autoprefixer                  —— 按 chrome>=90 补前缀
 *
 * 用法:
 *   node scripts/build-css.mjs            # 单次构建（npm run build 前自动执行）
 *   node scripts/build-css.mjs --watch    # 监听 src 变化自动重编译（npm run dev 并行运行）
 */
import { readFileSync, writeFileSync, mkdirSync, watch } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import postcss from 'postcss'
import tailwindcss from '@tailwindcss/postcss'
import postcssNesting from 'postcss-nesting'
import postcssOklabFunction from '@csstools/postcss-oklab-function'
import postcssColorMixFunction from '@csstools/postcss-color-mix-function'
import postcssCascadeLayers from '@csstools/postcss-cascade-layers'
import autoprefixer from 'autoprefixer'
import postcssLegacyColor from './postcss-legacy-color.mjs'
import postcssLegacyMedia from './postcss-legacy-media.mjs'
import postcssLegacyTransform from './postcss-legacy-transform.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const INPUT = path.join(ROOT, 'src', 'index.css')
const OUTPUT = path.join(ROOT, 'public', 'app.css')

// 插件实例复用: watch 模式下 Tailwind 内部缓存可跨次构建生效
const processor = postcss([
  tailwindcss(),
  postcssNesting(),
  postcssOklabFunction({ preserve: true }),
  postcssColorMixFunction({ preserve: true }),
  postcssLegacyColor(),
  postcssCascadeLayers(),
  postcssLegacyMedia(),
  postcssLegacyTransform(),
  autoprefixer({ overrideBrowserslist: ['chrome >= 90'] }),
])

let building = false
async function build() {
  if (building) return
  building = true
  const t0 = Date.now()
  try {
    const css = readFileSync(INPUT, 'utf-8')
    const result = await processor.process(css, { from: INPUT, to: OUTPUT })
    for (const w of result.warnings()) console.warn('[css] 警告:', w.toString())
    mkdirSync(path.dirname(OUTPUT), { recursive: true })
    writeFileSync(OUTPUT, result.css)
    console.log(`[css] public/app.css 已生成 (${(result.css.length / 1024).toFixed(0)} KB, ${Date.now() - t0}ms)`)
  } catch (e) {
    console.error('[css] 构建失败:', e.message)
    if (!process.argv.includes('--watch')) process.exitCode = 1
  } finally {
    building = false
  }
}

const isWatch = process.argv.includes('--watch')
await build()

if (isWatch) {
  let timer = null
  const schedule = (filename) => {
    // Tailwind 扫描源码中的类名, 因此 tsx/ts 变化也需重编译
    if (filename && !/\.(css|tsx?|jsx?)$/i.test(filename)) return
    clearTimeout(timer)
    timer = setTimeout(build, 200)
  }
  watch(path.join(ROOT, 'src'), { recursive: true }, (_event, filename) => schedule(filename))
  console.log('[css] watch 模式已启动: src 变化时自动重编译 public/app.css')
}
