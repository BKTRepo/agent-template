---
title: 知识库转换任务与技能挂载接入
status: implemented-local
last_updated: 2026-11-06
---

# 知识库转换任务与技能挂载接入

后端 dev-zyl 已合并 zdhgj-znfw-uat（b142896）。本次将独立转换任务关联到平台知识库，继续复用解析、术语、摘要、分块、Embedding 和 Milvus 流水线，不重复投递入库任务。技能挂载由现有保存服务统一生成版本和资源关联。

## 当前接口

业务请求携带平台 token 请求头。GET 编号均在查询参数；POST 编号和字段均在 JSON 或 form-data。

| 方法 | 路径 | 输入及用途 |
| --- | --- | --- |
| POST | `/api/convert` | form-data：file；PDF、DOCX、XLSX、MD、TXT；返回 data.job_id |
| GET | `/api/convert/status?job_id=...` | 查询阶段；仅 data.status=complete 表示入库完成 |
| POST | `/api/convert/retry` | JSON：job_id；原任务重试，关联知识库的任务也可使用，需维护权限 |
| GET | `/api/documents/markdown?job_id=...` | 解析 Markdown |
| GET | `/api/documents/terminology?job_id=...` | 术语产物 |
| GET | `/api/documents/chunks?job_id=...` | 最终分块 |
| GET | `/knowledge-bases/list?search=...&application=...&maintainer=...&offset=0&limit=10` | 公开及本人知识库；名称、所属应用、维护人组合筛选，默认及最大每次 10 条，按更新时间和编号倒序；外层 total 为权限及筛选后的总数 |
| GET | `/knowledge-bases/detail?kb_id=...` | 详情、文档状态、转换 job_id、历史及引用数 |
| POST | `/knowledge-bases/create` | form-data：source JSON，含 conversion_job_ids |
| POST | `/knowledge-bases/save` | form-data：kb_id、source；含 expected_version、retained_document_ids、新 conversion_job_ids |
| POST | `/knowledge-bases/retry` | JSON：kb_id、可选 doc_id；兼容旧平台文档任务 |
| GET | `/knowledge-bases/documents?kb_id=...` | 库内文件 |
| GET | `/knowledge-bases/history?kb_id=...` | 编辑历史 |
| GET | `/knowledge-bases/documents/preview?kb_id=...&doc_id=...` | 解析文本预览 |
| GET | `/knowledge-bases/documents/download?kb_id=...&doc_id=...` | 鉴权后下载原文件 |
| POST | `/knowledge-bases/documents/save-content` | JSON：kb_id、doc_id、content、change_summary、expected_generation |
| GET | `/knowledge-bases/chunks?kb_id=...&offset=0&limit=100` | 平台文档分块 |
| POST | `/skills/developer/save-skill` | JSON：skill_id + 完整 DeveloperSkillForm；现有技能更新入口 |

旧知识库 PUT/动态编号路由及转换状态动态路径已替换，前后端需同步更新。WRQ 接口清单见 applications/wrq/API_CONVENTIONS.md；同事沙箱契约未批量改写。

列表筛选：`search` 按知识库名称模糊匹配；`application` 使用应用代码，选择具体应用时包含全应用适用（`*`）的知识库；`maintainer` 按最近编辑历史中的维护人显示名称或其账号模糊匹配，历史未记录维护人时回退到创建者。维护人输入中的 `%`、`_` 按普通字符处理。所有条件同时成立，先验证可见范围并筛选，再统计总数和分页；解析重试不会更换维护人。

## 创建与任务关联

前端逐文件调用 convert 后，用 form-data 的 source 字符串提交元数据，例如：

```json
{
  "knowledge_name": "交易规则",
  "description": "",
  "tag": "general",
  "application": "",
  "is_public": false,
  "conversion_job_ids": ["doc-example"]
}
```

编辑附带 expected_version 和 retained_document_ids，新增或同名替换的原文件使用保存接口 files 字段，进入同一迁入流水线；避免 convert 的全局文件名唯一规则阻止同名修改。同一请求不能混用 files 与 conversion_job_ids。

conversion_links.py 校验任务所有权、原文件哈希和归属，建立 RagDocument.knowledge_document_id 与平台 Document 的关系；任务只能归属一个知识库。原文件复制为受控快照，转换任务不再次解析或入库。详情/状态查询同步实际阶段；仅 complete 且真实分块产物可用时将平台文档标为 completed，保存解析文本与 DocumentChunk。

创建响应丢失时，相同任务和相同元数据返回已建知识库；不同元数据提示刷新编辑，避免静默覆盖。前端同一会话保存失败后复用已返回 job_id。浏览器 store 不持久化模拟业务记录。

