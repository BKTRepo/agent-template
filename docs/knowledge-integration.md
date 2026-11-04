---
title: 知识库转换任务与技能挂载接入
status: implemented-local
last_updated: 2026-11-04
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
| GET | `/knowledge-bases/list?search=...&offset=0&limit=100` | 公开及本人知识库；保留外层 total |
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

前端多选抽象类，读取本人技能列表的全部分页，筛选所选类下本人全部实现。对每个未挂载目标调用现有 save-skill，保留完整表单、expected_revision、原 resource_ids、knowledge_bases、上传文件、指令及环境，只合并新知识库。

保存服务维护 keenrobot_skill_resource_bindings：source_type=knowledge_base、source_id=知识库 ID，关联各自 skill_id、skill_version_id。没有新增挂载表、自定义批量数据库写入接口或绕过技能保存服务的路径。

多个 HTTP 保存独立成功/失败，准确报告成功、已存在和失败明细；重试刷新全部分页，已保存项跳过。这不是跨请求的整批事务，不承诺全部回滚。当前保存接口生成新版本并转为 DRAFT，需重新构建、调试和发布，页面有明确提示。

## 隔离与验证

services/resource_isolation.py 的 resolve_isolation_rule 当前实现公开或本人可读、仅本人可改。知识库维护、技能保存中的知识库校验和构建资源解析均调用该函数，后续接团队时可替换内部策略。技能目标仍限定本人创建。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_conversion_knowledge_flow.py applications/wrq/tests/test_api_conventions.py -q
```

定向测试使用 SQLite 与显式外部服务替身；前端另有接口回归和浏览器交互验证。未连接生产数据库、模型或 Milvus，未执行迁移，不代表外部服务端到端验收。

部署按 applications/knowledge_base/README_MIGRATION.md 准备模型、Redis Worker、Milvus；现有业务库缺少迁入处理表时，需审核、应用其中的迁移。原有技能关联表无需新增迁移。旧 Chroma/PUT 验收脚本不代表迁移后的当前接口。
