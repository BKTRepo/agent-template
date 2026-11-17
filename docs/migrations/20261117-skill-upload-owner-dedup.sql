-- Run in the platform database before deploying the owner-scoped upload deduplication code.
-- Existing file IDs, owners, storage paths and skill bindings remain intact.
SELECT GROUP_CONCAT(
           CASE WHEN column_list IN ('category_id,sha256', 'sha256,category_id')
                THEN CONCAT('DROP INDEX `', REPLACE(index_name, '`', '``'), '`') END
           ORDER BY index_name SEPARATOR ', '
       ),
       COALESCE(MAX(column_list = 'create_user_login_name,category_id,sha256'), 0)
INTO @old_file_indexes, @owner_file_index_exists
FROM (
    SELECT index_name, GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') AS column_list
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'keenrobot_skill_uploaded_files'
      AND non_unique = 0
      AND index_name <> 'PRIMARY'
    GROUP BY index_name
    HAVING COUNT(*) = COUNT(column_name) AND SUM(sub_part IS NOT NULL) = 0
) AS file_indexes;

SET @alter_file_indexes = CONCAT_WS(
    ', ',
    @old_file_indexes,
    IF(@owner_file_index_exists = 1, NULL,
        'ADD UNIQUE INDEX uq_skill_file_owner_category_hash (create_user_login_name, category_id, sha256)')
);
SET @file_index_sql = IF(
    @alter_file_indexes = '',
    'SELECT ''Skill upload index already up to date'' AS message',
    CONCAT('ALTER TABLE `keenrobot_skill_uploaded_files` ', @alter_file_indexes)
);
PREPARE fix_file_indexes FROM @file_index_sql;
EXECUTE fix_file_indexes;
DEALLOCATE PREPARE fix_file_indexes;
