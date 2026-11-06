---
title: 知识库列表返回与前端展示字段对应
status: 接口已实现，目标库七张知识库处理表已完成整数编号迁移
last_updated: 2026-11-05
---

# 知识库列表返回

GET `/knowledge-bases/list?search=...&offset=0&limit=10` 携带平台token，返回 `{code,status,message,data:[知识库记录],total}`，其中total在响应外层，为权限和搜索过滤后的总条数。limit默认10、最大10，超出上限返回422。后端只列公开或本人记录，先过滤和计数，再按更新时间、编号倒序执行offset/limit，保证相同更新时间下翻页顺序稳定。

知识库管理页面每页10条，只请求当前页，不预先读取所有页。上一页、下一页和页码切换时，经 `src/api/knowledge.ts::listKnowledgeBasesPage` 转换并替换 `knowledgeStore.knowledgeBases`；搜索由后端执行并回到第一页，空结果保留第1页。新建后刷新第一页，编辑后刷新当前页，进度轮询只更新当前页已有记录。2026-11-05调整为与开发者中心共用分页控件，页面统一纵向滚动，表格内部仅按需横向滚动，不再限制表格高度或提供第二条纵向滚动条。描述放在名称下方，灰色12px常规字重，每行22个字符、最多44字符，超长为前41字符加三个点；不再提供单独描述列或“1/1已入库”等灰色状态补充。技能编辑中的知识库搜索仍遍历匹配页获取可挂载选项，但每个请求也最多10条。

每条知识库记录包含元数据、documents文件状态数组、history版本历史；没有在列表里传原文件、向量数据或完整解析正文。列表与详情共用 `KnowledgeService.detail()` 聚合逻辑，生成列表时同步已关联convert任务的状态。

| 后端返回 | 前端字段/计算 | 页面用途 |
| --- | --- | --- |
| id（整数） | id=String(id) | 行标识；查看、保存、挂载仍指向同一个数据库编号 |
| knowledge_name | name | 知识库名称 |
| description | description | 描述 |
| tag=general/custom | tag=通识类/自定义 | 名称旁标签 |
| documents | files | 文件数组；列表文件数使用files.length；后端也返回document_count |
| version | version | 系统维护版本号 |
| is_public | scope=public或历史枚举team | 全体可见/仅本人可见；team目前不代表已接入团队权限 |
| application | applicationIds=[application] | 所属应用，单值包装为数组 |
| reference_count | referenceCount | 被实现当前版本挂载的次数，不是调用次数 |
| maintainer | maintainer | 最新维护人 |
| creator_name/creator_login_name/user_id | creatorName/creatorId | 创建者，避免误用最新维护人 |
| status=processing/failed/completed | processingStatus | 知识处理中/知识处理失败/知识处理完成 |
| can_edit | canEdit | 是否允许编辑、重试；后端独立检查权限 |
| history | history（倒序） | 编辑历史弹窗 |

documents内的id转为files.id字符串，filename→name，file_size→size，conversion_job_id→conversionJobId，conversion_status→conversionStatus，error_message→errorMessage。转换任务的job_id始终是字符串，区别于知识库/文档的整数ID。

整体status优先判断是否仍有处理中/清理中的任务，然后判断失败，均无则completed。独立convert任务的终态叫complete，平台知识库聚合状态叫completed。前端每3秒查询处理中任务和知识库详情，显示阶段及已入库文件数；不会只凭上传响应job_id就显示已完成。

创建链路：上传每个file到POST `/api/convert` → 获得job_id → POST `/knowledge-bases/create` 的source中带conversion_job_ids → 服务端生成知识库和Document记录，通过RagDocument.knowledge_document_id关联任务 → 列表以知识库记录汇总展示。一个知识库可关联多个文档任务，不是一条任务等于一条知识库。

2026-11-04用户确认其他任务已创建平台知识库及RAG七张表，并授权同步为整数编号。已通过SSL对七张空表执行整数自增主键与关联列迁移，原外键已恢复；脚本为 `applications/knowledge_base/migrations/align_empty_integer_ids_20261104.py`，变更前DDL与日志已备份。代码合同、本地测试及数据库结构已核对，真实解析、模型和Milvus端到端联调仍需目标环境验收。创建知识库只关联文档，不自动绑定技能；技能挂载单独调用技能保存接口。
