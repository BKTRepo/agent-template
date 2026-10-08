# 简介

企业级 RAG（检索增强生成）问答系统后端，基于 FastAPI 构建，提供用户认证、知识库管理、模型配置、任务调度与流式智能问答能力。

## 技术栈

| 类别 | 技术 |
|------|------|
| Web 框架 | FastAPI |
| ORM | Tortoise ORM + Aerich（数据库迁移） |
| 关系型数据库 | MySQL（默认）/ SQLite |
| 向量数据库 | ChromaDB（本地持久化） |
| RAG | LangChain（文档加载、分块） |
| LLM | OpenAI 兼容 API（默认 DeepSeek） |
| Embedding | OpenAI 兼容 API（默认硅基流动） |
| 认证 | JWT + argon2 密码哈希 |
| 流式输出 | SSE（sse-starlette） |
| 配置 | pydantic-settings |
| 任务调度 | Celery + Celery Beat + Redis |

## 项目结构

```
├── backend_main.py                 # FastAPI 入口
├── configure/
│   ├── project_config.py           # ProjectConfig（pydantic-settings）
│   ├── celery_config.py            # Celery 配置（Redis、Beat 调度）
│   ├── global_config.py            # 全局常量配置
│   ├── logging_config.py           # 日志配置
│   ├── rag_config.py               # RAG 系统提示词配置
│   └── router_registry.py          # 路由注册信息
├── services/
│   ├── dependency.py               # 认证依赖（DependAuth）
│   ├── password.py                 # JWT / 密码工具（argon2）
│   ├── ctx.py                      # 请求上下文（CTX_USER_ID）
│   ├── file_transfer.py            # 文件传输工具
│   └── scripts/                    # 运维脚本
│       ├── init_admin.py           # 初始化管理员
│       ├── init_model_configs.py   # 初始化模型配置
│       └── build_kb.py             # 离线构建向量库
├── applications/                   # 业务模块（models / schemas / services / views）
│   ├── base/                       # 基础服务
│   │   ├── rag/                    # RAG 链、向量库、LLM、Embedding
│   │   ├── services/               # 审计日志 CRUD、脚手架基类
│   │   ├── schemas/                # 基础 schemas
│   │   └── views/                  # 认证、审计、路由视图
│   ├── user/                       # 用户与认证
│   ├── conversation/               # 对话与历史
│   ├── knowledge_base/             # 知识库与文档
│   ├── model_config/               # LLM 模型配置（连接/参数/厂商/深度思考）
│   ├── agent/                      # Agent 技能与 MCP 服务配置
│   ├── task_center/                # 任务中心（Celery 定时任务调度）
│   └── example/                    # 示例模块（商品分类/模型）
├── celery_scheduler/               # Celery 定时任务调度
│   ├── celery_base.py              # Celery 基础配置与 Tortoise ORM 初始化
│   ├── celery_worker.py            # Celery Worker 实例
│   └── tasks/                      # 任务定义
│       ├── task_dispatch.py        # 任务调度与分发
│       └── task_example.py         # 示例任务
├── core/
│   ├── chroma_db/                  # ChromaDB 持久化目录
│   ├── rag_db/                     # SQLite 数据库目录（rag_system.db）
│   ├── initializations/            # 应用初始化（数据库、中间件、路由、异常）
│   ├── middlewares/                # 认证、日志、请求上下文中间件
│   ├── responses/                  # 统一响应封装
│   └── exceptions/                 # 自定义异常与处理器
├── enums/                          # 枚举定义（HTTP状态、任务状态、聊天角色等）
├── common/                         # 通用工具（文件、Shell、异步转换、请求上下文）
├── migrations/                     # Aerich 迁移文件
├── output/                         # 输出目录（日志、上传、下载、媒体等）
├── static/                         # 静态文件（Swagger UI、Redoc、头像等）
├── .env                            # 环境变量（需自行创建）
└── pyproject.toml                  # Python 依赖（uv / pip）
```

## 环境要求

