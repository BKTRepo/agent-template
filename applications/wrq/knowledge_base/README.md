# 完整问答查询链路迁移

来源：D:/projects/agent-template-dev-knowledge，dev-knowledge 工作树。
迁移查询引擎和依赖，上传、解析、分块、嵌入入库代码保持不变。

现有入口 POST /chat/stream 调用 services/query_service.py，再调用 rag/query.py 的 run_query。
默认 hybrid；依次执行历史消解、术语/双语改写、子问题分解、多路混合召回、摘要/邻块补充、rerank、预算裁剪、引用和回答生成。
所有文档查询均限定知识库权限范围；空范围不会转换成全库查询。检索证据中 metadata.executed_stages 保存阶段执行状态，rerank 降级记录为 fallback。

## 请求与恢复

原 question、conversation_id、knowledge_base_ids、model_config_id 字段保持兼容。
新增 query_mode（默认 hybrid）、enable_rerank（默认 true）、max_total_tokens 可选参数。
meta 事件包含 run_id。GET /chat/resume-query?run_id=...&after=事件编号 可重放已持久化事件并继续等待。
GET /chat/get-query-detail?run_id=... 查询本人任务、回答及检索详情。
浏览器断连不取消后台任务；服务进程重启不自动重新执行未完成模型请求。
前端未新增页面或按钮。现有客户端若需要主动续传，应保存 meta.run_id 和 SSE id 并调用恢复接口。

## 存储与配置

知识库查询事件/检索详情：keenrobot_knowledge_query_turns。
滚动摘要及边界：keenrobot_knowledge_conversation_memory。
原项目术语映射读取依赖：rag_term_mapping_source、rag_term_mapping_learned。
采纳经验读取依赖：rag_answer_feedback。本次不迁移反馈管理和术语上传页面。
对话向量记忆独立使用 rag_chat_memory；不改原文档向量集合。

仅显式执行建表，默认只打印计划，--apply 才执行：

    .venv/Scripts/python.exe -m applications.wrq.knowledge_base.schema --apply

查询独立配置见 config.py，读取当前后端 .env，现有模型/向量入库配置仍沿用 configure。
需配置 LLM_API_KEY、LLM_BASE_URL、EMBEDDING_BINDING_API_KEY、RERANK_BINDING_API_KEY 等，并运行 Milvus。
聊天选择的 ModelConfig 连接信息通过 ContextVar 隔离，避免并发会话互相覆盖。

## 核验边界

    .venv/Scripts/python.exe -m pytest applications/wrq/tests/test_query_migration.py applications/wrq/tests/query_test_answer_evidence_retry.py applications/wrq/tests/query_test_structured_table_retrieval.py applications/wrq/tests/test_api_conventions.py -q

这些测试执行查询编排、重排 HTTP、分数/引用入上下文、子问题缓存、记忆裁剪/摘要、证据重试、断连后后台完成与持久化续传。外部生成/向量服务采用明确测试替身，不代表真实模型端到端通过。
真实验收必须使用已处理完成的知识库调用 /chat/stream，并从 get-query-detail 确认各阶段和 rerank_score，同时检查回答引用、长对话记忆和断线续传。
