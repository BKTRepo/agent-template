-- REFERENCE SCHEMA: 2026-11-04. Generator does not execute SQL.

-- Existing empty target tables were aligned using align_empty_integer_ids_20261104, not by executing this CREATE script.

-- For populated legacy tables, an explicit identifier mapping is required; CREATE IF NOT EXISTS does not convert existing columns.

-- Knowledge/document/chunk IDs and rag_document.knowledge_document_id are INT.

-- Existing keenrobot_skill_resource_bindings.source_id is INT; no changes to existing skill identifiers.

-- Review storage/charset and existing user-table constraints before applying.

CREATE TABLE IF NOT EXISTS `keenrobot_knowledge_bases` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT COMMENT '知识库自增整数编号',
    `state` SMALLINT NOT NULL COMMENT '状态(0:启用, 1:禁用)' DEFAULT 0,
    `created_time` DATETIME(6) NOT NULL COMMENT '创建时间' DEFAULT CURRENT_TIMESTAMP(6),
    `updated_time` DATETIME(6) NOT NULL COMMENT '更新时间' DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    `knowledge_name` VARCHAR(128) NOT NULL COMMENT '知识库名称',
    `name_key` VARCHAR(64) UNIQUE,
    `tag` VARCHAR(32) NOT NULL DEFAULT 'custom',
    `application` VARCHAR(128) NOT NULL DEFAULT '*',
    `revision` INT NOT NULL DEFAULT 0,
    `history` JSON NOT NULL,
    `description` LONGTEXT COMMENT '知识库描述',
    `is_public` BOOL NOT NULL COMMENT '是否公开' DEFAULT 0,
    `chunk_size` INT COMMENT '分块大小(字符数)，为空时使用全局配置',
    `chunk_overlap` INT COMMENT '分块重叠(字符数)，为空时使用全局配置',
    `user_id` BIGINT NOT NULL COMMENT '所属用户',
    CONSTRAINT `fk_keenrobo_keenrobo_75e2ad14` FOREIGN KEY (`user_id`) REFERENCES `keenrobot_user` (`id`) ON DELETE CASCADE,
    KEY `idx_keenrobot_k_state_aa0f13` (`state`)
) CHARACTER SET utf8mb4 COMMENT='知识库模型';

CREATE TABLE IF NOT EXISTS `keenrobot_documents` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT COMMENT '文档自增整数编号',
    `created_time` DATETIME(6) NOT NULL COMMENT '创建时间' DEFAULT CURRENT_TIMESTAMP(6),
    `updated_time` DATETIME(6) NOT NULL COMMENT '更新时间' DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    `filename` VARCHAR(255) NOT NULL COMMENT '文件名',
    `file_type` VARCHAR(32) NOT NULL COMMENT '文件类型(pdf/txt/docx)' DEFAULT 'pdf',
    `file_path` VARCHAR(512) NOT NULL COMMENT '文件路径',
    `file_size` BIGINT NOT NULL COMMENT '文件大小(字节)',
    `content_hash` VARCHAR(64) COMMENT '文件内容SHA256',
    `embedding_model` VARCHAR(64) COMMENT '向量化模型',
    `chunk_count` INT NOT NULL COMMENT '分块数量' DEFAULT 0,
    `status` VARCHAR(32) NOT NULL COMMENT '处理状态' DEFAULT 'processing',
    `error_message` LONGTEXT COMMENT '错误信息',
    `markdown` LONGTEXT,
    `generation` INT NOT NULL DEFAULT 1,
    `indexed_generation` INT NOT NULL DEFAULT 0,
    `processing_started_time` DATETIME(6),
    `cleanup_vector_ids` JSON NOT NULL,
    `is_deleted` BOOL NOT NULL DEFAULT 0,
    `task_id` VARCHAR(64),
    `task_dispatched_at` DATETIME(6),
    `next_retry_at` DATETIME(6),
    `deletion_retry_count` INT NOT NULL DEFAULT 0,
    `deletion_retryable` BOOL NOT NULL DEFAULT 1,
    `deletion_error_type` VARCHAR(64),
    `cleanup_file_paths` JSON NOT NULL,
    `artifact_paths` JSON NOT NULL,
    `knowledge_base_id` INT NOT NULL COMMENT '所属知识库',
    UNIQUE KEY `uid_keenrobot_d_knowled_8dd4e3` (`knowledge_base_id`, `content_hash`),
    CONSTRAINT `fk_keenrobo_keenrobo_9ee4470d` FOREIGN KEY (`knowledge_base_id`) REFERENCES `keenrobot_knowledge_bases` (`id`) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COMMENT='文档模型';

