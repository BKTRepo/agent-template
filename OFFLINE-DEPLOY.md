# 无网环境部署说明（Chrome/Edge 90~110 兼容）

本项目前端已按「无网 + 旧版浏览器（Chrome/Edge 90~110）」目标改造，
dev 与 build 两种模式均不依赖外网，样式与脚本均做了降级兼容。

## 一、迁移到无网机器

1. 在联网机器上确认依赖完整：`npm install`（当前 node_modules 即为完整依赖）。
2. 整体复制 `web-heroui/` 目录到无网机器，**必须包含 `node_modules/`**。
3. 平台要求：`node_modules` 内含平台相关二进制（esbuild、tailwindcss oxide、
   lightningcss 等），联网机器与无网机器需为**相同操作系统与 CPU 架构**
   （当前为 Windows x64）。跨平台时需在有网环境按目标平台重新 `npm install`
   后再拷贝。
4. 无网机器只需安装 Node.js（≥ 18，与开发机大版本一致即可），无需 npm 联网。

## 二、运行方式

### 开发模式（npm run dev）
```bash
npm run dev
```
并行启动两个进程（见 `scripts/dev.mjs`）：
- `scripts/build-css.mjs --watch`：监听 `src/` 变化，把样式增量编译到 `public/app.css`；
- Vite dev server：提供页面与接口代理（/api → 127.0.0.1:8519）。

**样式加载方式**：`index.html` 通过 `<link rel="stylesheet" href="/app.css">`
直接加载本地 CSS 文件，**不经过 JS 注入**。修改 CSS/组件类名后，watch 进程自动
重编译 app.css，Vite 检测到文件变化自动整页刷新。

### 生产模式
```bash
npm run build      # tsc 类型检查 + CSS 编译 + Vite 构建（含 chrome99 降级与 polyfill）
node server.js     # 零依赖静态服务器 + /api 反向代理（默认端口 3000）
```

## 三、兼容机制说明

### CSS（目标 Chrome/Edge 90+）
样式由 `scripts/build-css.mjs` 的 PostCSS 管线统一编译（dev/build 共用）：

| 步骤 | 插件 | 作用 |
|---|---|---|
| 1 | @tailwindcss/postcss | Tailwind v4 编译、@import 解析（@heroui/styles 等全部本地） |
| 2 | postcss-nesting | 展平原生 CSS 嵌套（`&` 选择器 Chrome 120 才支持） |
| 3 | @csstools/postcss-oklab-function | oklch()/oklab() → rgb 回退（保留原声明供现代浏览器） |
| 4 | @csstools/postcss-color-mix-function | 静态 color-mix() → 回退 |
| 5 | scripts/postcss-legacy-color.mjs（自研） | ① color-mix(var(--x) N%, transparent) → rgb(var(--x-rgb) / N%) 动态回退（回退规则插在 `@supports (color: color-mix(...))` 块**之前**，否则旧浏览器整块跳过只能吃到块外的实色回退，呈现为高反差纯色）；② 为主题变量补发 -rgb 三值；③ 拆分含 :has() 的选择器列表（Chrome 105 以下整条规则会被废弃，拆分后等价属性选择器版本可命中） |
| 6 | @csstools/postcss-cascade-layers | 剥离 `@layer` 级联层（Chrome 99 才支持；不支持时层内规则会被整块丢弃），转为 `:not(#\#)` 重复提升选择器优先级来编码层级顺序，产物约 +350KB |
| 7 | scripts/postcss-legacy-media.mjs（自研） | Tailwind v4 断点输出的 MQ4 区间语法 `@media (width >= 40rem)`（Chrome 104 才支持，旧浏览器整块丢弃 → 分页竖排、弹窗丢失 my-auto 贴底）→ 降级为 `(min-width: 40rem)` 等传统写法 |
| 8 | scripts/postcss-legacy-transform.mjs（自研） | ① `calc(infinity * 1px)`（Tailwind v4 的 rounded-full 实现，infinity Chrome 105 才支持，旧浏览器整条 border-radius 被丢弃 → 圆角变直角）→ 前置 `9999px` 回退；② `translate/rotate/scale` 独立 transform 属性（Chrome 104 才支持）→ 普通规则以 `@supports not (translate: 0 0)` 包裹等价 `transform` 回退（现代浏览器条件为假不受影响），@keyframes 内直接改写为 `transform` |
| 9 | autoprefixer | 按 chrome>=90 补前缀 |

