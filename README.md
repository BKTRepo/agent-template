# Agent Template 集成后端

这是多个 Vibecoding 项目合并后的统一 FastAPI 后端。当前版本保留了原有的用户认证、知识库问答、任务中心、测试用例生成、工单预审、Code Server IDE 和用例推荐能力，并接入了 `applications/jiayueyang` 的文档解析与混合检索 RAG 流程。

项目以 **Python 3.13** 为唯一支持版本，使用 MySQL 保存业务数据、Redis 承载缓存和 Celery 队列，并统一使用独立 Milvus Server 2.6.4 作为向量与全文检索存储。

## 功能模块

| 模块 | 主要入口 | 说明 |
| --- | --- | --- |
| 健康检查与接口文档 | `/health`、`/docs`、`/redoc` | 服务状态、Swagger UI、Redoc |
| 用户与基础服务 | `/user`、`/base` | 登录、用户管理、审计和通用 CRUD |
| 原知识库问答 | `/knowledge-bases`、`/conversations`、`/chat` | 知识库、会话、模型配置、流式问答 |
| 增强文档 RAG | `/api/documents`、`/api/conversations`、`/api/query` | 文档上传、异步解析、混合检索、重排与问答 |
| Agent 配置 | `/skills`、`/mcp-servers` | Skill 与 MCP Server 管理 |
| 任务中心 | `/task-center` | Celery 任务登记、调度和执行记录 |
| 测试用例生成 | `/testCaseGen`、`/test-case-gen` | DOCX 测试用例生成；保留两个兼容路径 |
| 工单预审 | `/pushTickets`、`/pushTasks` 等 | 环境工单和任务预审 |
| 用例推荐 | `/case-recommendation` | 测试用例检索与推荐 |
| Code Server IDE | `/claudeEngineering` | IDE 实例管理与代理 |

受保护接口通过 `Authorization: Bearer <token>` 访问。为了兼容合并前的调用方，增强 RAG 的 `/api/*`、工单和用例推荐接口目前仍在认证白名单中；生产环境如需统一鉴权，请同步调整 `core/middlewares/auth_middleware.py` 和调用方。

## 运行要求

- Python `3.13.x`（不支持用 3.12 或更早版本创建的虚拟环境）
- MySQL 8.x
- Redis 6.x 或更高版本
- Linux、macOS 或 Windows；生产部署推荐 Linux
- 文档解析使用 Docling。离线环境需要预先准备 Docling 模型目录

## 快速开始

### 1. 创建 Python 3.13 环境

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Windows PowerShell 使用 `.venv\\Scripts\\Activate.ps1` 激活环境。

### 2. 配置环境变量

```bash
cp .env.example .env
```

至少需要检查以下配置：

```dotenv
DATABASE_HOST=127.0.0.1
DATABASE_PORT=3306
DATABASE_USERNAME=root
DATABASE_PASSWORD=your-password
DATABASE_NAME=agent_template

REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# 至少 64 个字符，生产环境必须随机生成
AUTH_SECRET_KEY=replace-with-a-random-secret-at-least-64-characters-long
```

`.env.example` 同时保留了两套 RAG 配置：

- 原知识库模块使用 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL_NAME` 等变量。
- 增强文档 RAG 使用 `LLM_MODEL`、`EMBEDDING_*`、`RERANK_*`、`VLM_*` 和 `MILVUS_*` 等变量。

如果两个模块连接同一服务，可以填写相同的 Base URL 和 API Key。不要提交真实密钥或 `.env` 文件。

### 3. 准备数据库

先在 MySQL 中创建与 `DATABASE_NAME` 一致的数据库并使用 `utf8mb4` 字符集。开发环境可通过 `AUTO_MIGRATION=true` 允许启动时执行 Aerich 迁移；对已有生产数据库启用自动迁移前应先备份并审阅迁移脚本。

如需手动初始化管理员：

```bash
python services/scripts/init_admin.py
```

初始化后应立即修改默认凭据。

### 4. 启动 API

```bash
uvicorn backend_main:app --host 0.0.0.0 --port 8519 --reload
```

浏览器访问：

- Swagger UI：<http://127.0.0.1:8519/docs>
- Redoc：<http://127.0.0.1:8519/redoc>
- 健康检查：<http://127.0.0.1:8519/health>

### 5. 启动 Celery

增强 RAG 的文档解析和 Milvus 写入、测试用例生成以及任务中心调度都依赖 Celery Worker。

macOS/Windows 开发环境：

```bash
celery -A celery_scheduler.celery_worker:celery worker \
  -Q default,autotest_queue --pool=solo -l INFO
```

Linux Worker：

```bash
celery -A celery_scheduler.celery_worker:celery worker \
  -Q default,autotest_queue -c 4 -l INFO
```

定时任务：

```bash
celery -A celery_scheduler.celery_worker:celery beat \
  --scheduler redbeat.schedulers:RedBeatScheduler -l INFO
```

Linux 也可使用统一脚本：

```bash
./celery_deploy.sh start
./celery_deploy.sh status
```

## 增强 RAG 工作流

```text
上传文件
  -> MySQL 创建文档记录
  -> Celery 异步解析 PDF/DOCX
  -> Docling 清洗、表格与图片处理
  -> 分块、摘要和术语提取
  -> Embedding
  -> Milvus Server（Dense 向量 + 内置 BM25）
  -> 中文 BM25 + 英文 BM25 + Dense + RRF + Rerank
  -> LLM 流式回答