- Python >= 3.12
- [uv](https://github.com/astral-sh/uv)（推荐）或 pip
- Redis（任务调度必需）

## 快速开始

### 1. 安装依赖

```bash
uv sync
# 或
pip install -e .
```

数据库迁移需要额外安装 Aerich：

```bash
uv add aerich
# 或
pip install aerich
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少配置：

- `AUTH_SECRET_KEY`：JWT 密钥，**长度不少于 64 位**（可用 `openssl rand -hex 32` 生成）
- `LLM_API_KEY`：大模型 API Key（如 DeepSeek）
- `EMBEDDING_API_KEY`：向量模型 API Key（如硅基流动，知识库检索必需）
- `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD`：Redis 配置（Celery 任务调度必需）

完整配置项见 [环境变量说明](#环境变量说明)。

### 3. 初始化数据库

**首次部署**（在项目根目录执行）：

```bash
aerich init -t configure.project_config.TORTOISE_ORM
aerich init-db
```

若已有迁移文件（`migrations/` 目录），直接升级：

```bash
aerich upgrade
```

### 4. 初始化业务数据

```bash
python services/scripts/init_admin.py
# 模型配置在「模型管理」页面自行创建，不再自动 seed 到数据库
```

默认管理员账号：

| 字段 | 值      |
|------|--------|
| 用户名 | admin  |
| 密码 | 123456 |

### 5. 启动后端

```bash
uv run python backend_main.py
# 或
uvicorn backend_main:app --host 0.0.0.0 --port 8000 --reload
```

启动后访问：

- 健康检查：http://localhost:8000/api/health
- Swagger 文档：http://localhost:8000/docs
- ReDoc：http://localhost:8000/redoc

### 6. 启动 Celery 服务（任务调度必需）

```bash
# 启动 Worker（处理异步任务）
celery -A celery_scheduler.celery_worker worker -Q default -c 4 -l INFO

# 启动 Beat（定时调度器，需另开终端）
celery -A celery_scheduler.celery_worker beat -l INFO
```

## 环境变量说明

配置文件路径：`.env`（由 `configure/project_config.py` 中的 `ProjectConfig` 加载）。

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_HOST` | MySQL 主机 | `localhost` |
| `DATABASE_PORT` | MySQL 端口 | `3306` |
| `DATABASE_USERNAME` | MySQL 用户名 | `rag_user` |
| `DATABASE_PASSWORD` | MySQL 密码 | `password` |
| `DATABASE_NAME` | MySQL 库名 | `rag_system` |
| `AUTH_SECRET_KEY` | JWT 密钥（≥64 位） | — |
| `AUTH_JWT_ALGORITHM` | JWT 算法 | `HS256` |
| `AUTH_JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Token 过期时间（分钟） | `10080`（7天） |
| `LLM_API_KEY` | 大模型 Key（ModelConfig 为空时兜底） | — |
| `LLM_BASE_URL` | 大模型 API 地址 | `https://api.deepseek.com/v1` |
| `LLM_MODEL_NAME` | 默认模型名 | `deepseek-chat` |
| `EMBEDDING_API_KEY` | 向量模型 Key（兼容 `SILICONFLOW_API_KEY`） | — |
| `EMBEDDING_BASE_URL` | 向量 API 地址 | `https://api.siliconflow.cn/v1` |
| `EMBEDDING_MODEL_NAME` | 默认 Embedding 模型 | `BAAI/bge-large-zh-v1.5` |
| `CHROMA_COLLECTION` | Chroma 集合名 | `knowledge_base` |
| `REDIS_HOST` | Redis 主机 | `localhost` |
| `REDIS_PORT` | Redis 端口 | `6379` |
| `REDIS_PASSWORD` | Redis 密码 | — |
| `DATABASE_AUTO_MIGRATION` | 开发环境自动迁移开关 | `False` |

代码中通过单例访问配置：

```python
from configure import PROJECT_CONFIG
```

## API 接口

### 健康检查

| 方法 | 路径 | 认证 |
|------|------|------|
| GET | `/api/health` | 否 |

### 认证 `/api/base/auth`

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/base/auth/access_token` | 用户登录，返回 JWT | 否 |
| POST | `/api/base/auth/userinfo` | 获取当前用户信息 | 是 |

**登录请求示例**：

```json
{
  "username": "admin",
  "password": "123456"
}
```

**登录响应示例**：

```json
{
  "code": "000000",
  "status": "success",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "username": "admin",
    "alias": "管理员",
    "is_superuser": true
  }
}
```

### 用户 `/api/user`

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/user/create` | 用户注册 | 否 |
| POST | `/api/user/logout` | 用户登出（吊销 Token） | 是 |
| DELETE | `/api/user/delete` | 删除用户（Query: user_id） | 是 |
| POST | `/api/user/delete` | 批量删除用户 | 是 |
| POST | `/api/user/update` | 更新用户信息 | 是 |
| GET | `/api/user/get` | 查询用户详情（Query: user_id） | 是 |
| GET | `/api/user/byUsername` | 按用户名查询（Query: username） | 是 |
| GET | `/api/user/list` | 用户列表（分页查询） | 是 |
| POST | `/api/user/search` | 用户列表（Body 查询） | 是 |
| POST | `/api/user/update_password` | 修改密码 | 是 |
| POST | `/api/user/reset_password` | 重置密码 | 是 |

