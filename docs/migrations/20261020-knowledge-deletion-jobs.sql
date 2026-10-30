-- 在 knowledge-platform 迁移之后执行；先备份、测试，禁止对已有字段重复 ADD。
-- 当前适配模型需要任务／清理元数据，不能照抄源 RAG 的“无需新增字段”。
ALTER TABLE keenrobot_documents
    ADD COLUMN task_id VARCHAR(64) NULL,
    ADD COLUMN task_dispatched_at DATETIME(6) NULL,
    ADD COLUMN next_retry_at DATETIME(6) NULL,
    ADD COLUMN deletion_retry_count INT NOT NULL DEFAULT 0,
    ADD COLUMN deletion_retryable BOOL NOT NULL DEFAULT TRUE,
    ADD COLUMN deletion_error_type VARCHAR(64) NULL,
    ADD COLUMN cleanup_file_paths JSON NULL,
    ADD COLUMN artifact_paths JSON NULL;
UPDATE keenrobot_documents SET cleanup_file_paths=JSON_ARRAY() WHERE cleanup_file_paths IS NULL;
UPDATE keenrobot_documents SET artifact_paths=JSON_ARRAY() WHERE artifact_paths IS NULL;
ALTER TABLE keenrobot_documents MODIFY cleanup_file_paths JSON NOT NULL, MODIFY artifact_paths JSON NOT NULL;
-- 兼容上一批使用 is_deleted + failed/processing 的文档。
UPDATE keenrobot_documents SET status='delete_failed', deletion_retryable=FALSE
    WHERE is_deleted=TRUE AND status='failed';
UPDATE keenrobot_documents SET status='deleting' WHERE is_deleted=TRUE AND status='processing';