CREATE TABLE IF NOT EXISTS `keenrobot_document_chunks` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT COMMENT '分块自增整数编号',
    `created_time` DATETIME(6) NOT NULL COMMENT '创建时间' DEFAULT CURRENT_TIMESTAMP(6),
    `updated_time` DATETIME(6) NOT NULL COMMENT '更新时间' DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    `content` LONGTEXT NOT NULL COMMENT '分块内容',
    `chunk_index` INT NOT NULL COMMENT '分块序号',
    `page_number` INT COMMENT 'PDF页码(从1开始)',
    `chroma_id` VARCHAR(128) COMMENT 'Milvus向量ID（历史列名）',
    `source_metadata` JSON NOT NULL,
    `document_id` INT NOT NULL COMMENT '所属文档',
    CONSTRAINT `fk_keenrobo_keenrobo_a6b21ca6` FOREIGN KEY (`document_id`) REFERENCES `keenrobot_documents` (`id`) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COMMENT='文档分块模型';

CREATE TABLE IF NOT EXISTS `rag_document` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT COMMENT '文档任务自增整数主键',
    `created_time` DATETIME(6) NOT NULL COMMENT '创建时间' DEFAULT CURRENT_TIMESTAMP(6),
    `updated_time` DATETIME(6) NOT NULL COMMENT '更新时间' DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    `owner_id` BIGINT COMMENT '平台调用者编号',
    `knowledge_document_id` INT,
    `job_id` VARCHAR(64) NOT NULL UNIQUE COMMENT '任务ID(doc-<md5前16位>)',
    `filename` VARCHAR(255) NOT NULL UNIQUE COMMENT '文件名',
    `status` VARCHAR(32) NOT NULL COMMENT '处理状态: queued/splitting/parsing/terminology/analyzing/chunking/embedding/complete/failed/deleting/delete_failed' DEFAULT 'queued',
    `abstract` LONGTEXT NOT NULL COMMENT '文档摘要(失败时存错误描述, 取消时为\'用户取消\')',
    `input_path` VARCHAR(512) COMMENT '源文件留档路径(input/<job_id>/)',
    `output_path` VARCHAR(512) COMMENT '产物目录(output/rag_upload/<job_id>/)',
    `artifacts_file` VARCHAR(512) COMMENT 'docling artifacts 目录路径',
    `sidecar` JSON NOT NULL COMMENT '侧车文件四元组: meta/blocks/drawings/tables 路径',
    `chunks_file` VARCHAR(512) COMMENT '分块产物路径',
    `do_ocr` BOOL NOT NULL COMMENT '是否启用 OCR' DEFAULT 0,
    `force_ocr` BOOL NOT NULL COMMENT '是否强制 OCR' DEFAULT 0,
    `enable_vlm` BOOL NOT NULL COMMENT '是否启用多模态(VLM)分析' DEFAULT 0,
    `chunk_strategy` VARCHAR(32) COMMENT '分块策略(旧记录兼容字段)',
    `page_count` INT COMMENT 'PDF 页数',
    `total_parts` INT NOT NULL COMMENT '子文档总数' DEFAULT 1,
    `completed_parts` INT NOT NULL COMMENT '已完成子文档数' DEFAULT 0,
    `terminology_total_batches` INT NOT NULL COMMENT '术语抽取总批次' DEFAULT 1,
    `terminology_completed_batches` INT NOT NULL COMMENT '术语抽取已完成批次' DEFAULT 0,
    `analyzing_stage_skipped` BOOL NOT NULL COMMENT '是否跳过多模态分析阶段' DEFAULT 0,
    `celery_task_id` VARCHAR(64) COMMENT 'Celery 任务ID(巡检判活用)',
    `heartbeat_at` DATETIME(6) COMMENT 'Worker 最近心跳时间(巡检容忍15分钟)',
    `cancel_requested` BOOL NOT NULL COMMENT '取消标记(守卫: 已取消文档拒绝进度覆盖)' DEFAULT 0,
    `resume` BOOL NOT NULL COMMENT '重试续跑标记(完成后清除)' DEFAULT 0,
    `deleting_retry_count` INT NOT NULL COMMENT '删除任务由巡检重新投递的次数（仅补偿投递时递增）' DEFAULT 0,
    `deletion_retryable` BOOL NOT NULL COMMENT '删除失败后是否允许定时巡检自动补偿' DEFAULT 1,
    `deletion_error_type` VARCHAR(64) COMMENT '最近一次删除失败的异常类型',
    `content_length` INT COMMENT '清洗后 markdown 字符数',
    `chunks_count` INT COMMENT '分块数量',
    `error_trace` LONGTEXT COMMENT '错误堆栈(尾部500字符)',
    `file_sha256` VARCHAR(64) COMMENT '最新版本源文件 SHA256(增量更新快速通道: 与上传文件一致则免重处理)',
    `is_updating` BOOL NOT NULL COMMENT '增量更新处理中(更新期间旧版本向量持续服务, 到达终态后清除)' DEFAULT 0,
    `update_history` JSON COMMENT '增量更新历史: [{time, filename, reused, embedded}]',
    `parse_start_time` DATETIME(6) COMMENT '解析开始时间',
    `parse_end_time` DATETIME(6) COMMENT '解析结束时间',
    `parse_duration` DOUBLE COMMENT '解析耗时(秒)',
    `term_start_time` DATETIME(6) COMMENT '术语抽取开始时间',
    `term_end_time` DATETIME(6) COMMENT '术语抽取结束时间',
    `analyze_start_time` DATETIME(6) COMMENT '多模态分析开始时间',
    `analyze_end_time` DATETIME(6) COMMENT '多模态分析结束时间',
    `analyze_duration` DOUBLE COMMENT '多模态分析耗时(秒)',
    `chunk_start_time` DATETIME(6) COMMENT '分块开始时间',
    `chunk_end_time` DATETIME(6) COMMENT '分块结束时间',
    `embed_start_time` DATETIME(6) COMMENT '嵌入开始时间',
    `embed_end_time` DATETIME(6) COMMENT '嵌入结束时间',
    `process_end_time` DATETIME(6) COMMENT '处理结束时间',
    KEY `idx_rag_documen_owner_i_57dd08` (`owner_id`),
    KEY `idx_rag_documen_knowled_49689b` (`knowledge_document_id`),
    KEY `idx_rag_documen_status_5d8b63` (`status`),
    KEY `idx_rag_documen_celery__9dc14e` (`celery_task_id`),
    KEY `idx_rag_documen_heartbe_8e3982` (`heartbeat_at`)
) CHARACTER SET utf8mb4 COMMENT='RAG 文档表(文档管理页持久化载体)';

