-- 已有 MySQL 部署关闭自动迁移时，启动前执行本增量建表脚本。
-- 新部署/启用 Aerich 自动迁移的部署由原工程迁移流程创建同名表。
CREATE TABLE IF NOT EXISTS `keenrobot_trimmer_config` (
  `key` VARCHAR(64) NOT NULL PRIMARY KEY,
  `version` VARCHAR(64) NOT NULL,
  `value` JSON NOT NULL,
  `updated_at` DATETIME(6) NOT NULL
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS `keenrobot_system_automation_asset` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `system_name` VARCHAR(100) NOT NULL UNIQUE,
  `has_automation` BOOL NOT NULL,
  `updated_at` DATETIME(6) NOT NULL
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS `keenrobot_trimmer_markdown_document` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `document_id` VARCHAR(32) NOT NULL UNIQUE,
  `requirement_id` VARCHAR(100) NOT NULL DEFAULT '',
  `requirement_name` VARCHAR(200) NOT NULL,
  `filename` VARCHAR(160) NOT NULL,
  `file_key` VARCHAR(40) NOT NULL UNIQUE,
  `download_url` VARCHAR(240) NOT NULL,
  `config_version` VARCHAR(64) NOT NULL,
  `created_at` DATETIME(6) NOT NULL,
  INDEX `idx_trimmer_req_id` (`requirement_id`),
  INDEX `idx_trimmer_req_name` (`requirement_name`),
  INDEX `idx_trimmer_created` (`created_at`),
  INDEX `idx_trimmer_id_created` (`requirement_id`, `created_at`),
  INDEX `idx_trimmer_name_created` (`requirement_name`, `created_at`)
) CHARACTER SET utf8mb4;
