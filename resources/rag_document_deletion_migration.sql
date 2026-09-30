-- 方案 C：删除任务巡检补偿次数
-- 请在包含 rag_document 表的业务数据库执行一次。
-- 已存在该字段时不要重复执行；不同 MySQL 版本对 ADD COLUMN IF NOT EXISTS
-- 的支持不一致，因此这里保留为明确的一次性迁移语句。
ALTER TABLE `rag_document`
    ADD COLUMN `deleting_retry_count` INT NOT NULL DEFAULT 0
    COMMENT '删除任务由巡检重新投递的次数（仅补偿投递时递增）',
    ADD COLUMN `deletion_retryable` TINYINT(1) NOT NULL DEFAULT 1
    COMMENT '删除失败后是否允许定时巡检自动补偿',
    ADD COLUMN `deletion_error_type` VARCHAR(64) NULL
    COMMENT '最近一次删除失败的异常类型';