CREATE TABLE IF NOT EXISTS `rag_pipeline_state` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT COMMENT '流水线状态自增整数主键',
    `start_time` DATETIME(6) COMMENT '流水线启动时间（空闲为 NULL）',
    `updated_time` DATETIME(6) NOT NULL COMMENT '更新时间' DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) CHARACTER SET utf8mb4 COMMENT='RAG 流水线运行状态表（单行）';

CREATE TABLE IF NOT EXISTS `rag_pipeline_history` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT COMMENT '流水线历史自增整数主键',
    `message` LONGTEXT NOT NULL COMMENT '历史消息内容',
    `created_time` DATETIME(6) COMMENT '消息时间',
    KEY `idx_rag_pipelin_created_8024b4` (`created_time`)
) CHARACTER SET utf8mb4 COMMENT='RAG 流水线历史消息表';

CREATE TABLE IF NOT EXISTS `llm_call_log` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT COMMENT '模型调用日志自增整数主键',
    `model` VARCHAR(128) NOT NULL COMMENT '模型名',
    `scene` VARCHAR(64) COMMENT '调用场景(预留列, 当前恒为空; 后续可在调用点补传以区分最终回答/术语抽取/查询改写)',
    `stream` BOOL NOT NULL COMMENT '是否流式调用',
    `success` BOOL NOT NULL COMMENT '调用是否成功',
    `error_message` LONGTEXT COMMENT '失败时的错误摘要',
    `start_at` DATETIME(6) NOT NULL COMMENT '调用开始时间',
    `end_at` DATETIME(6) COMMENT '调用结束时间',
    `total_ms` INT COMMENT '总耗时(毫秒)',
    `first_token_ms` INT COMMENT '首 Token 耗时(毫秒), 仅流式有值',
    `prompt_tokens` INT COMMENT '输入 Token 数',
    `completion_tokens` INT COMMENT '输出 Token 数',
    `total_tokens` INT COMMENT '总 Token 数',
    `prompt_text` LONGTEXT NOT NULL COMMENT '模型实际收到的完整输入(messages 的 JSON)',
    `completion_text` LONGTEXT COMMENT '模型实际生成的完整输出(流式为逐块拼接)',
    `prompt_chars` INT NOT NULL COMMENT '输入字符数(便于按体积排序, 免解析 JSON)' DEFAULT 0,
    `completion_chars` INT NOT NULL COMMENT '输出字符数' DEFAULT 0,
    `created_time` DATETIME(6) NOT NULL COMMENT '落库时间' DEFAULT CURRENT_TIMESTAMP(6),
    KEY `idx_llm_call_lo_start_a_ca4dd2` (`start_at`),
    KEY `idx_llm_call_lo_model_b79a47` (`model`, `start_at`)
) CHARACTER SET utf8mb4 COMMENT='LLM 调用统计表(耗时/Token/完整输入输出)';
