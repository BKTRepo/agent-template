"""按已确认方案重置 WRQ 自有表。

显式执行；默认只读计划。此脚本会清空并重建白名单中的 WRQ 表，
不触碰用户、审计、同事沙箱、aerich 或任何未列入白名单的表。
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from applications.wrq.migrations.review_20261024 import connect
from configure import PROJECT_CONFIG

WRQ_TABLES = {
    'keenrobot_skill_classes', 'keenrobot_resource_categories', 'keenrobot_skills',
    'keenrobot_skill_versions', 'keenrobot_skill_forms', 'keenrobot_skill_uploaded_files',
    'keenrobot_skill_resource_bindings', 'keenrobot_skill_debug_runs',
    'keenrobot_skill_publications',
}
PROTECTED = {'keenrobot_user', 'keenrobot_audit', 'keenrobot_online_debug_runs', 'aerich'}
ROOT = Path(__file__).resolve().parents[3]
BACKUP_ROOT = ROOT.parent / '.tmp' / 'wrq-reset-backups'


DDL = {
 'keenrobot_skill_classes': """CREATE TABLE `keenrobot_skill_classes` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '技能大类自增主键',
  `name` VARCHAR(128) NOT NULL COMMENT '技能大类名称',
  `is_enabled` BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否允许选择',
  PRIMARY KEY (`id`), UNIQUE KEY `uq_skill_class_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='技能大类字典；无排序字段'""",
 'keenrobot_resource_categories': """CREATE TABLE `keenrobot_resource_categories` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '用途自增主键',
  `code` VARCHAR(16) NOT NULL COMMENT '稳定用途代码',
  `name` VARCHAR(32) NOT NULL COMMENT '用途显示名称',
  `is_enabled` BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否允许选择',
  PRIMARY KEY (`id`), UNIQUE KEY `uq_category_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='资源用途字典；与资源来源分开'""",
 'keenrobot_skills': """CREATE TABLE `keenrobot_skills` (
  `id` VARCHAR(64) NOT NULL COMMENT '技能唯一编号',
  `name` VARCHAR(128) NOT NULL COMMENT '当前技能名称；未删除记录唯一',
  `create_user_login_name` VARCHAR(10) NOT NULL DEFAULT '' COMMENT '平台创建人工号，不维护本地用户',
  `update_user_login_name` VARCHAR(10) NULL DEFAULT NULL COMMENT '最近修改人工号',
  `display_status` ENUM('DRAFT','DEBUGGING','DEBUG_SUCCESS','DEBUG_FAILED','ONLINE','OFFLINE') NOT NULL DEFAULT 'DRAFT' COMMENT '技能展示状态',
  `current_version_id` INT NULL DEFAULT NULL COMMENT '当前技能版本主键',
  `published_version_id` INT NULL DEFAULT NULL COMMENT '最近成功上线的技能版本主键',
  `current_revision` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '当前版本修订序号',
  `last_debug_run_id` VARCHAR(128) NULL DEFAULT NULL COMMENT '最近登记的当前版本任务编号',
  `published_at` DATETIME(6) NULL DEFAULT NULL COMMENT '最近已记录的上线时间',
  `offline_at` DATETIME(6) NULL DEFAULT NULL COMMENT '最近已记录的下线时间',
  `state` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0正常 1软删除',
  `created_time` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
  `updated_time` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '最后修改时间',
  `application_paso` VARCHAR(100) NULL DEFAULT NULL COMMENT '当前应用PASO；星号表示全应用',
  `skill_classes_id` INT NOT NULL DEFAULT 0 COMMENT '当前技能大类编号',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_skills_active_name` ((CASE WHEN (`state` = 0) THEN lower(trim(`name`)) ELSE NULL END)),
  KEY `idx_skill_owner` (`create_user_login_name`,`state`,`updated_time`),
  KEY `idx_skill_pointer` (`current_version_id`,`id`,`current_revision`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='技能主表；当前版本和状态，正文存版本表单'""",
 'keenrobot_skill_versions': """CREATE TABLE `keenrobot_skill_versions` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '技能版本自增主键',
  `skill_id` VARCHAR(64) NOT NULL COMMENT '所属技能编号',
  `version` VARCHAR(32) NULL DEFAULT NULL COMMENT '显示版本号；首次成功上线前为空',
  `revision` INT UNSIGNED NOT NULL COMMENT '技能内修订序号',
  `build_id` VARCHAR(64) NULL DEFAULT NULL COMMENT '本版不可变构建编号',
  `package_storage_key` VARCHAR(512) NULL DEFAULT NULL COMMENT '构建包受控存储位置',
  `manifest_hash` CHAR(64) NULL DEFAULT NULL COMMENT '本版指令及资源清单摘要',
  `created_time` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '版本保存时间',
  `updated_time` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '版本元数据更新时间',
  `create_user_login_name` VARCHAR(10) NOT NULL DEFAULT '' COMMENT '保存本版的工号',
  `update_user_login_name` VARCHAR(10) NULL DEFAULT NULL COMMENT '更新版本元数据的工号',
  PRIMARY KEY (`id`), UNIQUE KEY `uq_version_revision` (`skill_id`,`revision`),
  UNIQUE KEY `uq_version_build` (`build_id`), KEY `idx_version_skill` (`skill_id`,`revision`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='技能版本元数据；正文只存在对应表单'""",
 'keenrobot_skill_forms': """CREATE TABLE `keenrobot_skill_forms` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '表单自增主键',
  `skill_version_id` INT UNSIGNED NOT NULL COMMENT '技能版本编号；一版一份表单',
  `name` VARCHAR(128) NOT NULL COMMENT '本版技能名称快照',
  `skill_class_id` INT NOT NULL COMMENT '技能大类整数编号',
  `application_paso` VARCHAR(100) NULL DEFAULT NULL COMMENT '平台应用PASO；星号全应用',
  `description` TEXT NOT NULL COMMENT '本版描述',
  `instructions` LONGTEXT NOT NULL COMMENT '本版执行指令',
  `resource_usage` TEXT NULL COMMENT '本版资源使用说明',
  `compatibility` TEXT NULL COMMENT '本版运行要求',
  `technical_name` VARCHAR(128) NOT NULL COMMENT '本版Skill技术名称',
  `skill_markdown_path` VARCHAR(200) NOT NULL DEFAULT '' COMMENT 'Skill定义受控相对路径；不在数据库保存正文',
  PRIMARY KEY (`id`), UNIQUE KEY `uq_form_version` (`skill_version_id`), KEY `idx_form_class` (`skill_class_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='每个技能版本唯一的表单正文；Markdown只存路径'""",
 'keenrobot_skill_uploaded_files': """CREATE TABLE `keenrobot_skill_uploaded_files` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '独立长期文件自增主键',
  `original_name` VARCHAR(255) NOT NULL COMMENT '原始文件名',
  `extension` VARCHAR(16) NOT NULL COMMENT '文件扩展名',
  `mime_type` VARCHAR(128) NULL DEFAULT NULL COMMENT '文件MIME类型',
  `byte_size` BIGINT UNSIGNED NOT NULL COMMENT '文件真实字节数',
  `sha256` CHAR(64) NULL DEFAULT NULL COMMENT '原件摘要',
  `storage_key` VARCHAR(512) NOT NULL COMMENT '原件受控存储位置',
  `create_user_login_name` VARCHAR(10) NOT NULL COMMENT '上传人工号',
  `state` VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE正常 MISSING原件缺失 DELETED软删除',
  `created_time` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '上传时间',
  `deleted_at` DATETIME(6) NULL DEFAULT NULL COMMENT '软删除时间',
  `category_id` INT NOT NULL COMMENT '文件用途整数编号',
  PRIMARY KEY (`id`), UNIQUE KEY `uq_file_category_hash` (`category_id`,`sha256`), KEY `idx_uploaded_owner` (`create_user_login_name`,`state`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='独立长期挂载文件；不维护文件版本，不保存沙箱临时文件'""",
 'keenrobot_skill_resource_bindings': """CREATE TABLE `keenrobot_skill_resource_bindings` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '挂载关联自增主键',
  `skill_version_id` INT UNSIGNED NOT NULL COMMENT '技能版本整数主键',
  `source_type` VARCHAR(32) NOT NULL COMMENT '来源：upload或knowledge_base，不表示用途',
  `source_id` INT NULL DEFAULT NULL COMMENT '来源对象整数主键',
  `file_id` INT UNSIGNED NULL DEFAULT NULL COMMENT '上传文件整数主键；知识库来源为空',
  `display_name` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '挂载时展示名称',
  `usage_text` TEXT NULL COMMENT '单项资源使用说明',
  `content_hash` CHAR(64) NULL DEFAULT NULL COMMENT '挂载内容摘要',
  `sort_order` INT NOT NULL DEFAULT 0 COMMENT '本版资源显示顺序',
  `created_time` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '挂载建立时间',
  `skill_id` VARCHAR(64) NOT NULL COMMENT '所属技能编号',
  PRIMARY KEY (`id`), UNIQUE KEY `uq_binding_source` (`skill_version_id`,`source_type`,`source_id`), UNIQUE KEY `uq_skill_version_file` (`skill_version_id`,`file_id`),
  KEY `idx_binding_skill` (`skill_id`,`skill_version_id`), KEY `idx_binding_file` (`file_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='技能版本与上传文件或知识库的挂载关系；业务代码校验关联'""",
 'keenrobot_skill_debug_runs': """CREATE TABLE `keenrobot_skill_debug_runs` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '任务版本关联自增主键',
  `run_id` VARCHAR(128) NOT NULL COMMENT '同事沙箱任务编号',
  `skill_id` VARCHAR(64) NOT NULL COMMENT '关联技能编号',
  `skill_version_id` INT UNSIGNED NOT NULL COMMENT '实际执行的技能版本',
  `build_id` VARCHAR(64) NULL DEFAULT NULL COMMENT '实际使用的构建编号',
  `conversation_input` LONGTEXT NOT NULL COMMENT '本次调试输入，不保存临时文档原件',
  `request_document_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '本次输入文档数量',
  `resource_manifest_hash` CHAR(64) NULL DEFAULT NULL COMMENT '执行时资源清单摘要',
  `result_byte_size` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '保留兼容字段；当前新流程不写',
  `error_code` VARCHAR(64) NULL DEFAULT NULL COMMENT '保留兼容字段；真实错误读同事任务表',
  `create_user_login_name` VARCHAR(10) NOT NULL COMMENT '任务发起人工号',
  `created_time` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '首次登记时间',
  `updated_time` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '关联元数据更新时间',
  PRIMARY KEY (`id`), UNIQUE KEY `uq_debug_run` (`run_id`), KEY `idx_debug_version` (`skill_id`,`skill_version_id`,`created_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='我方调试任务与技能版本关联；执行结果只读同事表'""",
 'keenrobot_skill_publications': """CREATE TABLE `keenrobot_skill_publications` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '上下线历史自增主键',
  `skill_id` VARCHAR(64) NOT NULL COMMENT '技能编号',
  `skill_version_id` INT UNSIGNED NOT NULL COMMENT '操作的技能版本',
  `action` VARCHAR(16) NOT NULL COMMENT 'PUBLISH上线 OFFLINE下线',
  `operator_login_name` VARCHAR(10) NOT NULL COMMENT '平台操作人工号',
  `version` VARCHAR(32) NULL DEFAULT NULL COMMENT '操作时的对外版本号',
  `reason_code` VARCHAR(32) NULL DEFAULT NULL COMMENT '下线原因枚举',
  `reason_text` VARCHAR(500) NULL DEFAULT NULL COMMENT '其他原因说明',
  `reason` VARCHAR(500) NULL DEFAULT NULL COMMENT '操作原因',
  `created_time` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '操作时间',
  PRIMARY KEY (`id`), KEY `idx_publication_skill` (`skill_id`,`created_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='技能上线和下线操作历史'""",
}
CLASS_SEED = [(1, '历史缺陷案例推荐'), (2, '智能用例生成'), (3, '测试数据构造'),
             (4, '测试要点生成'), (5, '测试报告生成'), (6, 'UI自动化脚本生成')]
CATEGORY_SEED = [(1, 'reference', '参考资料'), (2, 'template', '模板'), (3, 'asset', '静态资源'), (4, 'script', '脚本')]


async def run(apply=False):
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    folder = BACKUP_ROOT / datetime.now().strftime('%Y%m%dT%H%M%S')
    folder.mkdir()
    conn = await connect()
    try:
        async with conn.cursor() as cur:
            await cur.execute('SHOW TABLES')
            tables = {next(iter(row.values())) for row in await cur.fetchall()}
            unexpected = (set(DDL) | {'keenrobot_sources','keenrobot_skill_knowledge_bindings'}) - tables
            if not unexpected:
                pass
            for name in sorted(WRQ_TABLES & tables):
                await cur.execute(f'SHOW CREATE TABLE `{name}`')
                ddl = (await cur.fetchone())['Create Table']
                await cur.execute(f'SELECT * FROM `{name}`')
                rows = list(await cur.fetchall())
                (folder / f'{name}.json').write_text(json.dumps({'ddl': ddl, 'rows': rows}, ensure_ascii=False, default=str), encoding='utf8')
            if not apply:
                print(json.dumps({'mode':'plan','backup':str(folder),'protected_untouched':sorted(PROTECTED),
                    'reset_tables':sorted(WRQ_TABLES), 'drop_file_version_table':'keenrobot_source_versions' in tables}, ensure_ascii=False))
                return
            await cur.execute('SET FOREIGN_KEY_CHECKS=0')
            for name in sorted(WRQ_TABLES & tables):
                await cur.execute(f'DROP TABLE IF EXISTS `{name}`')
            await cur.execute('DROP TABLE IF EXISTS `keenrobot_source_versions`')
            for name, sql in DDL.items():
                await cur.execute(sql)
            await cur.executemany('INSERT INTO keenrobot_skill_classes (id,name,is_enabled) VALUES (%s,%s,1)', CLASS_SEED)
            await cur.executemany('INSERT INTO keenrobot_resource_categories (id,code,name,is_enabled) VALUES (%s,%s,%s,1)', CATEGORY_SEED)
            await cur.execute('SET FOREIGN_KEY_CHECKS=1')
            await cur.execute('SHOW TABLES')
            after = {next(iter(row.values())) for row in await cur.fetchall()}
            print(json.dumps({'mode':'apply','backup':str(folder),'reset_tables':sorted(set(DDL)),
                'file_version_table_present':'keenrobot_source_versions' in after,
                'protected_present':sorted(PROTECTED & after)}, ensure_ascii=False))
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run(args.apply))
