-- Expand saved skill descriptions while preserving all existing values.
SET @description_type = (
    SELECT DATA_TYPE FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'keenrobot_skill_forms' AND COLUMN_NAME = 'description'
);
SET @description_migration = IF(
    @description_type = 'longtext',
    'SELECT ''skill description already LONGTEXT'' AS result',
    'ALTER TABLE keenrobot_skill_forms MODIFY COLUMN description LONGTEXT NOT NULL COMMENT ''技能描述'''
);
PREPARE description_statement FROM @description_migration;
EXECUTE description_statement;
DEALLOCATE PREPARE description_statement;
