---
title: 信创测试策略裁剪器
status: implemented
last_updated: 2026-10-08
---

# master 分支新增功能

本功能在 `KKNOBUG/agent-template` 的 master（基线 `72b71e9`）上增量实现。后端沿用原项目 FastAPI、统一响应、路由注册和视图 / 服务 / Schema 分层；React 前端单独放在 `frontend/`。原有聊天、任务中心、知识库等模块不做替换。

## 功能与原型

原型归档在 `docs/prototype/demo-终版-0826-裁剪设计.html`，配套样式和脚本保留。React 不运行原型的 DOM 操作脚本，使用原型样式和真实 React 状态、组件重建六步交互。

前三步为需求分析、功能测试裁剪、非功能测试裁剪。五类信创技术栈决定第 2、3 步策略行，取消勾选会删除相应旧裁剪结论，并重新校核后续步骤。后端维护原型的 9.1 / 9.2 / 9.3 文案；前端从目录接口获取同一份规则。

为了生成原型中的完整指引，保留第 4～6 步工具选择、门禁及协作确认。最终 Markdown 包含需求分析、功能裁剪、非功能裁剪、工具能力、质量门禁、干系人协作六章。页面预览、复制、下载均使用生成接口返回的 `markdown`，不在前端另行拼装内容。

## 启动原项目

1. 按根 README 配好原项目依赖、`.env`、MySQL 等既有运行环境。
2. 在仓库根目录使用原后端入口：`python backend_main.py`，默认端口 `8519`。
3. 在 `frontend/` 执行 `npm ci`，再执行 `npm run dev`。
4. 打开 `http://127.0.0.1:5173`。

前端开发代理默认指向 `http://127.0.0.1:8519`，与原项目默认端口一致。若原后端运行在其他地址，启动前端前设置环境变量 `TRIMMER_API_TARGET`。生产构建执行 `npm run build`，将 `dist/` 部署为静态前端，并把 `/strategy-trimmer/` 反向代理到原后端；若分域部署，可通过构建环境变量 `VITE_API_BASE_URL` 设置接口地址，并使用原项目现有 CORS 配置。

## 仅联调新增功能

`trimmer_main.py` 是可选的测试入口，复用原项目统一响应和同一个裁剪器路由，用于缺少 MySQL / Redis 环境时验证这次新增功能。它不替代 `backend_main.py`，不引入第二套生成逻辑。

使用 Python 3.12+，安装原项目已经声明的 `fastapi`、`pydantic`、`orjson`、`uvicorn`、`httpx`、`tortoise-orm`、`aiosqlite`、`openpyxl`、`python-multipart`，执行：

```powershell
python -m uvicorn trimmer_main:app --host 127.0.0.1 --port 8519
```

前端仍按上述方式启动。

## 接口

`GET /strategy-trimmer/catalog` 返回数据库目录：五类改造类型、系统选项、功能与非功能策略、工具、六项硬性门禁、准入准出说明、默认干系人。

`POST /strategy-trimmer/generate` 接收前端本次选择，生成并保存 Markdown，返回内容、建议文件名及文档索引元数据。统一响应格式沿用仓库：

```json
{
  "code": "000000",
  "status": "success",
  "message": "请求成功",
  "data": {
    "filename": "REQ-001-测试裁剪指引.md",
    "markdown": "# 《核心系统改造测试裁剪指引》\n..."
  },
  "total": null
}
```

接口错误也沿用统一响应，可能是 HTTP 200 + `status: failure`，前端同时检查 HTTP 状态和业务状态。

请求示例：

```json
{
  "reqId": "REQ-001",
  "name": "核心系统改造",
  "duration": "6-15个工作日",
  "changes": ["database"],
  "systems": [{"name": "核心交易系统", "testDept": "是"}],
  "functionDecisions": {"database": {"status": "必测", "reason": "重点回归保留"}},
  "nfDecisions": {"database": {"status": "裁剪", "reason": "日交易量低于 2000，申请裁剪性能，保留关键读写和数据一致性验证"}},
  "toolChoices": {"automation": {"decision": "必用"}},
  "extraGates": [],
  "stakeholders": [{"role": "测试经理", "name": "项目测试团队", "duty": "确认范围、例外和结论"}],
  "collabConfirmed": true
}
```

- 改造类型：`framework / database / middleware / os / browser`，必须至少一项，不得重复。
- 测试周期：`≤5个工作日 / 6-15个工作日 / >15个工作日`。
- 裁剪结论：`必测 / 条件测试 / 裁剪`；选择裁剪必须填写备注。未传某已选类型的结论时，功能默认必测，非功能默认条件测试；不得提交未选类型的结论。
- 工具：`automation / precision / toolbox / ai / performance`；结论为 `必用 / 条件使用 / 不使用`，省略时默认条件使用。
- 六项默认硬性门禁直接纳入工件，生成指引不代表门禁实际达标。额外硬性门禁必须确认，协作状态必须为 `true`。
- 需求编号可为空，按原型输出“未填写”。涉及系统和干系人至少一项，所有文本都有长度上限。

## 不保存选择信息

