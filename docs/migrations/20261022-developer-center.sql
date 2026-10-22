-- 开发者中心首期表结构。执行前请确认当前连接的是 zdhgj_db。
-- 文件本体保存到对象存储，本库仅保存元数据、哈希与 storage_key。

CREATE TABLE IF NOT EXISTS keenrobot_skills (
  id VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  name_key CHAR(64) NOT NULL,
  description TEXT NULL,
  user_id BIGINT NOT NULL,
  is_enabled TINYINT(1) NOT NULL DEFAULT 0,
  display_status VARCHAR(16) NOT NULL DEFAULT 'DRAFT',
  current_version_id VARCHAR(64) NULL,
  current_revision INT NOT NULL DEFAULT 1,
  last_debug_run_id VARCHAR(128) NULL,
  last_debug_passed_at DATETIME(6) NULL,
  published_at DATETIME(6) NULL,
  offline_at DATETIME(6) NULL,
  config JSON NULL,
  state SMALLINT NOT NULL DEFAULT 0,
  created_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_keenrobot_skills_name_key (name_key),
  KEY idx_keenrobot_skills_user_status (user_id, display_status, updated_time),
  KEY idx_keenrobot_skills_state (state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS keenrobot_skill_versions (
  id VARCHAR(64) NOT NULL,
  skill_id VARCHAR(64) NOT NULL,
  version VARCHAR(32) NOT NULL,
  revision INT NOT NULL,
  skill_class_id VARCHAR(64) NOT NULL,
  application_id VARCHAR(64) NULL,
  description VARCHAR(1024) NOT NULL,
  instructions LONGTEXT NOT NULL,
  resource_usage LONGTEXT NULL,
  compatibility VARCHAR(500) NULL,
  skill_markdown LONGTEXT NULL,
  build_id VARCHAR(64) NULL,
  package_storage_key VARCHAR(512) NULL,
  manifest_hash CHAR(64) NULL,
  created_by BIGINT NOT NULL,
  created_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_keenrobot_skill_versions_skill_version (skill_id, version),
  KEY idx_keenrobot_skill_versions_skill_time (skill_id, created_time),
  KEY idx_keenrobot_skill_versions_application (application_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS keenrobot_skill_uploaded_files (
  id VARCHAR(64) NOT NULL,
  original_name VARCHAR(255) NOT NULL,
  extension VARCHAR(16) NOT NULL,
  mime_type VARCHAR(128) NULL,
  byte_size BIGINT NOT NULL,
  sha256 CHAR(64) NOT NULL,
  storage_key VARCHAR(512) NOT NULL,
  uploaded_by BIGINT NOT NULL,
  state VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
  created_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  KEY idx_keenrobot_skill_uploaded_files_owner (uploaded_by, state, created_time),
  KEY idx_keenrobot_skill_uploaded_files_hash (sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS keenrobot_skill_resource_bindings (
  id VARCHAR(64) NOT NULL,
  skill_version_id VARCHAR(64) NOT NULL,
  source_type VARCHAR(32) NOT NULL,
  source_id VARCHAR(64) NOT NULL,
  source_version VARCHAR(64) NULL,
  file_id VARCHAR(64) NULL,
  display_name VARCHAR(255) NOT NULL,
  category VARCHAR(16) NOT NULL,
  usage_text TEXT NULL,
  content_hash CHAR(64) NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_keenrobot_skill_bindings_version (skill_version_id, sort_order),
  KEY idx_keenrobot_skill_bindings_source (source_type, source_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS keenrobot_skill_debug_runs (
  id VARCHAR(64) NOT NULL,
  run_id VARCHAR(128) NOT NULL,
  skill_id VARCHAR(64) NOT NULL,
  skill_version_id VARCHAR(64) NOT NULL,
  build_id VARCHAR(64) NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'QUEUED',
  conversation_input LONGTEXT NULL,
  request_document_count INT NOT NULL DEFAULT 0,
  resource_manifest_hash CHAR(64) NULL,
  result_storage_key VARCHAR(512) NULL,
  result_file_name VARCHAR(255) NULL,
  result_byte_size BIGINT NULL,
  error_code VARCHAR(64) NULL,
  error_message TEXT NULL,
  started_at DATETIME(6) NULL,
  finished_at DATETIME(6) NULL,
  created_by BIGINT NOT NULL,
  created_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_keenrobot_skill_debug_runs_run_id (run_id),
  KEY idx_keenrobot_skill_debug_runs_version (skill_version_id, status, created_time),
  KEY idx_keenrobot_skill_debug_runs_skill (skill_id, created_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS keenrobot_skill_debug_documents (
  id VARCHAR(64) NOT NULL,
  debug_run_id VARCHAR(64) NOT NULL,
  original_name VARCHAR(255) NOT NULL,
  extension VARCHAR(16) NOT NULL,
  mime_type VARCHAR(128) NULL,
  byte_size BIGINT NOT NULL,
  sha256 CHAR(64) NOT NULL,
  storage_key VARCHAR(512) NOT NULL,
  created_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_keenrobot_skill_debug_documents_run (debug_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS keenrobot_skill_publications (
  id VARCHAR(64) NOT NULL,
  skill_id VARCHAR(64) NOT NULL,
  skill_version_id VARCHAR(64) NOT NULL,
  action VARCHAR(16) NOT NULL,
  operator_id BIGINT NOT NULL,
  reason VARCHAR(500) NULL,
  created_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_keenrobot_skill_publications_skill (skill_id, created_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