### 对话历史 `/api/conversations`

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/conversations/` | 查询当前用户对话列表 | 是 |
| GET | `/api/conversations/{conversation_id}` | 查询对话详情（含消息） | 是 |
| DELETE | `/api/conversations/{conversation_id}` | 删除单条对话 | 是 |
| DELETE | `/api/conversations/` | 清空所有对话 | 是 |

### 聊天 `/api/chat`

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/chat/stream` | SSE 流式问答 | 是 |

**请求体示例**：

```json
{
  "question": "公司的年假政策是什么？",
  "conversation_id": "可选，续聊时传入",
  "knowledge_base_ids": ["知识库ID"],
  "model_config_id": "可选，传 null 则不绑定配置",
  "enable_thinking": false
}
```

当 `model_config_id=null` 时，前端不展示模型下拉选择器，聊天链路纯走 `.env` 兜底；深度思考开关仅当选中配置的 `model_thinking=true` 时显示。

**SSE 事件类型**：

| event | 含义 |
|-------|------|
| `meta` | 返回 `conversation_id` |
| `reasoning` | 深度思考推理内容（仅 `model_thinking=true` 的配置且用户开启时触发） |
| `token` | 流式文本片段 |
| `usage` | Token 用量（prompt_tokens / completion_tokens / reasoning_tokens） |
| `done` | 回答完成（含完整 `content`、`usage`、`process_trace`） |
| `error` | 错误信息 |

### 知识库 `/api/knowledge-bases`

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/knowledge-bases/` | 创建知识库 | 是 |
| GET | `/api/knowledge-bases/` | 列表（支持 `?search=`） | 是 |
| GET | `/api/knowledge-bases/{kb_id}` | 详情 | 是 |
| PUT | `/api/knowledge-bases/{kb_id}` | 更新 | 是 |
| DELETE | `/api/knowledge-bases/{kb_id}` | 删除 | 是 |
| POST | `/api/knowledge-bases/{kb_id}/documents` | 上传 PDF | 是 |
| GET | `/api/knowledge-bases/{kb_id}/documents` | 文档列表 | 是 |
| DELETE | `/api/knowledge-bases/{kb_id}/documents/{doc_id}` | 删除文档 | 是 |
| GET | `/api/knowledge-bases/{kb_id}/chunks` | 分块列表（Query: doc_id, page, page_size） | 是 |
| GET | `/api/knowledge-bases/{kb_id}/chunks/{chunk_id}` | 分块详情 | 是 |
| PUT | `/api/knowledge-bases/{kb_id}/chunks/{chunk_id}` | 更新分块 | 是 |
| DELETE | `/api/knowledge-bases/{kb_id}/chunks/{chunk_id}` | 删除分块 | 是 |

### 模型配置 `/model-configs`

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/model-configs/` | 配置列表 | 是 |
| POST | `/model-configs/` | 创建配置 | 是 |
| GET | `/model-configs/default` | 获取当前用户默认配置 | 是 |
| GET | `/model-configs/{config_id}` | 配置详情 | 是 |
| PUT | `/model-configs/{config_id}` | 更新配置 | 是 |
| DELETE | `/model-configs/{config_id}` | 删除配置 | 是 |
| POST | `/model-configs/{config_id}/default` | 设为默认 | 是 |