不保存原始选择 JSON；生成 Markdown 文件和需求下载索引按本次新增要求保存。原项目 `logging_middleware` 在读取请求体之前跳过 `/strategy-trimmer` 应用的审计和参数日志，包括校验失败。成功响应及主后端裁剪器响应设置 `Cache-Control: no-store`。

原型“历史策略”功能保留为浏览器 `localStorage`，不发送历史保存请求到后端。只有用户点击生成时当前选择会提交；下载实际读取已保存的 Markdown 文件。

## 验证

```powershell
python -m unittest discover -s tests -v
```

自动测试覆盖 31 种非空技术栈组合、六章工件、裁剪备注、非法/过期选择、额外硬性门禁、协作确认、Markdown 转义、文件名处理、请求隔离，以及实际原路由注册函数和原鉴权 / 审计中间件函数。

浏览器联调脚本为 `frontend/tests/e2e-trimmer.js`，可用 Playwright CLI 的 `run-code --filename` 执行。需要先启动上述前后端；截图和下载证据保存在执行目录的 `.playwright-cli/`。检查六步流程、失败重试、预览、Windows 剪贴板换行、下载和本机历史及移动端溢出。

本次完整原后端启动依赖未配置的 MySQL / Redis / `.env`，实际 HTTP 与浏览器联调使用共享路由的可选测试入口；原项目路由注册和相关中间件通过针对性集成验证。

## 数据库配置、Excel 导入及最新文档查询

| 表 | 保存内容 |
| --- | --- |
| keenrobot_trimmer_config | key=strategy_catalog 的 JSON 规则配置、版本及更新时间。包含策略明细、选项、门禁与默认干系人。 |
| keenrobot_system_automation_asset | 唯一系统名称、是否有自动化资产、更新时间。 |
| keenrobot_trimmer_markdown_document | 需求编号、名称、文档 ID、下载 URL、文件名、文件存储键、配置版本及生成时间。 |

catalog.json 仅为首次初始化种子，配置已存在时不会在重启后覆盖。目录和生成接口每次查询配置表和资产表，维护规则时更新 value 和 version，保持原 JSON 结构及 Schema 支持的技术栈 ID 和选项枚举。生成以本次数据库快照渲染；前端不提交 automation 字段，篡改提交此字段会被拒绝。

原 backend_main.py 使用已有 Tortoise/MySQL 配置及迁移、数据初始化流程。已有 MySQL 部署若关闭自动迁移，启动前执行 docs/migrations/20261008-strategy-trimmer.mysql.sql；启用原 Aerich 自动迁移时使用原迁移流程建表。后续需保持原项目 Aerich 版本记录一致。

trimmer_main.py 联调入口持久化 SQLite 至 output/trimmer.sqlite3，可用 TRIMMER_DB_URL 覆盖；Markdown 默认保存到 output/docs/strategy_trimmer/，可用 TRIMMER_DOCUMENT_DIR 覆盖。数据库及文档目录是运行数据，已忽略 Git，部署需保留它们。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /strategy-trimmer/automation-assets/template | 下载两列 Excel 模板。 |
| POST | /strategy-trimmer/automation-assets/import | multipart 文件字段 file，按系统名称新增或更新资产关系。 |
| GET | /strategy-trimmer/documents/latest?reqId=REQ-001 | 按需求编号精确查询最新文档。 |
| GET | /strategy-trimmer/documents/latest?name=核心系统改造 | 按需求名称精确查询最新文档。 |
| GET | /strategy-trimmer/documents/{documentId}/download | 下载保存的该版本 Markdown。 |

Excel 工作表名为“系统自动化资产”，首行依次为“系统名称”“接口/UI自动化”，后续填系统名称及“有自动化资产”或“无自动化资产”。模板三条原型示例可修改/删除，新增行上传。文件上限 2 MB，最多 10000 条；拒绝重复名称、空名称、公式、损坏文件和非法状态。整份校验通过后在事务中写入，未出现的系统保持原关系、不删除。返回 total / created / updated。新系统立即进入系统选项，前端资产列只读，切换回页面刷新配置。

正式原工程的 Excel 导入接口沿用 token 鉴权，展示、生成、查询及下载延续公开访问方式。本机独立联调入口未加载原鉴权中间件，可访问 http://127.0.0.1:8519/docs 上传 Excel。

查询至少填写 reqId 或 name，同时传入时二者均需匹配，按 created_at DESC、id DESC 返回最新版本。每次成功生成保存新文档，旧下载地址仍可访问。找不到文档或文件不可用时返回业务失败。

生成响应 data 新增 documentId、downloadUrl、createdAt、reqId、name、configVersion，仍包含 markdown 和 filename。查询返回同样元数据，不附全文。下载读取对应存档，后续规则变化不会重算历史版本。浏览器新增“查询文档”弹窗，与本机“历史策略”分开。

新增测试覆盖真实 SQLite 配置即时生效、种子不覆盖、Excel 新增/更新和错误批次不写入、资产防篡改、编号/名称最新查询、旧版下载、重启持久化及索引失败文件清理。浏览器联调覆盖资产只读和按编号/名称查询下载；实际联调为 SQLite，正式 MySQL/Redis 全工程运行环境尚未配置。
