CREATE TABLE IF NOT EXISTS keenrobot_artifact_case_groups (
    artifact_id VARCHAR(128) NOT NULL PRIMARY KEY,
    `groups` JSON NOT NULL,
    updated_time DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE keenrobot_asset_files ADD COLUMN case_groups JSON NULL;