列表仅返回**当前登录用户**自己创建的配置。ModelConfig 核心字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `config_name` | string | 用户自定义配置名称 |
| `config_desc` | string? | 配置说明 |
| `model_provider` | string | 厂商分类（`custom`/`deepseek`/`openai`/`siliconflow` 等） |
| `model_thinking` | bool | 是否展示深度思考开关 |
| `llm_model_name` | string | API 请求体中的 `model` 参数 |
| `llm_base_url` | string? | 模型接入地址；空 → `.env` 的 `LLM_BASE_URL` |
| `llm_api_key` | string? | 创建/更新时传入，**加密入库**；查询时脱敏返回（`llm_api_key_masked`）；空 → `.env` 的 `LLM_API_KEY`；更新时空值/含 `***` 不覆盖已有 Key |

聊天时模型解析优先级：
1. 请求中的 `model_config_id`（须属于当前登录用户）
2. 当前用户的 `is_default` 配置（无 default 标记则取最早一条）
3. 以上均无 → `model_config=None`，走 `.env`（`LLM_MODEL_NAME` / `LLM_BASE_URL` / `LLM_API_KEY`）+ 代码默认参数

> 不再降级读取 admin 的配置。

### Agent 技能 `/api/agent`

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/agent/skills` | 技能列表 | 是 |
| POST | `/api/agent/skills` | 创建技能 | 是 |
| PUT | `/api/agent/skills/{skill_id}` | 更新技能 | 是 |
| DELETE | `/api/agent/skills/{skill_id}` | 删除技能 | 是 |
| GET | `/api/agent/mcp-servers` | MCP 服务列表 | 是 |
| POST | `/api/agent/mcp-servers` | 创建 MCP 服务 | 是 |
| PUT | `/api/agent/mcp-servers/{server_id}` | 更新 MCP 服务 | 是 |
| DELETE | `/api/agent/mcp-servers/{server_id}` | 删除 MCP 服务 | 是 |

### 任务中心 `/api/task-center`

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/task-center/presets` | 获取任务模板与调度选项 | 是 |
| POST | `/api/task-center/create` | 创建任务 | 是 |
| POST | `/api/task-center/update` | 更新任务 | 是 |
| DELETE | `/api/task-center/delete` | 删除任务 | 是 |
| GET | `/api/task-center/get` | 查询任务详情 | 是 |
| POST | `/api/task-center/search` | 搜索任务列表 | 是 |
| POST | `/api/task-center/run` | 立即执行任务 | 是 |
| POST | `/api/task-center/start` | 启动任务调度 | 是 |
| POST | `/api/task-center/stop` | 停止任务调度 | 是 |
| POST | `/api/task-center/record/search` | 查询执行记录 | 是 |

### 审计日志 `/api/base/audit`

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/base/audit/list` | 审计日志列表（Query） | 是 |
| POST | `/api/base/audit/search` | 审计日志列表（Body） | 是 |
| GET | `/api/base/audit/get` | 单条审计日志 | 是 |
| GET | `/api/base/audit/byUser` | 用户审计日志 | 是 |
| GET | `/api/base/audit/recent` | 最近审计日志 | 是 |
| GET | `/api/base/audit/statistics` | 审计统计 | 是 |
| DELETE | `/api/base/audit/delete` | 删除单条 | 是 |
| POST | `/api/base/audit/delete` | 批量删除 | 是 |
| DELETE | `/api/base/audit/deleteByUser` | 按用户删除 | 是 |
| DELETE | `/api/base/audit/deleteByTime` | 按时间删除 | 是 |
| DELETE | `/api/base/audit/clearAll` | 清空所有 | 是 |

### 路由查询 `/api/base/routes`

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/base/routes/routers` | 查询所有路由信息 | 是 |

