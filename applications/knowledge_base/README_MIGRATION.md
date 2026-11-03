# dev-knowledge 知识库迁移

源分支：dev-knowledge，来源提交：891b0c5。
目标：当前 dev-wrq 的 applications/knowledge_base。本地迁移清单与备份不随业务代码发布。
源项目与源 .env 未修改；没有复制聊天、会话、工单、前端、原数据库或输出数据。

## 处理链路

PDF/DOCX/XLSX/MD/TXT → MarkItDown → 清洗 → 术语提取及结果保存 → 摘要 → 分块 → Embedding → Milvus。
本版与源分支一致，不提供扫描 PDF OCR；不迁移 Chroma 中的历史向量。

- rag/: 源分支的术语、摘要、分块、嵌入、Milvus、表格和章节处理。
- processing/: MarkItDown 转换、Markdown 清洗、连接池和上传辅助函数。
- services/rag_*.py、pipeline_crud.py: 持久任务、阶段产物、重试、取消和增量处理。
- tasks/: Celery 处理、回滚和删除任务。
- models/: rag_document、rag_pipeline_state、rag_pipeline_history、llm_call_log。
- services/document_pipeline.py: 当前平台知识库 Document 与源流水线的适配层。
- services/platform_service.py: 保留当前平台的权限、版本、资源绑定及删除流程。

平台 /knowledge-bases 上传继续使用原合同，处理时进入迁入的流水线。
兼容入口 POST /api/convert（multipart file）、GET /api/convert/status/{job_id}、POST /api/convert/retry（JSON job_id）。
Markdown、术语、分块通过 /api/documents/{job_id}/markdown、terminology、chunks 获取。
这些接口沿用平台鉴权，并限制任务创建者访问。完整原文件不需要调用方访问服务器磁盘。

## 部署

1. 安装项目依赖（新增 MarkItDown、OpenAI SDK、pymilvus；Celery/Redis 使用现有配置）。
2. 配置 LLM_API_KEY/LLM_BASE_URL/LLM_MODEL、EMBEDDING_BINDING_API_KEY/EMBEDDING_BINDING_HOST/EMBEDDING_MODEL/EMBEDDING_DIM、MILVUS_URI 及凭据。
   兼容现有 LLM_MODEL_NAME、EMBEDDING_API_KEY/BASE_URL/MODEL_NAME；不复制源项目密钥。
3. 生成知识处理新增表的计划：
   python -m applications.knowledge_base.migrations.prepare_ingestion_schema
   核对后添加 --apply，仅创建四张处理表/补充两列；不自动修改其他业务表。
4. Web：python -m applications.wrq.full_backend
5. 解析 Worker（单任务槽位）：
   python -m celery -A celery_scheduler.celery_worker worker -Q knowledge_parse --pool=solo -c 1 -l INFO
6. 删除 Worker：同上，队列改为 knowledge_delete；Beat 使用当前 celery 配置。

独立 convert 按文件返回 job_id，多个文件可分别提交、排队处理。RAG_MAX_UPLOAD_MB 沿用源分支的服务端上限。
阶段产物保存在 RAG_OUTPUT_DIR/<job_id>；SQL 保存任务状态与计时，向量写入 Milvus。
重试是否复用按源分支的产物完整性和模型配置校验执行；缺少证明时重新处理，不把缺失产物误报为完成。

## 验证边界

迁移测试包括真实本地五种格式转换、术语阶段重试、向量替换失败保护、连接池、模型重试，以及平台 ORM 适配。
隔离测试的模型和 Milvus 写入使用显式替身；这不等于真实外部模型、Redis Worker、Milvus 全链路验收。
