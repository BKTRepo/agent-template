-- 定稿知识库模型升级（MySQL 8）。仅提供迁移材料，本次没有执行服务器迁移。
-- 执行前备份，停止写入；先在测试数据库验证。若字段已存在，不要重复执行。
-- Skill.name_key 仍沿用 examples/migrate_skill_names.py 的独立预审迁移。

ALTER TABLE keenrobot_knowledge_bases
    ADD COLUMN name_key VARCHAR(64) NULL,
    ADD COLUMN tag VARCHAR(32) NOT NULL DEFAULT 'custom',
    ADD COLUMN application VARCHAR(128) NOT NULL DEFAULT '*',
    ADD COLUMN revision INT NOT NULL DEFAULT 0,
    ADD COLUMN history JSON NULL;
UPDATE keenrobot_knowledge_bases SET history = JSON_ARRAY() WHERE history IS NULL;
ALTER TABLE keenrobot_knowledge_bases MODIFY history JSON NOT NULL;
CREATE UNIQUE INDEX uq_knowledge_name_key ON keenrobot_knowledge_bases(name_key);

ALTER TABLE keenrobot_documents
    MODIFY file_size BIGINT NOT NULL,
    ADD COLUMN markdown LONGTEXT NULL,
    ADD COLUMN generation INT NOT NULL DEFAULT 1,
    ADD COLUMN indexed_generation INT NOT NULL DEFAULT 0,
    ADD COLUMN processing_started_time DATETIME(6) NULL,
    ADD COLUMN cleanup_vector_ids JSON NULL,
    ADD COLUMN is_deleted BOOL NOT NULL DEFAULT FALSE;
UPDATE keenrobot_documents SET cleanup_vector_ids = JSON_ARRAY() WHERE cleanup_vector_ids IS NULL;
ALTER TABLE keenrobot_documents MODIFY cleanup_vector_ids JSON NOT NULL;

ALTER TABLE keenrobot_document_chunks ADD COLUMN source_metadata JSON NULL;
UPDATE keenrobot_document_chunks SET source_metadata = JSON_OBJECT() WHERE source_metadata IS NULL;
ALTER TABLE keenrobot_document_chunks MODIFY source_metadata JSON NOT NULL;

-- 然后使用 applications.knowledge_base.name_rules.name_key 的 NFKC + casefold + SHA256 规则回填名称键。
-- 不可直接用 MySQL LOWER() 替代全半角归一化；先处理重名再开放写入。
