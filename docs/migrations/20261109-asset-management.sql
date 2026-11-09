CREATE TABLE IF NOT EXISTS keenrobot_assets (
  id INT NOT NULL AUTO_INCREMENT,
  name VARCHAR(128) NOT NULL,
  skill_classes_id INT NOT NULL,
  application_identify VARCHAR(100) NOT NULL,
  created_by BIGINT NOT NULL,
  visibility VARCHAR(16) NOT NULL DEFAULT 'private',
  source_artifact_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
  created_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_asset_source (source_artifact_id),
  KEY idx_asset_list (deleted_at, created_time, id),
  KEY idx_asset_class (skill_classes_id, deleted_at, created_time, id),
  KEY idx_asset_owner (created_by, deleted_at),
  CONSTRAINT fk_asset_skill_class FOREIGN KEY (skill_classes_id) REFERENCES keenrobot_skill_classes (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS keenrobot_asset_files (
  id INT NOT NULL AUTO_INCREMENT,
  asset_id INT NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  storage_key VARCHAR(512) COLLATE utf8mb4_bin NOT NULL,
  size_bytes BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_asset_file_storage (storage_key),
  KEY idx_asset_file_asset (asset_id, id),
  CONSTRAINT fk_asset_file_asset FOREIGN KEY (asset_id) REFERENCES keenrobot_assets (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
