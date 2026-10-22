# 知识库删除修复：完整流程迁移与验证

更新：2026-10-21。用户明确要求把此前未迁入的删除机制全部适配过来。本轮不修改前端，不操作源 RAG 工作区和正式 MySQL，不提交／推送／部署服务器。

## 1. 原因和当前结论

此前仅复用 RAG 文档解析、分块及原生 PDF 转换器，未迁入其完整删除服务。当前平台自行适配的清理函数吞掉文件异常，是“文件未删但 SQL 被删”的直接原因。上一轮 39 项边界修复补上单进程保护，仍缺独立队列、跨进程协调和自动重试。

本轮已把这些机制接入现有 Celery／Redis，并适配当前 Document 表和 Chroma：

| 需求 | 当前实现 | 证据 |
| --- | --- | --- |
| 删除不排在解析后面 | knowledge_parse 和 knowledge_delete 两个队列、两个独立 Worker | 真实解析槽占用时删除仍执行 |
| 正在解析的文档可取消 | 数据库 is_deleted／generation 信号；心跳检查；转换器 should_cancel；回收本任务独占子进程 | Docling 两种取消测试、普通解析取消测试 |
| 跨进程防止删除和写入并发 | 共用严格 Redis 租约、定期续期、所有者 token 校验释放 | Redis 不可用／锁忙不降级，续期失效停止写入 |
| 临时故障自动重试 | Celery retry/countdown，最多 12 次，间隔 2、4、8、16、30…秒 | 真实文件占用后自动恢复；用例验证耗尽 |
| 明确失败和手动重试 | deleting／delete_failed，重试计数、下次时间、错误类型、can_retry | 持久 SQL、详情 cleanup_tasks、单文档 retry |
| 清理完成后才删 SQL | 按 doc_id 清全部向量并确认无残留 → 文件及解析产物 → SQL | 真实 Chroma／文件／SQL 核验 |
| 提交或 Worker 崩溃后恢复 | 数据库持久任务意图、generation 消息隔离、Beat 失联巡检 | 锁、时间、终态、恢复上限用例 |
| 替换后旧路径清理 | cleanup_file_paths 持久记录，后续严格清理 | 不再只有日志而丢失路径 |

不是把 Milvus 服务硬复制到 Chroma；源项目的队列、取消、锁、重试和清理顺序已适配到本项目。没有迁入与本任务无关的问答、术语、多模态分析等模块。

## 2. 源码来源和当前文件

来源仍是 D:/projects/agent-template-release-qoder，分支 release/qoder-worker-db-20260930 的本地工作树，包含未提交修复。

对照文件：rag_service.py（删除工作流和异常分类）、rag_pipeline.py（同文档锁／取消）、task_rag_pipeline.py（同步 Celery retry）、task_rag_maintenance.py（巡检）、docling_native.py（取消回收）、DOCUMENT-DELETION.md 与 test_deletion_recovery.py。来源哈希及当前适配说明已追加到 rag/PROVENANCE.json。

本项目主要文件：

| 文件 | 作用 |
| --- | --- |
| services/job_control.py | 严格分布式租约、续期、取消监测 |
| services/cancellable_parser.py | 普通格式解析子进程，取消回收进程树 |
| services/document_jobs.py | 派发、执行、删除进度和巡检恢复 |
| services/document_pipeline.py | 文档解析接入取消、原生产物登记、按文档删除向量 |
| services/platform_service.py | 删除意图、状态／重试、严格清理和旧路径记录 |
| celery_scheduler/tasks/task_knowledge.py | 解析、删除、巡检 Celery 入口 |
| configure/celery_config.py | 队列路由、Beat 每 60 秒巡检 |
| deploy/knowledge_workers.sh | 分别启动解析和删除 Worker |

services 文件相对于 applications/knowledge_base/。Celery 同步任务入口在请求线程调用 retry，ORM 协程仍使用项目常驻事件循环，避免在线程间读取错误的 Celery request。

## 3. 默认方式与部署

