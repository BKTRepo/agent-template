# 悬浮对话台后端

本模块使用独立的 `chat_*` 表。新环境按项目原有的 `aerich init-db` 流程，根据当前模型初始化表。临时附件不需要新增表。

新建会话同时使用 MySQL 和 JSONL：MySQL 的 `chat_conversations` 保存会话索引及文件相对路径，`chat_messages` 只保存消息 ID、角色、未读状态和时间；消息正文与上下文摘要只保存于 JSONL。任务、评价和统计数据仍保存在数据库中。JSONL 不包含 SDK 工具执行全过程。默认文件位置为 `applications/chat/chat_history/{user_id}/{conversation_id}.jsonl`，可通过 `CHAT_HISTORY_DIR` 指向共享存储；多进程须共享该目录，文件系统须支持跨进程锁和原子替换。清空后文件更新为新代次，删除后删除文件；旧数据库正文不会自动迁移。JSONL 不提交 Git，必须与 MySQL 一起备份：文件丢失后正文无法从 MySQL 恢复。历史正文搜索需要扫描对应用户的 JSONL 文件。

UAT 同时保留原知识库问答 `/chat/stream`、`/chat/resume-query`、`/chat/get-query-detail` 及其旧会话依赖，与本模块的 `/chat/conversation/*`、`/chat/send` 分开注册。资产与产出物继续使用 `/api/assets/*`、`/assistant/artifacts/*`。完整本地启动入口也复用本模块清理循环，启动不自动建表。

## 模型配置

悬浮对话台与开发者中心在线调试沙箱共用同一套 `.env` 网关配置，通过 `CHAT_GATEWAY_MODE` 选择：