## 认证方式

- **普通请求**：在 Header 中添加 `token: <jwt_token>`
- **文件上传/SSE**：需手动将 Token 放入 `token` Header
- **登录/注册**：无需携带 Token

**响应格式**：

```json
{
  "code": "000000",
  "status": "success",
  "message": "操作成功",
  "data": { ... },
  "total": 100
}
```

## RAG 处理流程

```
用户提问
  → Embedding 向量化问题
  → ChromaDB 检索相关知识块（按 knowledge_base_ids 过滤）
  → 拼接上下文 + 历史消息
  → 调用 LLM 流式生成回答
  → 保存 assistant 消息到数据库
```

PDF 上传处理流程：

```
上传 PDF → PyMuPDF 解析 → 文本分块（500 字 / 100 重叠）
  → Embedding 向量化 → 写入 ChromaDB + 元数据入库
```

文档 `status`：`processing`（处理中）/ `completed`（成功）/ `failed`（失败）。同内容重传时，`failed` 或卡住的 `processing` 记录会被清理后覆盖；`completed` 仍拒绝重复上传。

对话/知识库等业务表使用 `state=1` 软删除，用于统计与留档，不提供恢复入口。

## 任务中心说明

### 架构设计

任务中心基于 **Celery + Redis + Celery Beat** 实现异步任务调度：

```
┌─────────────────────────────────────────────────────────┐
│                   FastAPI 后端                           │
│  ┌────────────────────────────────────────────────────┐ │
│  │  TaskCenterInfo (任务定义)                          │ │
│  │  - task_name, task_type, task_celery_node           │ │
│  │  - task_celery_scheduler: interval/cron/datetime   │ │
│  │  - task_enabled, task_version                      │ │
│  └────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────┐ │
│  │  TaskCenterRecord (执行记录)                        │ │
│  │  - celery_id, task_celery_status                   │ │
│  │  - celery_start_time, celery_end_time              │ │
│  │  - task_summary, task_error                        │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│              Celery + Redis + Beat                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  Beat 调度器   │  │  Worker 执行  │  │  Redis 队列   │ │
│  │  (定时扫描)    │  │  (异步任务)   │  │  (消息中间件)  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 调度机制

Celery Beat 每 60 秒扫描一次启用且配置了调度的任务：

```python
"beat_schedule": {
    "scan-task-center-tasks": {
        "task": "celery_scheduler.tasks.task_dispatch.scan_and_dispatch_tasks",
        "schedule": 60.0,
    },
}
```

调度逻辑：
1. 查询所有启用且配置了调度的任务
2. 检查任务是否到期（interval/cron/datetime）
3. 到期则通过 Celery 发送任务到 Worker
4. Worker 执行并记录执行结果

### 任务状态流转

```
创建任务 ──► 启用调度 ──► 等待到期 ──► 执行中 ──► 成功/失败
   │           │           │           │
   │           │           │           └── 记录执行结果
   │           │           │
   │           │           └── 检查间隔/cron/定时
   │           │
   │           └── 版本号+1，调度器感知
   │
   └── 禁用调度 ──► 停止执行
```

### 任务调度模式

- **interval**: 固定间隔（秒），如每 60 秒执行一次
- **cron**: Cron 表达式，如 `0 9 * * 1`（每周一 9:00）
- **datetime**: 一次性定时任务，如 `2026-06-15 10:00:00`

### 注意事项

1. **Celery 服务启动**：任务中心依赖 Celery Worker 和 Beat，需要单独启动（见 [快速开始](#快速开始) 第 6 步）
2. **Redis 配置**：确保 `.env` 中配置了 Redis（用于 Celery 消息队列和 Beat 调度）
3. **任务版本机制**：每次启用/停止任务时版本号递增，调度器通过版本号感知任务变更
4. **执行记录**：任务执行后会生成记录，包含执行状态、开始/结束时间、耗时、错误信息

## 工具脚本

```bash
# 初始化管理员
python services/scripts/init_admin.py