字体：Space Grotesk 已本地化到 `public/fonts/`；favicon 内联在 index.html。
全链路无任何外网请求。

### JS（目标 Chrome/Edge 90+）
- Vite 配置 `esbuild.target` / `optimizeDeps.esbuildOptions.target` /
  `build.target` 均为 `chrome90`，语法层面全部降级（dev 预构建依赖同样生效）；
- `@vitejs/plugin-legacy`（`renderLegacyChunks: false` + `modernPolyfills: true`）
  按 targets 向构建产物注入缺失的 stdlib API 补丁（core-js，见 dist 的
  polyfills-*.js，首个加载）；
- `src/lib/legacy-shims.ts`（main.tsx 首行 import，dev/build 均生效）：
  手垫 `Object.hasOwn`（ES2022，Chrome 93+；lowlight/rehype-highlight、
  react-markdown、framer-motion、react-dom dev 构建均调用，缺失时打开
  聊天记录渲染 Markdown 即崩溃——build 产物 core-js 已含，dev 不注入，
  故手动兜底），以及 core-js 不覆盖的 Web API ——
  `Element.prototype.checkVisibility`（Chrome 105+，react-aria 使用）与
  `structuredClone`（Chrome 98+，markdown 链路使用）。

### 运行时主题切换
主题色 accent 以 hex 表示（`src/lib/theme.ts`），`useTheme` 同时写入
`--accent` 与 `--accent-rgb` 两个变量；明暗主题由 HeroUI 主题变量的
`.light/.dark` 静态定义切换（均已带 rgb 回退），旧浏览器同样可用。

## 四、已知降级与限制（Chrome 90~110）

1. **部分半透明混色退化为实色**：HeroUI/Tailwind 自带 `@supports (color:
   color-mix(...))` 包裹的声明，旧浏览器整块跳过。自研管线已把能精确换算的
   （与 transparent 混合）以同选择器规则插到 @supports 块之前，旧浏览器得到
   精确的 rgb 三值半透明回退（如行悬停 4% 前景色）；剩余少量（如两种变量色
   互混）为实色近似，视觉差异轻微。
2. **Chrome 90~104 上 :has() 规则不生效**：管线已把「:has() + 等价属性选择器」
   的混合列表拆成两条规则，绝大多数交互样式有等价兜底；个别仅有 :has()
   形式的装饰规则（如个别圆角细节）在该版本区间不生效，Chrome 105+ 正常。
3. **accent-color（93+）/ scrollbar-width（121+）**等纯外观属性在更低版本
   被忽略，回退为浏览器默认外观，无功能影响。
4. **text-wrap: balance/pretty 等渐进增强特性**在旧浏览器不生效（无副作用）。
5. **dev 模式不注入 core-js 补丁**（仅 build 注入）。若 dev 下旧浏览器报
   某个新 API 未定义，请记录 API 名：属 ECMAScript 标准 API 时在
   `src/main.tsx` 顶部 `import 'core-js/actual/<api>'`；属 DOM/Web API 时
   在 `src/lib/legacy-shims.ts` 内补一段垫片。
6. 生产构建的 polyfills 按「chrome >= 90」计算，若实际浏览器低于 90，
   需同步下调 vite.config.ts 与 build-css.mjs 中的 targets 并重新验证。

## 五、验证清单（迁移后自检）

- [ ] `npm run dev` 后页面样式正常（打开 DevTools Network 应无任何外网请求）
- [ ] 切换明暗主题、切换主题色正常
- [ ] `npm run build && node server.js` 生产模式页面正常
- [ ] 文档上传/解析、问答、流式输出、会话搜索各功能可用