正式默认 KNOWLEDGE_TASK_MODE=celery。数据库存文件路径、代次、任务 ID、投递时间、重试时间和次数；消息只携带文档 ID 与 generation。Redis 不可用不会退回 Web 执行或假报成功，提交失败保留为明确可重试失败。

inline 只保留给单机演示／隔离测试；examples/platform_backend_server.py 的 8520 是这种模式，不能拿它证明自动重试和跨进程能力。真实队列独立验证入口为 examples/knowledge_queue_server.py，端口 8530；独立 Redis 为 6398，不与原 RAG 共用。

正式 Linux 部署：

```bash
# API、Worker、Beat 使用相同配置、数据库、上传目录、解析产物和向量存储。
# 先审查并执行数据库迁移，再重启 API。
bash celery_deploy.sh restart
bash celery_deploy.sh status
```

脚本现在会启动既有 default Worker、knowledge_parse Worker（threads/1）、knowledge_delete Worker（threads/2）和 Beat。也可独立 `bash deploy/knowledge_workers.sh start`，但仍须另外运行 Beat。

不得让一个 Worker 同时消费解析和删除以代替两个进程。Redis 是任务协调依赖，不是随意可省略的组件。当前 Chroma 为同机共享目录，分布式多主机不能用各机器独立目录冒充同一向量库，需统一服务端存储方案。

数据库升级顺序：先上一批 20261020-knowledge-platform.sql，再本轮 20261020-knowledge-deletion-jobs.sql。新增字段不得重复 ADD；先备份和测试，不自动改正式 MySQL。旧 is_deleted + failed/processing 会迁为 delete_failed/deleting。

## 4. 用户能看到什么

删除受理后从 documents 隐藏，cleanup_tasks 中仍显示：

```json
{
  "document_id":"实际ID",
  "filename":"rules.md",
  "status":"deleting",
  "error_message":"删除暂未完成，2 秒后自动重试",
  "can_retry":false,
  "retry_count":1,
  "next_retry_at":"服务器返回的时间",
  "error_type":"RetryableDeletionError"
}
```

自动重试耗尽或永久路径错误显示 delete_failed、can_retry=true；创建者用原单文档 retry 接口重置次数并重新提交。失败不能当作解析失败重新跑原文档。详情整体 processing 持续轮询，明确终态失败可停止轮询并显示重试。

前端本轮未修改，仍须接这些状态。后端完整流程完成不等于页面删除按钮已实际验收。

## 5. 验证结果

本轮新增 22 项迁移专项用例全部通过；完整后端 268 项全部通过、0 失败、0 跳过，12 条既有依赖弃用警告。记录：output/knowledge-queue-migration/queue-tests.xml、full.xml。

覆盖独立队列、消息仅 ID／代次、Broker 失败、锁忙／Redis 故障、租约丢失、解析产物和旧文件清理、永久路径错误、过期消息、定时重试和耗尽、Beat 恢复与限额、跨进程取消信号、Docling 主动取消／协程取消及普通解析回收。

真实 Redis＋两个 Celery Worker＋HTTP＋真实 Embedding／Chroma 验证：

```powershell
# 独立验证 API 和 Worker 事先按说明启动，Redis 6398 仅监听本机。
.\.venv\Scripts\python.exe -m examples.verify_knowledge_queue
```

run_id=b850a50f，knowledge_id=faf39830-c298-4fbc-bb4e-1e074adb4fcd，结果 PASS：

1. 创建并完成两个合成文档真实索引。
2. 占用解析 Worker 执行槽，同时用 Windows 句柄占用目标原文件。
3. 删除 Worker 独立执行，遇文件占用；SQL、文件保留，观察到 retry_count=1。
4. 释放句柄后，未点击人工重试，Celery 自动完成清理。
5. 实际检查原文件、SQL、Chroma 均无该文档残留。

报告：output/knowledge-queue-integration/verification.json。该目录含本机凭据和合成数据，已被 Git 忽略，不提交。

尚未执行正式 MySQL／Linux 发布、真实 OCR 模型内容质量验收及前端删除交互。取消进程生命周期使用轻量替身验证原生子进程确被回收，不把它冒充真实 OCR 成功测试。原有 Skill 测试继续通过。