```

向量后端固定为 Milvus C/S 架构，`MILVUS_URI` 必须配置为 `http://host:19530` 或 HTTPS 服务地址。客户端依赖锁定为 `pymilvus==2.6.4`，与服务端版本保持一致。文档解析仍由 Celery Worker 执行；Web 与 Worker 均通过进程内有界连接池连接 Milvus Server，可用 `MILVUS_POOL_SIZE` 和 `MILVUS_POOL_ACQUIRE_TIMEOUT` 调整池大小与等待时间。

离线部署 Docling 时，将模型放到 `DOCLING_ARTIFACTS_PATH` 指定目录，并设置 `DOCLING_ALLOW_REMOTE_MODELS=false`。大文件上传受 `RAG_MAX_UPLOAD_MB` 限制，API 会同时校验请求头和实际读取字节数。

## 生产部署

启动 API：

```bash
gunicorn -c gunicorn_config.py backend_main:app
```

同时部署 Redis、Celery Worker 和 Celery Beat。生产环境还应：

- 使用反向代理提供 TLS，并限制上传体积和请求速率。
- 将 MySQL、Redis、LLM 和向量库凭据放入密钥管理系统。
- 持久化 `output/`、RAG 数据目录和向量库目录。
- 禁用不需要的公开白名单并更换所有默认凭据。
- 在迁移前备份数据库，避免让多个 API 实例同时执行自动迁移。

仓库提供的 `deploy/nginx.conf` 可作为反向代理配置起点，需要按实际域名、证书和端口修改。

### 复杂问答与截断保护配置

部署复用旧 `.env` 时可以依赖代码默认值，但建议显式同步以下配置，便于环境核对和回滚：

```ini
SUBQUERY_MAX_TOKENS=800
SUBQUERY_MAX_COUNT=4
SUBQUERY_MAX_LENGTH=40
SUBQUERY_TRUNCATION_RETRY_ENABLED=true
SUBQUERY_RULE_FALLBACK_ENABLED=true
SUBQUERY_FALLBACK_CACHE_TTL=300
SUBQUERY_QUOTA_BACKFILL_ENABLED=true
SUBQUERY_MIN_FINAL_CHUNKS=1
SUBQUERY_BACKFILL_MAX_TOTAL=3
SUBQUERY_BACKFILL_MIN_SCORE=0
SUBQUERY_BACKFILL_REQUIRE_ANCHOR=false
ANSWER_TRUNCATION_RETRY_ENABLED=true
ANSWER_PARTIAL_FALLBACK_ENABLED=true
ANSWER_CONCISE_RETRY_MAX_CHARS=1500
FIELD_VARIANT_NORMALIZATION_ENABLED=true
```

子问题候选先由各自检索和统一 rerank 排序，再做有限回填；不再要求单个分块同时包含字段、代码和完整业务含义，避免跨块表格证据被硬过滤。修改上述配置或代码后需重启 API；Celery Worker 只有在其任务也读取了相同配置时才需要同步重启。

## 测试与校验

在已配置测试环境变量或 `.env` 后运行：

```bash
python -m pytest -q
python -m compileall -q applications common configure core services celery_scheduler
python -m pip check
```

本次合并已在 Python 3.13 下验证：应用可完成导入并注册全部核心路由，现有测试和新增的合并兼容性测试均通过。

## 目录结构

```text
applications/
  base/                    原 RAG 基础设施和公共服务
  user/                    用户与认证
  knowledge_base/          原知识库管理
  conversation/            原会话模块
  jiayueyang/              增强文档 RAG
  task_center/             通用任务中心
  test_case_generate/      测试用例生成
  ticket_review/           工单预审
  code_server_ide/         Code Server IDE
celery_scheduler/
  tasks/                   通用、RAG 和维护任务
configure/                 环境、RAG、Celery 和日志配置
core/                      生命周期、中间件、异常与响应封装
migrations/                Aerich 数据库迁移
services/scripts/          初始化、迁移和数据维护脚本
static/                    本地接口文档静态资源
static_vendor/             合并模块携带的 Swagger 静态资源
tests/                     单元和集成测试
```

## 常见问题

- **依赖安装异常**：确认 `python --version` 为 3.13，并删除后重新创建由旧 Python 版本生成的虚拟环境。
- **启动时数据库连接失败**：确认 MySQL 已创建目标数据库，且 `DATABASE_*` 配置可从当前主机访问。
- **上传后一直处于处理中**：检查 Redis、Celery Worker 和 Worker 队列是否已启动。
- **向量写入或检索失败**：确认 Milvus Server 2.6.4 可从当前主机访问，并检查 `MILVUS_URI`、认证信息和 PyMilvus 版本。
- **Docling 尝试联网下载**：准备完整的离线模型目录，并将 `DOCLING_ALLOW_REMOTE_MODELS` 设为 `false`。
- **旧接口返回 401**：确认接口是否在认证白名单中；受保护接口需携带有效 Bearer Token。
