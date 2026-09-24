from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `rag_term_mapping_learned` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT COMMENT '主键',
    `learned_mapping_id` VARCHAR(64) NOT NULL UNIQUE COMMENT '程序映射稳定编号',
    `mapping_key` VARCHAR(255) NOT NULL UNIQUE COMMENT '标准词与适用范围生成的幂等业务键',
    `canonical_zh` VARCHAR(255) NOT NULL COMMENT '归纳的中文标准词',
    `aliases_zh` JSON NOT NULL COMMENT '归纳的中文别名数组',
    `official_en` VARCHAR(255)   COMMENT '归纳的官方英文词',
    `aliases_en` JSON NOT NULL COMMENT '归纳的英文别名和缩写数组',
    `scope` VARCHAR(255)   COMMENT '适用范围',
    `normalized_keys` JSON NOT NULL COMMENT '规范化匹配键数组',
    `evidence_count` INT NOT NULL COMMENT '独立采纳证据数量' DEFAULT 0,
    `confidence` DOUBLE NOT NULL COMMENT '归纳置信度' DEFAULT 0,
    `status` VARCHAR(16) NOT NULL COMMENT '状态: candidate/active/rejected/disabled' DEFAULT 'candidate',
    `source_feedback_ids` JSON NOT NULL COMMENT '来源反馈记录 ID 数组',
    `algorithm_version` VARCHAR(64)   COMMENT '归纳规则或模型版本',
    `reviewed_by` VARCHAR(64)   COMMENT '审核人',
    `reviewed_time` DATETIME(6)   COMMENT '审核时间',
    `created_time` DATETIME(6) NOT NULL COMMENT '创建时间' DEFAULT CURRENT_TIMESTAMP(6),
    `updated_time` DATETIME(6) NOT NULL COMMENT '更新时间' DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY `idx_rag_term_ma_scope_9c517f` (`scope`),
    KEY `idx_rag_term_ma_status_7f0c80` (`status`),
    KEY `idx_rag_term_ma_canonic_02da99` (`canonical_zh`, `scope`),
    KEY `idx_rag_term_ma_status_5cc253` (`status`, `scope`)
) CHARACTER SET utf8mb4 COMMENT='RAG 程序归纳术语映射表';
        CREATE TABLE IF NOT EXISTS `rag_term_mapping_source` (
    `id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT COMMENT '主键',
    `mapping_id` VARCHAR(64) NOT NULL UNIQUE COMMENT '对外稳定映射编号',
    `mapping_key` VARCHAR(255) NOT NULL UNIQUE COMMENT '标准词与适用范围生成的幂等业务键',
    `canonical_zh` VARCHAR(255) NOT NULL COMMENT '中文标准词',
    `aliases_zh` JSON NOT NULL COMMENT '中文别名数组',
    `official_en` VARCHAR(255)   COMMENT '官方英文词',
    `aliases_en` JSON NOT NULL COMMENT '英文别名和缩写数组',
    `scope` VARCHAR(255)   COMMENT '适用范围',
    `note` LONGTEXT   COMMENT '参考出处或补充说明',
    `raw_payload` JSON NOT NULL COMMENT '上传原始行快照',
    `normalized_keys` JSON NOT NULL COMMENT '规范化匹配键数组',
    `status` VARCHAR(16) NOT NULL COMMENT '状态: enabled/disabled' DEFAULT 'enabled',
    `upload_batch_id` VARCHAR(64) NOT NULL COMMENT '上传批次编号',
    `source_file` VARCHAR(255)   COMMENT '来源文件名',
    `source_row` INT   COMMENT '来源文件行号',
    `version` INT NOT NULL COMMENT '业务记录版本' DEFAULT 1,
    `created_by` VARCHAR(64)   COMMENT '上传人',
    `updated_by` VARCHAR(64)   COMMENT '最后修改人',
    `created_time` DATETIME(6) NOT NULL COMMENT '创建时间' DEFAULT CURRENT_TIMESTAMP(6),
    `updated_time` DATETIME(6) NOT NULL COMMENT '更新时间' DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY `idx_rag_term_ma_scope_2aeb1e` (`scope`),
    KEY `idx_rag_term_ma_status_04f89b` (`status`),
    KEY `idx_rag_term_ma_upload__811fc7` (`upload_batch_id`),
    KEY `idx_rag_term_ma_canonic_f54b37` (`canonical_zh`, `scope`),
    KEY `idx_rag_term_ma_status_ceb33e` (`status`, `scope`)
) CHARACTER SET utf8mb4 COMMENT='RAG 用户上传的权威术语映射表';
        """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `rag_term_mapping_learned`;
        DROP TABLE IF EXISTS `rag_term_mapping_source`;"""


MODELS_STATE = (
    "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"
    "CFR9rS5G5AB1ugaAbgtSByuyNWgi8c//Aw3Ek08="
)
