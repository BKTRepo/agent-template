# 2026-10-21 真实运行调试与文档下载联调

本次只接入运行调试与结果下载。Skill 创建、ZIP 构建、上线和权限仍沿用当前实现，不代表其他接口已联调。

## 接口

- `POST /realtime-test-case-gen/generate`，`multipart/form-data`。字段：`skill_definition`（实际 Markdown 定义）、`conversation_input`、`documents`（同名字段重复上传，最多10份）、`mounted_resources`（同名字段重复上传，最多20份）。
- 成功响应为根对象 `{ run_id, status: "completed", document, sandbox }`。同时兼容已有 `status/data` 响应包装。
- `GET /realtime-test-case-gen/runs/{run_id}/document`，按二进制读取 Excel，使用 Content-Disposition 文件名。
- 两个请求均由同源代理转发，携带 `token` 请求头。浏览器不直接跨域请求内网地址。

## 本地配置

`.env.example` 提供配置模板；`.env.local` 已加入 Git 忽略。真实 token 只配置在无 `VITE_` 前缀的 `REALTIME_DEBUG_TOKEN`，由 Vite 代理注入，不写入前端包。后端地址使用 `REALTIME_DEBUG_TARGET`，真实调试开关为 `VITE_REALTIME_DEBUG_ENABLED=true`。

开发服务读取 `.env.local`。部署时先使用真实调试开关构建，再向 `server.js` 进程配置 `REALTIME_DEBUG_TARGET` 和 `REALTIME_DEBUG_TOKEN`；也可转发已存在的平台会话 token。修改 token 后需重启对应代理进程。

## 页面行为

- 真实模式隐藏模拟成功/失败选择；失败直接显示后端原因，不回退为模拟结果。
- 需求文档与挂载资源发送原文件内容；原文件缺失时明确阻止请求，不用文件名或虚构内容替代。
- 成功后获取 Excel、保存至浏览器、展示文件名/格式/大小/结果条数/运行编号，支持自动下载与重复点击下载。
- 下载失败保留运行编号，点击“重试下载”只重复 GET，不重新调用生成接口。
- 识别 HTTP 200 中的业务失败响应、无效 token、参数错误、下载异常、空文件、非 Excel 数据及请求超时。
- 真实模式下旧的模拟调试通过记录不能用于上线操作；仍不接入真实上线接口。

## 实际验证

- 第一次直接接口请求返回 HTTP 200，业务状态为 failure，消息 `422: 在线调试超时（180 秒）`，已作为错误展示逻辑覆盖。
- 随后通过 React 页面新建技能并运行：真实生成成功，运行编号 `83d030f313b24f5d80ae75688a4dbfaf`，服务执行耗时21118毫秒。
- 用返回的运行编号成功下载 `调试结果文档.xlsx`，6636字节；验证为有效 XLSX，工作表为“功能测试用例”，含表头和1条测试用例。
- 浏览器另行验证原始需求文档与挂载资源的 multipart 内容，以及首次下载失败后仅重试GET的行为。该故障场景使用受控响应，不重复触发真实模型生成。

真实样例和截图保存在已忽略的 `output/` 下。文档到期时间来自后端响应；已经缓存到当前浏览器的文件仍可重复下载。
