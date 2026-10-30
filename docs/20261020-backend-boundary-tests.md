# 后端边界、故障注入与修复报告

2026-10-21 更新：此前未迁入的知识库完整删除机制已完成本项目适配，完整后端 268 项通过，真实 Redis／双 Worker 自动重试验证通过。本文旧的“尚未迁入／单进程”描述保留为历史，请以 [最新迁移方案](20261021-knowledge-deletion-migration.md) 为准。


日期：2026-10-20；范围：Skill 解析引擎与个人知识库后端。本轮没有修改前端、源 RAG 工作区或生产数据库，没有提交、推送或部署。

## 1. 结果

| 批次 | 通过 | 失败 | 跳过 | 证据 |
| --- | ---: | ---: | ---: | --- |
| 首轮新增边界测试 | 17 | 11 | 0 | before.xml |
| 首次修复及相关回归 | 61 | 0 | 0 | after.xml |
| 最终新增边界测试 | 39 | 0 | 0 | final-boundaries.xml |
| 完整后端 | 246 | 0 | 0 | full.xml，45.45 秒 |

完整后端为原有 207 项加新增 39 项，不能将各批次重复相加。12 条警告为既有依赖弃用警告。首轮 11 个失败是参数化用例数量，不等于 11 个独立缺陷。

测试涉及真实 API 路由、ORM／SQLite、文件系统。外部故障使用显式替身注入；真实模型／Chroma 另有集成复验，不人为中断真实服务。

## 2. 问题与修复

| 编号 | 原问题或体验缺口 | 修复 |
| --- | --- | --- |
| D1 | 原文件被占用时只记日志，仍可能删除 SQL 记录 | 严格清理；失败保留记录、错误和重试入口，完成后最后删 SQL |
| D2 | 越界路径被跳过后仍当作清理成功 | 保留失败记录，不触碰外部文件，不假报成功 |
| D3 | 重试错误／跨库文档返回无任务 409 | 按知识库范围验证存在性，返回 404 |
| D4 | 旧解析回调可再次处理已移除文档 | 领取及关键写回检查 is_deleted 和 generation |
| D5 | 解析中移除直接被拒绝，未复用源 RAG 已有体验 | 先标删除、递增代次；同文档锁协调在途写入，清理后不留晚到索引 |
| D6 | NaN、无穷、字符串、布尔向量可能被当作成功 | 数量、非空、维度和有限数值校验；失败保留 Markdown 预览 |
| D7 | 页面没有独立的删除失败任务可展示 | 增加 cleanup_tasks：deleting／delete_failed、错误、can_retry |
| D8 | 向量删除未确认是否真正完成 | Chroma delete 后按 ID 查询，有残留报失败，不继续删原文件与 SQL |

D5 是对既有 RAG 行为的补齐；D7、D8 是复现后追加的恢复／确认保护。本轮沿用 DocumentStatus.PROCESSING／FAILED 存储，响应中映射删除状态，没有增加数据库字段。

修改：platform_service.py（严格清理、失败恢复、任务回显、ID 范围校验），document_pipeline.py（旧代次保护、向量验证、清理确认），document_lock.py（单进程同文档锁），test_backend_boundaries.py（用例）。均在 applications/knowledge_base/services/ 或 tests/ 下。

## 3. 最终 39 个实例

所有实例通过。表中节点对应 tests/test_backend_boundaries.py，可单独选取复现。

