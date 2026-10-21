# FastAPI 后端模板

基于 FastAPI、Tortoise ORM 和 Pydantic Settings 的通用后端框架，保留认证、用户管理、审计日志、路由查询、统一响应、异常处理、请求追踪和本地 API 文档资源。

目录划分参考 [fastapi-template 的 main 分支](https://github.com/KKNOBUG/fastapi-template/tree/main)（参考提交 `ff52be9`）。`applications/` 仅保留 `base` 和 `user`，供新项目扩展；没有商品示例、知识库、会话、模型配置、Agent、用例生成/推荐、任务中心、后台调度或预置业务数据。

## 项目结构

```text
applications/
  base/                # 通用模型和 CRUD 基类、认证、审计、路由查询
  user/                # 用户模型、请求参数、用户管理接口
common/                # 文件、Shell 和请求追踪工具
configure/             # 应用、日志和路由元数据配置
core/
  initializations/     # 数据库连接、路由、中间件、异常注册
  middlewares/         # 认证、审计、请求追踪
  responses/           # 统一响应
  exceptions/          # 统一异常
  decorators/          # 通用装饰器
enums/                 # 状态、错误和 HTTP 枚举
services/              # 密码、JWT、依赖注入和文件传输
  scripts/init_admin.py
static/                # Swagger UI / ReDoc 本地资源
output/                # 日志、上传、下载等运行数据（忽略提交）
tests/                 # 使用临时 SQLite 的集成检查
backend_main.py        # 应用入口
gunicorn_config.py     # Linux 生产服务配置
pyproject.toml         # 基础依赖、开发依赖和 Aerich 配置
uv.lock                # 可复现的依赖锁定文件
.env.example           # 配置示例
```

## 快速开始

要求 Python >= 3.12，推荐使用 uv。在项目根目录执行：

```bash
uv sync --frozen
```

复制 `.env.example` 为 `.env`（PowerShell 使用 `Copy-Item .env.example .env`，Linux/macOS 使用 `cp .env.example .env`），生成独立 JWT 密钥并填入 `AUTH_SECRET_KEY`：

```bash
uv run python -c "import secrets; print(secrets.token_hex(32))"
```

默认使用 SQLite，数据库文件为 `output/template.db`。首次使用一个全新数据库时，显式初始化基础表和迁移目录：

```bash
uv run aerich init-db
```

项目已在 `pyproject.toml` 配置 Aerich，无需再次执行 `aerich init`。模板未附带特定数据库的迁移文件；新项目生成迁移后应将 `migrations/` 提交到自己的仓库。已有迁移的项目部署到新环境时，使用 `uv run aerich upgrade`。

启动服务：

```bash
uv run python backend_main.py
# 或
uv run uvicorn backend_main:app --host 0.0.0.0 --port 8000
```

访问地址：

- 健康检查：`http://localhost:8000/health`
- Swagger：`http://localhost:8000/docs`
- ReDoc：`http://localhost:8000/redoc`
- OpenAPI：`http://localhost:8000/openapi.json`

应用启动只建立 ORM 连接，不会创建表、生成迁移、初始化管理员或写入示例数据。`/health` 表示应用存活，不执行数据库可用性探测。

### 创建管理员（可选）

初始化数据库后，显式运行以下命令，按提示输入密码：

```bash
uv run python -m services.scripts.init_admin --username admin --email admin@example.com
```

也支持 `uv run python services/scripts/init_admin.py --username admin --email admin@example.com`。密码使用 Argon2 哈希保存；账号已存在时不会覆盖其密码和权限。模板没有默认管理员密码。

### 不使用 uv

创建并激活 Python >= 3.12 虚拟环境，然后执行：

```bash
python -m pip install -r requirements.txt
aerich init-db
python backend_main.py
```

`requirements.txt` 由锁定文件导出，只包含运行依赖。Gunicorn 和 uvloop 仅在非 Windows 平台安装。

## 配置

配置由 `configure/project_config.py` 从项目根目录的 `.env` 和环境变量读取，环境变量优先。

| 配置 | 说明 |
| --- | --- |
| `AUTH_SECRET_KEY` | 必填，至少 64 个字符 |
| `AUTH_JWT_ALGORITHM` | 默认 `HS256` |
| `AUTH_JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | 默认 10080 分钟 |
| `DATABASE_URL` | 示例为 `sqlite://output/template.db`；支持 Tortoise 数据库 URL |
| `DATABASE_HOST` / `DATABASE_PORT` | 不配置 URL 时使用的 MySQL 主机和端口 |
| `DATABASE_USERNAME` / `DATABASE_PASSWORD` / `DATABASE_NAME` | 不配置 URL 时使用的 MySQL 账号、密码和库名 |
| `DATABASE_AUTO_MIGRATION` | 默认 `False`；开启后只应用已有迁移，不生成新迁移或重建迁移目录 |
| `SERVER_HOST` / `SERVER_PORT` | 默认监听 `0.0.0.0:8000` |
| `SERVER_DEBUG` | 示例为 `False`；开发时可开启自动重载 |
| `APP_TITLE` / `APP_DESCRIPTION` | API 文档标题和描述 |

使用 MySQL 时，先创建空数据库和对应账号，再删除 `.env` 的 `DATABASE_URL`，填写 MySQL 参数。运行时不需要 Redis、向量数据库或模型 API Key。

模型变更后手动生成并检查迁移，再升级：

```bash
uv run aerich migrate --name your_change
uv run aerich upgrade
```

`configure.project_config.TORTOISE_ORM` 由应用、Aerich 和管理员脚本共用。基础用户与审计表沿用参考框架的 `keenrobot_user`、`keenrobot_audit` 表名。

## 基础接口

路径直接从根路径开始，没有 `/api` 前缀。

| 接口 | 说明 | 认证 |
| --- | --- | --- |
| `GET /`、`GET /health` | 欢迎信息、健康检查 | 否 |
| `POST /base/auth/access_token` | 用户名和密码登录 | 否 |
| `POST /base/auth/userinfo` | 当前用户 | 是 |
| `POST /user/create` | 创建用户 | 否 |
| `/user/*` 其他接口 | 查询、更新、删除用户，改密、登出 | 是 |
| `/base/audit/*` | 审计日志查询与管理 | 是 |
| `POST /base/routes/routers` | 查询已注册路由 | 是 |

登录请求示例：

```json
{"username": "your_username", "password": "your_password"}
```

后续请求通过 `token: <access_token>` 请求头传递令牌。沿用参考框架的统一响应格式，客户端同时检查 `status` 和 `code`；业务失败可能使用 HTTP 200 返回。

```json
{"code": "000000", "status": "success", "message": "操作成功", "data": null, "total": null}
```

完整参数以 `/docs` 为准。新模块按 `models / schemas / services / views` 分层创建，在 `core/initializations/app_initialization.py` 注册路由；模型会按 `applications/<模块>/models/*model.py` 自动发现。

## 验证

```bash
uv sync --frozen
uv run python -m unittest discover -s tests -v
```

检查使用隔离的内存/临时 SQLite，覆盖首次建表、迁移升级、无模型变更时不生成迁移、显式启动迁移、应用启动无自动建表或预置数据、基础模型与接口范围、认证和令牌吊销、用户更新、管理员初始化、密码校验、本地文档资源、请求追踪和模块导入。MySQL 配置装配有覆盖；连接实际 MySQL 服务需要自行提供测试实例。

依赖更新后同步锁定文件和 pip 清单：

```bash
uv lock
uv export --frozen --no-dev --no-emit-project --no-hashes --no-annotate --format requirements-txt --output-file requirements.txt
```
