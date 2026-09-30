# web-heroui（HeroUI v3 前端）

基于 [HeroUI v3](https://heroui.com)（Tailwind CSS v4 + React Aria Components）重写的 RAG 系统前端。
功能与原 `frontend/` 完全一致（知识库管理、对话问答、API 文档三个页签），UI 采用 HeroUI 组件全面重绘，并支持暗色模式。

> 本目录是**独立前端工程**，不依赖、也不修改后端与其他代码。

---

## 一、前后端分离架构

后端（FastAPI）**只提供 API 与离线接口文档，不再托管前端产物**。前端构建产物由
**nginx（生产）**或 **`server.js` / Vite（开发、无 nginx 场景）**托管，并把接口反向代理到后端：

```
浏览器 ──访问──▶ 前端入口 (nginx:80 / server.js:3000 / vite:5174)
                     │  静态资源 (dist/)            直接返回
                     │  /api、/docs、/openapi.json、/swagger-assets
                     ▼  反向代理
               后端 (http://127.0.0.1:8519)
```

- **前端**只负责渲染界面，通过**相对路径** `/api/...` 调用接口。
- 托管方（nginx / server.js / Vite）把 `/api` 等接口**反向代理**到后端。
- 因此**用户只需访问前端入口**即可使用，无需关心后端端口；浏览器视角下前后端同源，无跨域问题。

| 场景 | 方式 | 默认端口 |
| --- | --- | --- |
| 后端 API | 后端自身启动（uvicorn/gunicorn） | `8519` |
| 前端开发（热更新） | `npm run dev` | `5174` |
| 前端预演（构建后本地验证） | `npm run preview` | `4173` |
| 前端生产（有 nginx，推荐） | `deploy/nginx.conf` 托管 `dist/` | `80` |
| 前端生产（无 nginx） | `npm run serve`（= `node server.js`） | `3000` |

> `server.js` 端口可用环境变量覆盖：`PORT=8080 node server.js`；
> 后端不在同机时指定：`BACKEND_URL=http://<后端IP>:8519 node server.js`。

---

## 二、快速开始

```bash
# 1. 安装依赖（需有 Node.js ≥ 18；建议 20+）
npm install

# 2. 开发模式（需后端已在 8519 启动）
npm run dev          # 打开 http://localhost:5174

# 3. 生产构建（输出到 ./dist）
npm run build

# 4. 启动生产服务（前后端分离, 访问前端端口）
npm run serve        # 打开 http://localhost:3000
```

---

## 三、离线部署（迁移到无外网服务器）

构建产物**完全自包含**，运行时不发起任何外网请求：

- 所有 JS / CSS 由 Vite 打包进 `dist/assets/`（HeroUI、Tailwind、React、图标等全部本地化）；
- **不使用任何 CDN**、不加载网络字体（使用操作系统自带字体栈，兼容中文）；
- `favicon` 以内联 `data:` URI 写在 `index.html`，不产生额外请求；
- 代码高亮样式（highlight.js）也随包本地引入。

迁移步骤：

1. 在**有网**的构建机上执行 `npm install && npm run build`，生成 `dist/`；
2. 将 `dist/` 目录拷贝到无外网服务器，并按下面任一方式托管。

**方式 A：nginx（生产推荐，项目已提供 `deploy/nginx.conf`）**
把 `dist/` 放到 nginx.conf 中 `root` 指向的路径（默认 `/opt/rag/web-heroui/dist`，按需修改），
该配置已处理好 SPA 兜底、`/assets/` 强缓存、`/api` SSE 关缓冲与长超时、离线文档反代等，随后
`nginx -t && nginx -s reload`，浏览器访问 `http://<服务器IP>/` 即可。

**方式 B：`server.js`（无 nginx 时的零依赖替代）**
额外拷贝 `server.js`（仅用 Node 内置模块），目标服务器仅需安装 Node.js：
```bash
PORT=3000 node server.js
# 若后端不在同一台机器: BACKEND_URL=http://<后端IP>:8519 node server.js
```
浏览器访问 `http://<服务器IP>:3000` 即可。

> 两种方式都要求后端已在 `8519` 提供 API。任意能托管静态文件并反代 `/api`、`/docs`、
> `/openapi.json`、`/swagger-assets` 的服务器均可替代 `server.js`。

---

## 四、目录结构

```
web-heroui/
├─ index.html            # 入口（内联 favicon, 无外链; <link> 直连 app.css）
├─ server.js             # 生产静态服务 + API 反向代理（零依赖）
├─ vite.config.ts        # Vite 配置（别名 @、接口代理、构建输出 dist/）
├─ package.json
├─ tsconfig*.json
└─ src/
   ├─ main.tsx           # 挂载入口
   ├─ App.tsx            # 外壳: HeroUI Tabs 三页签 + ToastProvider
   ├─ index.css          # 主题入口(@import @heroui/styles) + 自定义样式
   ├─ api/               # 接口封装（axios 信封解包、SSE 流式）
   ├─ stores/            # zustand 状态（chat/conversation/document/pipeline/settings）
   ├─ types/             # 接口类型定义
   ├─ hooks/useTheme.ts  # 明暗主题切换(.light/.dark)
   ├─ lib/               # 常量与工具
   ├─ pages/             # KnowledgePage / ChatPage / ApiPage
   └─ components/
      ├─ layout/SiteHeader.tsx     # 顶栏: 品牌 + 导航 + Docling 状态 + 主题 + 用户
      ├─ common/                   # Modal 封装、Checkbox/Switch 封装、空态、错误边界等
      ├─ knowledge/                # 文档表格、上传、详情、流水线、清除弹窗
      └─ chat/                     # 消息、检索详情、会话侧栏、查询设置侧栏
```

---

## 五、技术要点

- **HeroUI v3**：组合式组件（如 `Modal > ModalBackdrop > ModalContainer > ModalDialog`），
  本项目在 `components/common/` 中封装了 `AppModal`、`CheckboxField`、`SwitchField` 以降低样板代码。
- **通知**：使用 HeroUI 自带 `toast`（`toast.success / danger / warning / info`），替换原 `sonner`。
- **暗色模式**：`useTheme` 在 `<html>` 上切换 `.light` / `.dark`，HeroUI 主题变量随之切换。
- **状态与业务逻辑**：`api/`、`stores/`、`types/` 与原前端逐行一致，保证与后端行为完全对齐。