| 编号 | 场景 | pytest 节点 | 结果 |
| --- | --- | --- | --- |
| B01 | 文件被占用，保留记录并成功重试 | `test_delete_file_in_use_retains_record_and_exposes_retry` | 通过 |
| B02 | 向量清理失败不丢原文件及其他文档 | `test_delete_vector_failure_preserves_file_and_does_not_block_other_document` | 通过 |
| B03 | 缺失文件幂等；越界文件不能假报成功 | `test_delete_missing_file_is_idempotent_but_outside_path_is_not_success[False]` | 通过 |
| B04 | 缺失文件幂等；越界文件不能假报成功 | `test_delete_missing_file_is_idempotent_but_outside_path_is_not_success[True]` | 通过 |
| B05 | 未知或跨库文档重试返回404 | `test_retry_unknown_or_cross_base_document_returns_not_found[unknown]` | 通过 |
| B06 | 未知或跨库文档重试返回404 | `test_retry_unknown_or_cross_base_document_returns_not_found[other-base]` | 通过 |
| B07 | 旧解析回调不复活已移除文档 | `test_raw_parse_callback_cannot_resurrect_deleted_document` | 通过 |
| B08 | 解析中移除，防止晚到向量残留 | `test_remove_processing_document_fences_late_worker_and_leaves_no_vectors[embed]` | 通过 |
| B09 | 解析中移除，防止晚到向量残留 | `test_remove_processing_document_fences_late_worker_and_leaves_no_vectors[put]` | 通过 |
| B10 | 无效向量不标记完成，保留预览 | `test_invalid_embedding_is_reported_and_never_saved_as_completed[vectors0]` | 通过 |
| B11 | 无效向量不标记完成，保留预览 | `test_invalid_embedding_is_reported_and_never_saved_as_completed[vectors1]` | 通过 |
| B12 | 无效向量不标记完成，保留预览 | `test_invalid_embedding_is_reported_and_never_saved_as_completed[vectors2]` | 通过 |
| B13 | 无效向量不标记完成，保留预览 | `test_invalid_embedding_is_reported_and_never_saved_as_completed[vectors3]` | 通过 |
| B14 | 部分写入及清理失败可恢复 | `test_partial_vector_write_and_cleanup_failure_are_recoverable` | 通过 |
| B15 | 单文件上限前、等于及超过1字节 | `test_skill_single_upload_exact_limit_and_one_byte_over[7-True]` | 通过 |
| B16 | 单文件上限前、等于及超过1字节 | `test_skill_single_upload_exact_limit_and_one_byte_over[8-True]` | 通过 |
| B17 | 单文件上限前、等于及超过1字节 | `test_skill_single_upload_exact_limit_and_one_byte_over[9-False]` | 通过 |
| B18 | 合计上限前、等于及超过1字节 | `test_skill_aggregate_exact_limit_and_one_byte_over[3-True]` | 通过 |
| B19 | 合计上限前、等于及超过1字节 | `test_skill_aggregate_exact_limit_and_one_byte_over[4-True]` | 通过 |
| B20 | 合计上限前、等于及超过1字节 | `test_skill_aggregate_exact_limit_and_one_byte_over[5-False]` | 通过 |
| B21 | 失败编辑保留版本与旧包下载 | `test_invalid_edit_preserves_previous_skill_version_and_download[stale-version]` | 通过 |
| B22 | 失败编辑保留版本与旧包下载 | `test_invalid_edit_preserves_previous_skill_version_and_download[blank-usage]` | 通过 |
| B23 | 失败编辑保留版本与旧包下载 | `test_invalid_edit_preserves_previous_skill_version_and_download[missing-classification]` | 通过 |
| B24 | 坏文件名清理此前已暂存文件 | `test_knowledge_bad_filename_cleans_earlier_staged_file[../escape.md]` | 通过 |
| B25 | 坏文件名清理此前已暂存文件 | `test_knowledge_bad_filename_cleans_earlier_staged_file[bad\\path.md]` | 通过 |
| B26 | 坏文件名清理此前已暂存文件 | `test_knowledge_bad_filename_cleans_earlier_staged_file[NUL.md]` | 通过 |
| B27 | 坏文件名清理此前已暂存文件 | `test_knowledge_bad_filename_cleans_earlier_staged_file[bad.md.]` | 通过 |
| B28 | 旧代次编辑不覆盖较新原文件 | `test_stale_generation_editor_does_not_replace_newer_original` | 通过 |
| B29 | 删除后查询确认有无向量残留 | `test_chroma_delete_checks_for_residual_vectors[remaining0]` | 通过 |
| B30 | 删除后查询确认有无向量残留 | `test_chroma_delete_checks_for_residual_vectors[remaining1]` | 通过 |
| B31 | 重复删除回调只清理一次 | `test_repeated_delete_callbacks_only_clean_once` | 通过 |
| B32 | 单文档锁不阻塞其他文档 | `test_waiting_for_one_document_does_not_lock_another` | 通过 |
| B33 | 处理中替换返回冲突，保留原文件 | `test_replacing_processing_file_returns_conflict_and_preserves_original` | 通过 |
| B34 | 向量数量及维度不匹配 | `test_embedding_count_and_dimension_mismatch_keep_parsed_preview[vectors0]` | 通过 |
| B35 | 向量数量及维度不匹配 | `test_embedding_count_and_dimension_mismatch_keep_parsed_preview[vectors1]` | 通过 |
| B36 | 向量数量及维度不匹配 | `test_embedding_count_and_dimension_mismatch_keep_parsed_preview[vectors2]` | 通过 |
| B37 | 实际50MiB允许，超1字节拒绝 | `test_actual_50mib_file_is_allowed_and_one_extra_byte_is_rejected` | 通过 |
| B38 | HTTP下载拒绝被篡改文件或ZIP | `test_download_rejects_corrupted_package_through_http[file]` | 通过 |
| B39 | HTTP下载拒绝被篡改文件或ZIP | `test_download_rejects_corrupted_package_through_http[zip]` | 通过 |