- `direct`（默认）：复用 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_API_KEY`。DeepSeek 未单独设置时使用 `ANTHROPIC_MODEL`。
- `ccr`：使用行内已部署的 CCR，填写 `CHAT_CCR_BASE_URL`、`CHAT_CCR_AUTH_MODE` 和 `CHAT_CCR_API_KEY`。地址是 CCR 的 Anthropic 兼容服务基础地址，不是模型网关的 `/v1/chat/completions` 完整地址。认证方式支持 `bearer`（默认）、`api_key`（`x-api-key`）和 `none`（CCR 不校验凭据）。`none` 模式下 SDK 仍发送非机密占位 token；是否接受需在目标环境验证。

公网模型映射使用 `CHAT_MODEL_DEEPSEEK` 等配置。CCR 模式从网关 `/v1/models` 动态读取模型，使用 CCR 返回的完整 ID 校验和调用，页面展示时去掉供应商前缀；无需配置 `CHAT_CCR_MODEL_*` 或模型清单。列表进程内缓存 30 秒，CCR 不可用时返回错误而不展示过期配置。健康检测会向模型发送短请求并可能消耗少量 token；429 表示限流，不代表测到了排队人数。

公网直连模式可以设置 `CHAT_MODEL_REGISTRY` 自定义清单，例如：

```dotenv
CHAT_MODEL_REGISTRY='[{"id":"deepseek","name":"DeepSeek","direct_model":"deepseek-flash","ccr_model":"bank,deepseek"},{"id":"new-model","name":"新模型","ccr_model":"bank,new-model"}]'
CHAT_DEFAULT_MODEL=deepseek
```

`id` 是公网直连模式的模型标识；`direct_model` 是实际模型名。CCR 模式忽略这份清单，`GET /chat/models` 的 `name` 是完整 ID，`display_name` 是去掉供应商前缀后的模型名。出现在列表中仅表示已配置，可用性仍以健康检测为准。

`CHAT_DEFAULT_MODEL` 设置默认模型 id，留空使用当前列表第一项；CCR 模式下若填写须与 CCR 返回的完整 ID 一致。开发者中心在线调试与悬浮窗自动选模优先使用健康缓存中响应最快的模型；没有有效检测结果时优先使用默认模型。

服务端和对话容器必须都能访问 `CHAT_CCR_BASE_URL`；容器中的 `127.0.0.1` 指容器自身。实际 CCR 版本、路由、鉴权以及流式和工具调用转换能力需要在行内联调验证。部署目录也提供 CCR 容器配置。

模型健康状态通过项目 Redis 配置共享，正常状态默认缓存 60 秒，异常状态默认缓存 30 秒，分别由 `CHAT_MODEL_HEALTH_TTL_SECONDS` 和 `CHAT_MODEL_HEALTH_FAILURE_TTL_SECONDS` 配置。首次请求没有结果时立即返回 `checking`，缓存过期时返回带 `stale: true` 的上次结果；两种情况均由后台探测更新，前端可在 `refreshing: true` 时稍后重新查询。`checked_at` 是实际检测时间，UTC ISO 8601 格式。Redis 不可用时降级为进程内缓存，此时多进程之间不共享结果。模型网关地址、实际模型名或凭证变更会使用新的缓存键。

要求部署环境具备 Docker、`test-case-sandbox:local` 镜像和可访问的模型网关。知识库检索使用现有 Milvus 与 embedding 配置，并要求安装项目的 `pymilvus` 依赖。容器目录、产物目录必须在运行本任务的机器上可访问；多机器部署应配置共享产物存储。当前异常任务回收由同一机器上的后台循环处理，并非跨机器调度器。

生成的产物保存到 `applications/chat/chat_results/conversations/{conversation_id}/{generation}/{task_id}/`，服务进程需要对该目录有写入权限。产物文件不提交到 Git。

## 接口

所有接口都要求 `token` 请求头，GET 业务参数在查询字符串，POST 业务参数在 JSON 请求体。

| 方法和路径 | 参数 | 用途 |
| --- | --- | --- |
| POST `/chat/conversation/create` | `title`，可选 | 创建会话。 |
| GET `/chat/conversation/list` | `search`、`favorite`、`offset`、`limit` | 查询历史和收藏，搜索标题或当前代次消息。 |
| GET `/chat/conversation/detail` | `conversation_id` | 查询会话及已加载资源。 |
| GET `/chat/message/list` | `conversation_id`、`before_id`、`limit` | 分页查询消息。 |
| POST `/chat/conversation/rename` | `conversation_id`、`title` | 修改名称。 |
| POST `/chat/conversation/favorite` | `conversation_id`、`favorite` | 收藏或取消收藏。 |
| POST `/chat/conversation/resources` | `conversation_id`、`skills`、`knowledge_bases`、`model` | 保存当前会话资源选择。 |
| POST `/chat/conversation/read` | `conversation_id` | 将本会话 AI 消息标记已读。 |
| POST `/chat/conversation/clear` | `conversation_id` | 清空当前代次并异步清理。 |
| POST `/chat/conversation/delete` | `conversation_id` | 删除一条会话。 |
| POST `/chat/conversation/delete-all` | 无 | 删除当前用户全部会话。 |
| GET `/chat/models` | 无 | 获取模型标识 `name` 和展示名 `display_name`。 |
| GET `/chat/models/health` | 无 | 读取健康缓存；首次或过期时后台探测并返回检测中或标记过期的上次结果。 |
| POST `/chat/send` | JSON：`conversation_id`、`content`、可选 `model` | 发送纯文本消息。 |
| POST `/chat/send-with-files` | multipart：`conversation_id`、`content`、可选 `model`、`files`（多文件） | 发送消息和本次任务临时附件，允许只发附件。 |
| GET `/chat/task` | `task_id` | 查询任务状态、当前回复和完成耗时。 |
| GET `/chat/events` | `task_id` | SSE 返回任务状态及目前完整回复；前端按返回内容替换，不要拼接。 |
| POST `/chat/stop` | `task_id` | 停止生成。 |
| POST `/chat/retry` | `task_id` | 重试当前会话最新的已结束任务，替换旧回复。 |
| POST `/chat/retry-with-files` | multipart：`task_id`、`files`（多文件） | 重新上传附件并重试最新的已结束任务。 |
| POST `/chat/feedback` | `message_id`、`rating`、可选 `reason` | 点赞或点踩。 |
| POST `/chat/artifact/count-retry` | `artifact_id` | 对仍保留的文件重新发起统计。 |
| GET `/chat/statistics` | 可选 `skill_id` | 查询悬浮窗技能调用和全局产物数量。 |
| GET `/chat/statistics/count-failures` | 可选 `limit` | 管理员查看产物计数失败原因。 |

流式接口需要能设置 `token` 请求头的客户端，例如使用 `fetch` 读取流；浏览器原生 `EventSource` 无法自定义这个请求头。

附件支持 PDF、DOCX、XLSX、TXT、Markdown、JSON、CSV、Python、JavaScript、SQL、Shell、PNG 和 JPEG。单文件最多 20 MB，每次消息最多 10 个附件、合计最多 100 MB。附件随消息一次性上传，仅供本次任务使用，不记录附件信息到数据库，也不提供历史查看、下载或下次对话复用；临时文件在任务结束后清理。重试需要附件时，必须使用 `/chat/retry-with-files` 重新上传；`/chat/retry` 仅重试文本，响应的 `attachments_supplied` 为 `false`。模型通过容器中的只读文件路径按需读取，实际图片理解能力取决于模型及网关。临时附件保存在接收请求的机器上，对应任务也由该机器执行。

## 统计和清理

容器调用技能工具时，服务端先持久化调用记录再确认派发；只加载技能不计数。Excel 包含 `用例编号` 列时逐行统计，其他文件按文件数统计。任务须成功、文件须保存成功才计数。失败会重试并记录原因；清空时如果重试耗尽，会保留失败记录并清理文件，不估算数量。

清空后旧代次立即不可见。运行中的容器退出后，后台清理旧文件；任务退出或文件清理失败时保留清理状态供重试。会话内容不会重复写入悬浮窗接口的审计请求及响应正文。

较早历史在容器内分批压缩，最近消息保持原文；当前预算按字符数控制，实际模型窗口由行内网关配置决定，尚不是精确的模型 tokenizer 预算。