# 手动创建模型配置示例（应用启动时不再自动 seed，需在「模型管理」页面创建）
python services/scripts/init_model_configs.py

# 离线构建向量库（读取 output/data/*.pdf）
python services/scripts/build_kb.py
```

## 架构说明

### 模块化分层

每个业务域（`user`、`conversation`、`knowledge_base`、`model_config`、`agent`、`task_center`）均包含：

- `models/` — Tortoise ORM 模型
- `schemas/` — Pydantic 请求/响应模型
- `services/` — 业务逻辑与数据访问
- `views/` — FastAPI 路由（API 层）

公共能力集中在：

- `configure/` — 应用配置
- `services/` — 认证、依赖注入、上下文
- `applications/base/rag/` — RAG 基础设施
- `core/` — 中间件、异常处理、响应封装、初始化
- `celery_scheduler/` — 异步任务调度

### 数据库初始化

`core/initializations/app_initialization.py` 在 FastAPI lifespan 中调用：

```python
register_tortoise(app=app, config=config, generate_schemas=False)
```

并自动执行 Aerich 迁移（生产环境 Linux 始终执行，开发环境 macOS/Windows 需开启 `DATABASE_AUTO_MIGRATION`）。

### 认证流程

1. 登录 `/api/base/auth/access_token` 获取 JWT
2. 后续请求在 Header 携带 `token: <jwt_token>`
3. `auth_middleware` 解析并验证 Token
4. `DependAuth` 依赖注入当前用户到视图函数
5. 登出 `/api/user/logout` 增加 `token_version` 吊销所有 Token

## 常见问题

### 启动报 `Module "aerich.models" not found`

安装 Aerich 后重启：

```bash
pip install aerich
```

或在 `configure/project_config.py` 的 `TORTOISE_ORM` 中移除 `aerich.models`（仅在不使用 Aerich 迁移时可临时处理）。

### 注册/登录报 `No TortoiseContext is currently active`

确认 `register_database()` 已正确调用 `register_tortoise`，并检查 lifespan 是否正常执行（启动日志中应有 `Application startup complete`）。

### 知识库问答不检索文档

检查 `.env` 中是否配置了 `EMBEDDING_API_KEY`。未配置时系统会跳过向量检索，退化为纯 LLM 对话。

### 切换 MySQL

```env
DATABASE_HOST=localhost
DATABASE_PORT=3306
DATABASE_USERNAME=rag_user
DATABASE_PASSWORD=your_password
DATABASE_NAME=rag_system
```

修改后重新执行 `aerich upgrade`。

### 任务中心任务不执行

检查以下服务是否已启动：
1. Redis 服务
2. Celery Worker：`celery -A celery_scheduler.celery_worker worker -Q default -c 4 -l INFO`
3. Celery Beat：`celery -A celery_scheduler.celery_worker beat -l INFO`

### PyCharm 调试

- **Working directory**：项目根目录
- **Script path**：`backend_main.py`

---

*文档最后更新：2026-10-08*

## 信创测试策略裁剪器（master 新增）

React 前端位于 `frontend/`，新增后端模块位于 `applications/strategy_trimmer/`，已通过原路由注册接入 `backend_main.py`。规则从数据库读取，系统自动化资产单表存储并支持 Excel 导入、前端只读。根据六步选择生成并保存 Markdown，可按需求编号或名称查询最新文档下载；不保存原始选择 JSON。

使用原后端启动方式（默认 `8519`），在 `frontend/` 运行 `npm ci` 和 `npm run dev`，访问 `http://127.0.0.1:5173`。完整启动、接口、原型来源及验证说明见 [裁剪器说明](docs/strategy-trimmer.md)。