上传小额度测试覆盖上限前／等于／超 1 字节，还有实际 52,428,800 字节允许、52,428,801 字节拒绝的 HTTP 用例。失败保存同时检查旧版本和旧下载不受影响，不只断言“有错误”。

## 4. 用户习惯与前端待办

后端已提供：中文字段错误；失败不丢原版本；同内容重传不重复索引；过期编辑有冲突；处理中文档可移除；删除失败可显式恢复。

前端接入后还要验收：

1. 显示 cleanup_tasks 的清理中／删除失败及重试，不把文件列表隐藏当作物理删除完成。
2. processing 持续轮询；failed 展示文档或清理错误；completed 才停止。
3. 409 保留当前编辑内容，提示刷新／比较，不能默默覆盖或清空。
4. 补大类、应用、分类和 expected_version 的真实请求及错误映射。
5. 知识库失败不静默以 Mock 冒充成功，统一端口和平台 token。

这些是阅读前端代码后记录的接线要求，本轮未修改或测试浏览器交互。

## 5. 真实链路复验

执行 examples.verify_platform_backend --user-scenarios，run_id 为 b858ab77，结果 PASS。使用本机 SQLite、真实文档、真实 Embedding、独立 Chroma，不连接源 RAG 数据库。

| 项目 | 结果 |
| --- | --- |
| 知识库 ID | f014a288-2f74-4033-9aa9-64fd238db77b |
| 知识库最终版本／文件数 | V1.0.5／2 |
| 增量行为 | 元数据不重建索引，文本编辑仅重建对应文件 |
| 用户场景 | 双文件内容互换、移除后同内容改名、同内容重传 |
| Skill 版本 | 1.0.2 |
| 最终 build_id | 7069a80f761e411381b8f22cfd789441 |
| ZIP | 6 个文件，图片原字节一致 |
| 实际沙箱执行 | 否 |

此链路实际经过知识库移除和 Chroma 删除后的查询确认。文件被占用、向量不可用等错误在隔离测试中注入，未破坏真实外部服务。

## 6. 复现与证据

在后端目录执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backend_boundaries.py -q
.\.venv\Scripts\python.exe -m pytest -q --junitxml=output/skill-scope-check/boundary-tests/full.xml
.\.venv\Scripts\python.exe -m examples.verify_platform_backend --user-scenarios
```

JUnit 文件在 output/skill-scope-check/boundary-tests/，真实链路报告在 output/platform-integration/verification.json。output 被 Git 忽略，证据本机保留，未自动提交。

## 7. 尚未证明的内容

- 当前是单进程文档锁、BackgroundTasks 和显式重试，未迁入源 RAG 完整 Celery／Redis 删除系统。多 Worker、跨实例、自动重试及崩溃恢复须部署前设计和验收。
- 取消在安全检查点生效，不会立即强杀解析线程或模型请求；同文档在途操作可能需要等待。
- 同名替换后旧路径 best-effort 清理失败仍只记日志，需维护清理或后续持久清理任务；与已修复的文档移除任务不同。
- 正式 MySQL、统一会话、浏览器完整交互、旧 DOC／扫描 PDF OCR、真实 Agent 和发布流程均未由本轮测试证明。
- 测试通过表示已覆盖场景通过，不保证所有输入和部署方式没有问题。

交接：[最新完整版手册](C:/Users/DELL/Documents/ChatGPT/智能服务调度集/deliverables/开发者中心_前后端实施与联调交接手册_最终版.md)。