## 挂载与状态

### 知识库更新的持久化提醒

2026-11-06 提醒显示在左侧“开发者中心”导航及“我创建的技能”名称旁。导航红色数字按本人有未读更新的技能去重，
不依赖当前列表页；技能红色感叹号使用“该技能挂载的知识库已发布新版本，请同步更新”。
当前知识库没有独立发布步骤，因此这里的新版本指实际保存引起的 `revision` 递增；处理状态独立展示。

`keenrobot_skill_knowledge_notifications` 按接收人、技能、知识库唯一，保存 `latest_revision`、
`read_revision`、最新变更摘要和更新时间/已读时间。`latest_revision > read_revision` 表示未读。
接收人统一由 `knowledge_notification_service.recipients` 解析技能创建者，后续可替换团队策略。
列表当前页的 `knowledge_update_count` 批量查询；详情、统计及已读均校验本人技能、当前有效挂载及知识库访问权限。

知识库实际升版与提醒在同一事务提交；无修改保存、仅填写摘要、处理重试与完成/失败状态变化不增加提醒。
关联表新增 `knowledge_mount_revision`：首次挂载以当前版本为基线，连续挂载在新技能版本中继承基线，
普通技能保存保留未读。解除挂载移除提醒；重新挂载创建新提醒编号与新基线，排除历史技能版本的挂载。
涉及挂载的保存先按编号锁知识库，再锁技能、检查技能修订号，避免更新与挂载并发时漏提醒。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/skills/developer/get-knowledge-update-summary` | 全部本人技能的未读汇总及 `skill_counts` |
| GET | `/skills/developer/get-knowledge-updates?skill_id=14` | 未读详情、已读/最新版本、摘要及实时文档状态 |
| POST | `/skills/developer/mark-knowledge-updates-read` | JSON：`skill_id`、`items: [{notification_id, seen_revision}]`，一次最多100项 |

已读只推进到本次看到的版本，不能超过提醒最新修订号；旧请求不回退已读版本，重复请求幂等。
例如看到了修订号1而后台已升到2，确认1后2仍未读。全部标记按页面当时的快照分批提交。
阅读、悬浮、进入页面不自动已读；已读不修改技能修订号、构建或发布状态，也不代表已同步资源。
界面每15秒及恢复焦点时刷新汇总，切换账号清空缓存并丢弃旧请求；数据库保存已读，刷新/重登后仍有效。

部署前显式执行增量迁移（启动不自动建表）：

```powershell
.\.venv\Scripts\python.exe -m applications.wrq.migrations.knowledge_notifications
.\.venv\Scripts\python.exe -m applications.wrq.migrations.knowledge_notifications --apply
```

迁移要求TLS，备份关联表DDL到工作区 `.tmp/knowledge-notification-migration`，新增表/字段及查询索引。
已有当前挂载按当前知识库版本初始化为已读，不补发历史更新；重复执行不重置已有提醒的已读状态。

2026-11-06 验收：提醒增量迁移已应用；12项提醒定向测试、30项知识库关联/保存回归、
14项当前挂载权限/技能目录回归通过，前端92项测试和正式构建通过。
真实浏览器验证导航红色气泡、技能感叹号、旧版本已读保留并发新提醒、全部已读清除、刷新和重登持久化，
确认读取提醒不改变技能修订号。提示框复用现有转换状态同步，即使知识库列表不在当前页，也会查询实际文档状态。
额外旧脚本 `tests/test_developer_center_crud.py` 仍引用已移除的 `DeveloperApplication`，不能收集，未计入上述通过数。

2026-11-06上传限制调整：一个知识库的有效文件合计不得超过200 MB（200×1024×1024字节），恰好等于上限允许提交。前端上传区显示单文件及总大小上限，并在创建转换任务前拦截超限。后端对直接上传的流式暂存、转换任务原件的合计大小以及编辑后的最终文件集合分别校验；最终集合包含保留文件和新文件，同名替换只计算新文件大小，删除的文件不再计入。超限返回字段files的参数错误，回滚本次修改并清理暂存副本，不修改原文档和版本。转换任务原件不因知识库提交失败而删除。

前端展示本人创建的所有状态技能，复用开发者中心前五列（实现名称、技能类、所属应用、版本、状态），每页10条，维护人固定为当前登录人。技能类仅用于筛选；2026-11-05确认改为只挂载勾选的具体实现，不再扩展到同类全部实现。读取本人技能列表分页后重新核对所选编号的归属，对每个未挂载的勾选目标调用现有 save-skill，保留完整表单、expected_revision、原 resource_ids、knowledge_bases、上传文件、指令及环境，只合并新知识库。

保存服务维护 keenrobot_skill_resource_bindings：source_type=knowledge_base、source_id=知识库 ID，关联各自 skill_id、skill_version_id。没有新增挂载表、自定义批量数据库写入接口或绕过技能保存服务的路径。

2026-11-06：同一技能版本内，同一知识库 ID 只允许挂载一次。开发者表单选择按编号去重，
知识库挂载弹窗将已挂载技能标记并禁选，全选跳过这些技能；提交时仍重新查询目标最新资源。
技能创建/保存接口拒绝 resource_ids 或 knowledge_bases 各自列表中的重复编号，数字、
数字字符串及前导零均按同一整数编号校验。正常编辑时携带一份已有挂载可继续保存，
每个历史版本仍保留自己的资源快照，不对 skill_id/source_id 添加跨版本全局唯一约束。
名称相近但编号不同的知识库是不同资源，不按名称合并或删除。

多个 HTTP 保存独立成功/失败，准确报告成功、已存在和失败明细；重试刷新全部分页，已保存项跳过。这不是跨请求的整批事务，不承诺全部回滚。当前保存接口生成新版本并转为 DRAFT，需重新构建、调试和发布，页面有明确提示。

## 隔离与验证

### 数据库连接池与任务失败状态

接口、通用启动入口和 Celery Worker 统一使用 `DATABASE_POOL_MIN_SIZE=1`、
`DATABASE_POOL_MAX_SIZE=10`（2026-11-06 调整），可通过 `.env` 调整；最小值不得大于最大值。
WRQ 入口不再覆盖这两个参数。每个进程分别建池，同一数据库账号下各进程、
其他部署及运维工具的连接数均累加，需预留重启时新旧进程重叠的额度。
应用启动不会修改 MySQL 全局或账号连接限额；服务端参数由单独的管理操作维护。

2026-11-06 按用户授权，经 SSH 在应用专用的 23306 实例执行管理操作：
`SET PERSIST max_connections=151`，并将 `zdhgj`@`%` 的 `MAX_USER_CONNECTIONS`
调整为 151。已核验运行值和 `performance_schema.persisted_variables` 中的持久化值，
未改动 3306 实例；修改前备份在服务器 `/root/mysql-connection-limits-20261106-lijoEU/`。
对应管理员脚本为 `deploy/mysql-connection-limit-151.sql`，不由应用启动自动执行。

解析任务未捕获异常和超时会回写 `failed` 并向 Celery 抛出异常，不再将异常返回为成功任务。
状态回写校验当前任务编号和处理中状态，保留取消、删除、已完成及新重试任务的结果。
数据库暂不可用导致回写失败时保留错误日志，可在连接恢复后运行
`RagDocumentService.sweep_stale_documents()`，仅将确认中断且心跳过期的任务标记失败，
再通过现有重试接口或页面恢复。Windows 自定义启动脚本必须使用
`if __name__ == '__main__':` 保护启动动作，避免解析子进程重复启动 Worker。

services/resource_isolation.py 的 resolve_isolation_rule 当前实现公开或本人可读、仅本人可改。知识库维护、技能保存中的知识库校验和构建资源解析均调用该函数，后续接团队时可替换内部策略。技能目标仍限定本人创建。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_conversion_knowledge_flow.py applications/wrq/tests/test_api_conventions.py -q
```

定向测试使用 SQLite 与显式外部服务替身；前端另有接口回归和浏览器交互验证。未连接生产数据库、模型或 Milvus，未执行迁移，不代表外部服务端到端验收。

2026-11-05 连接池修复联调另行使用当前配置的真实 MySQL、Redis 和知识处理服务：
页面登录、创建私有验证知识库、上传 TXT、后台完整处理、完成状态、原文件预览、
Markdown 与分块查询均通过；11 个旧文件任务恢复完成，新验证文件完成。
核对时账号可见连接数为 8（包含临时诊断连接），实际全局上限 40、账号上限 20，
未修改数据库服务端参数。前端 67 项测试与正式构建、后端连接池/失败回写/任务身份/
知识库关联及接口约定定向测试通过。此记录不代表生产压力测试或高并发容量验收。

部署按 applications/knowledge_base/README_MIGRATION.md 准备模型、Redis Worker、Milvus；现有业务库缺少迁入处理表时，需审核、应用其中的迁移。原有技能关联表无需新增迁移。旧 Chroma/PUT 验收脚本不代表迁移后的当前接口。
