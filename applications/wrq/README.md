# WRQ 开发者中心

业务代码、显式迁移和测试均在 `applications/wrq/`。启动不建用户、不造业务数据、不自动迁移。

## 完整后端项目启动

在后端根目录执行：

```powershell
.venv/Scripts/python.exe -m applications.wrq.full_backend
```

此入口直接使用 `backend_main.app`，加载原项目全部路由与中间件，
不初始化用户、不建表、不自动迁移；公共鉴权保持原实现。
`DATABASE_AUTO_MIGRATION` 必须关闭，否则拒绝启动。云库连接池仅本进程限制为1～4连接。
接口文档：`http://127.0.0.1:8519/docs`。

原项目签发Token的接口是 `POST /base/auth/access_token`（基础服务），
不是 `/base/audit` 审计模块。该接口及完整项目公共鉴权仍依赖 `keenrobot_user`。
该表之前按要求删除，导致原项目登录及公共鉴权不可用。
2026-10-26经用户明确授权，已从删除前私有备份恢复原22列及1个管理员账号；
应用表未恢复。原项目HTTP登录签发Token及开发者中心受保护接口已实测通过。
WRQ内部仍只验证JWT，不维护另一套用户资料；完整项目外层公共鉴权继续使用原平台用户表。
恢复脚本为 `migrations/restore_platform_user_20261026.py`，仅显式 `--apply` 执行，
若已存在不同的账号记录会拒绝覆盖；不能拿它重置已经使用中的账号。

## 单模块隔离测试与凭证

在后端项目根目录执行：

```powershell
.venv/Scripts/python.exe -m applications.wrq.main
.venv/Scripts/python.exe -m applications.wrq.configure_local_token
```

上述单模块入口仅用于隔离测试，不代表整个后端已启动；与完整入口不能同时占用8519端口。
健康检查：`/health`。
凭证工具默认复用前端忽略提交的 `.env.local` 中已有、验证有效的平台JWT，
把凭证另存为用户私有目录 `.codex/private/wrq-interface-test-token.txt`，不打印Token。
若凭证过期，仅本机联调可显式添加 `--issue-test-token` 签发8小时测试凭证。
这是本地CLI，不是登录模块或对外签发接口。生产凭证由外部平台签发。

Swagger接口的 `token` 请求头粘贴文件中的内容，也支持 `Authorization: Bearer ...`。
`auth.py` 校验固定算法、签名、有效期、用户编号和令牌内的状态；不查询本地用户表。
当前仅实现JWT校验，不实现跨平台用户资料获取、历史用户衔接或平台实时吊销查询。

尚未配置外部应用目录时，只提供“全应用适用”，不生成虚假应用清单。
已有业务记录中的应用编号保留。后续目录可通过 `WRQ_PORTAL_APPLICATIONS_URL` 对接。

## 任务开始时登记版本

1. 前端固定本次实际使用的构建及版本，再调用同事的 `POST /realtime-test-case-gen/runs`。
2. 取得 `run_id` 后立即调用我方登记接口，无须等待任务完成。

```http
POST /skills/developer/{skill_id}/debug-runs
token: <平台JWT>
Content-Type: application/json

{
  "run_id": "同事创建接口返回的任务编号",
  "build_id": "本次实际使用的构建编号",
  "conversation_input": "本次对话输入",
  "request_document_count": 1
}
```

`status` 不必传。后端核对同事表的任务确实属于该技能，再定位构建对应的保存版本。
`queued/running` 可以登记；重复登记相同关联幂等，改绑其他版本返回409。
旧的 `/debug-result` 保留为兼容入口；前端传入 `passed` 不作为成功证明。

恢复窗口时，前端继续用同事的 `latest-run` 找任务，再通过
`GET /skills/developer/{skill_id}/debug-runs/{run_id}` 核对 `is_current_version`。
未登记或属于旧版本，不能认定当前版本测试通过。登记失败时用原run_id重试，不能重新启动任务。
前端创建、轮询、找回和下载的四个同事接口保持原协议；本次未改同事服务及前端流程。

## 数据一致性

- 版本表10列元数据，表单表10列正文，一版一条；保存修改生成新版本。
- 技能、版本、表单、挂载在同一事务保存；修订检查和行锁防止旧页面覆盖。
- MySQL复合外键约束当前版本与修订、版本归属和文件归属；名称唯一只覆盖未删除记录。
- 来源 `source_type` 与用途 `category_id` 分开。上传保存真实大小、扩展名、MIME和SHA256。
- 文件换版保持旧版本与原件；构建和下载核对摘要。
- 上下线状态、启用字段、时间及操作历史同一事务更新；上线后修改回草稿。
- 任务关联表保存版本、构建和我方输入等信息；状态、结果位置和执行时间只读同事表。

## 迁移与测试

`migrations/review_20261026.py` 已显式执行。影子表逐值/外键验证后原子换表，保留44份版本。
`migrations/drop_local_identity_20261026.py` 默认只读；显式执行前先把自建用户/应用表
全量备份到用户私有目录，检查实际外键，再删除指定表。不修改同事结果表或审计、aerich。
已迁移的库不要再次套用旧结构迁移。

隔离测试在 `tests/test_developer.py`、`test_token_auth.py`、`test_migration_20261026.py`。
真实云库路由验收：

```powershell
.venv/Scripts/python.exe -m applications.wrq.tests.live_review_20261026 --live
```

除沙箱执行边界外，认证、HTTP路由、数据库事务、构建和文件均真实执行。
沙箱只在独立测试进程注入，不写同事表；测试结束清理本次UUID标识的测试数据与文件。

### 调试后续流程及实际前端API验收

```powershell
.venv/Scripts/python.exe -m applications.wrq.tests.live_debug_lifecycle_20261026 --live
```

37项用例先定义在 `tests/debug_lifecycle_cases.py`（含前端关闭后恢复与旧版结果隔离）。本命令在临时端口启动真实WRQ路由，
验证真实JWT、TLS云MySQL、ZIP构建、登记、恢复、失败/过期拦截、上线下线和版本失效；
并运行前端 `scripts/test-debug-cloud.mjs`，让实际前端API函数通过真实TCP访问测试服务。
只替代沙箱的任务状态及测试Excel；不修改运行中的完整项目公共鉴权或同事任务表。
前端Node测试中，浏览器文件缓存使用测试存储，不代表完成了浏览器UI/关闭刷新验收。

报告：工作区 `deliverables/开发者中心_调试后续流程测试结果_20261026.html` 及同名JSON。
2026-10-26恢复平台鉴权用户表并修复前端新建任务及开始登记流程后，已重新执行全部37项，全部通过。
前端 `npm test` 另有42项通过。沙箱状态和结果Excel使用mock，后续业务真实执行，
这不代表同事实际模型执行服务已联调通过；当前前端配置的同事服务暂不可连接。
存在失败或阻塞时命令返回非零，不能当成全流程通过。
结束硬清理本轮随机前缀的自有测试记录、构建及临时文件，并逐表复核既有数据和结构；
自增计数自然前进，不重置共享库的自增值。允许运行中的完整项目追加正常审计日志，
通过原审计行集合及哈希校验其原有记录没有被修改；不会将正常追加日志误认为测试改了业务数据。
