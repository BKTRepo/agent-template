"""审核后的WRQ目标列与约束；不包含共享用户/应用/沙箱结果表。"""
T = 'DATETIME(6)'
NOW = 'DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)'
V64 = 'VARCHAR(64)'
TABLES = {
 'keenrobot_resource_categories': ('资源用途字典；与资源来源不同', [
  ('id','SMALLINT UNSIGNED NOT NULL','用途编号'),('code','VARCHAR(16) NOT NULL','稳定用途代码'),
  ('name','VARCHAR(32) NOT NULL','用途名称'),('is_enabled','BOOLEAN NOT NULL DEFAULT TRUE','是否允许选择')],
  ['PRIMARY KEY(id)','UNIQUE KEY uq_category_code(code)']),
 'keenrobot_skills': ('技能主表；当前版本和状态，正文存版本表单', [
  ('id',V64+' NOT NULL','技能唯一编号'),('name','VARCHAR(128) NOT NULL','当前技能名称；未删除记录唯一'),
  ('description','TEXT NOT NULL','当前表单描述的查询副本'),('user_id',V64+' NOT NULL','平台创建者编号，不维护本地用户'),
  ('is_enabled','BOOLEAN NOT NULL DEFAULT FALSE','仅已上线技能启用'),
  ('display_status',"ENUM('DRAFT','DEBUGGING','DEBUG_SUCCESS','DEBUG_FAILED','ONLINE','OFFLINE') NOT NULL DEFAULT 'DRAFT'",'技能展示状态'),
  ('current_version_id','INT UNSIGNED NULL','当前技能版本主键'),('current_revision','INT UNSIGNED NOT NULL','当前版本修订序号'),
  ('last_debug_run_id','VARCHAR(128) NULL','最近登记的当前版本任务编号'),('last_debug_passed_at',T+' NULL','当前版本确认通过时间'),
  ('published_at',T+' NULL','最近已记录的上线时间'),('offline_at',T+' NULL','最近已记录的下线时间'),
  ('state','TINYINT UNSIGNED NOT NULL DEFAULT 0','0正常 1软删除'),('created_time',NOW,'创建时间'),('updated_time',NOW,'最后修改时间')],
  ['PRIMARY KEY(id)',"UNIQUE KEY uq_skills_active_name ((CASE WHEN state=0 THEN LOWER(TRIM(name)) ELSE NULL END))",'KEY idx_skill_owner(user_id,state,updated_time)',"CHECK ((display_status='ONLINE' AND is_enabled=1) OR (display_status<>'ONLINE' AND is_enabled=0))"]),
 'keenrobot_skill_versions': ('技能版本元数据；正文只存在对应表单', [
  ('id','INT UNSIGNED NOT NULL AUTO_INCREMENT','版本整数主键'),('skill_id',V64+' NOT NULL','所属技能编号'),
  ('version','VARCHAR(32) NOT NULL','显示版本号'),('revision','INT UNSIGNED NOT NULL','技能内修订序号'),
  ('build_id',V64+' NULL','本版不可变构建编号'),('package_storage_key','VARCHAR(512) NULL','构建包受控存储位置'),
  ('manifest_hash','CHAR(64) NULL','本版指令及资源清单摘要'),('created_by',V64+' NOT NULL','保存本版的平台用户编号'),
  ('created_time',NOW,'版本保存时间'),('updated_time',NOW,'版本元数据更新时间')],
  ['PRIMARY KEY(id)','UNIQUE KEY uq_version_revision(skill_id,revision)','UNIQUE KEY uq_version_owner(id,skill_id)','UNIQUE KEY uq_version_pointer(id,skill_id,revision)','UNIQUE KEY uq_version_build(build_id)']),
 'keenrobot_skill_forms': ('每个技能版本唯一的表单正文；无重复版本元数据', [
  ('skill_version_id','INT UNSIGNED NOT NULL','主键兼技能版本外键'),('name','VARCHAR(128) NOT NULL','本版技能名称快照'),
  ('skill_class_id',V64+' NOT NULL','技能大类编号'),('application_id',V64+' NULL','平台应用编号；星号全应用'),
  ('description','TEXT NOT NULL','本版描述'),('instructions','LONGTEXT NOT NULL','本版执行指令'),
  ('resource_usage','TEXT NULL','本版资源使用说明'),('compatibility','TEXT NULL','本版运行要求'),
  ('technical_name','VARCHAR(128) NOT NULL','本版Skill技术名称'),('skill_markdown','LONGTEXT NOT NULL','本版完整Skill定义')],
  ['PRIMARY KEY(skill_version_id)']),
 'keenrobot_skill_uploaded_files': ('长期上传文件及当前属性；不保存沙箱临时输入文件', [
  ('id','INT UNSIGNED NOT NULL AUTO_INCREMENT','文件实体主键，沿用现有文件编号'),('original_name','VARCHAR(255) NOT NULL','当前原始文件名'),
  ('extension','VARCHAR(16) NOT NULL','当前扩展名'),('mime_type','VARCHAR(128) NULL','当前MIME类型'),
  ('byte_size','BIGINT UNSIGNED NOT NULL','当前真实字节数'),('sha256','CHAR(64) NULL','当前原件摘要；缺失历史原件为空'),
  ('storage_key','VARCHAR(512) NOT NULL','当前原件受控存储位置'),('uploaded_by',V64+' NOT NULL','最初上传人的平台编号'),
  ('state',"VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'",'ACTIVE正常 MISSING原件缺失 DELETED软删除'),
  ('created_time',NOW,'最初上传时间'),('deleted_at',T+' NULL','软删除时间'),
  ('category_id','SMALLINT UNSIGNED NOT NULL','当前用途字典编号'),('current_version_id','INT UNSIGNED NULL','当前文件版本主键'),
  ('current_revision','INT UNSIGNED NOT NULL','当前文件修订序号')],
  ['PRIMARY KEY(id)','KEY idx_uploaded_owner(uploaded_by,state)']),
 'keenrobot_source_versions': ('长期文件历史版本；技能挂载固定引用，历史不覆盖', [
  ('id','INT UNSIGNED NOT NULL AUTO_INCREMENT','文件版本主键'),('file_id','INT UNSIGNED NOT NULL','所属上传文件编号'),
  ('revision','INT UNSIGNED NOT NULL','文件内修订序号'),('original_name','VARCHAR(255) NOT NULL','本版原始文件名'),
  ('extension','VARCHAR(16) NOT NULL','本版扩展名'),('mime_type','VARCHAR(128) NULL','本版MIME类型'),
  ('byte_size','BIGINT UNSIGNED NOT NULL','本版真实字节数'),('sha256','CHAR(64) NULL','本版原件摘要；缺失历史原件为空'),
  ('storage_key','VARCHAR(512) NOT NULL','本版原件存储位置'),('category_id','SMALLINT UNSIGNED NOT NULL','本版用途字典编号'),
  ('uploaded_by',V64+' NOT NULL','本版上传人的平台编号'),('state',"VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'",'本版原件状态'),
  ('created_time',NOW,'本版创建时间'),('deleted_at',T+' NULL','本版软删除时间')],
  ['PRIMARY KEY(id)','UNIQUE KEY uq_file_revision(file_id,revision)','UNIQUE KEY uq_file_version_owner(id,file_id)','UNIQUE KEY uq_file_pointer(id,file_id,revision)']),
 'keenrobot_skill_resource_bindings': ('技能具体版本与来源资源及固定文件版本的挂载关系', [
  ('id','INT UNSIGNED NOT NULL AUTO_INCREMENT','挂载记录主键'),('skill_version_id','INT UNSIGNED NOT NULL','技能版本主键'),
  ('source_type','VARCHAR(32) NOT NULL','来源：upload knowledge_base knowledge_document；不表示用途'),
  ('source_id',V64+' NULL','来源资源标识'),('source_version',V64+' NULL','来源资源版本'),
  ('file_id','INT UNSIGNED NULL','上传文件编号；整库挂载为空'),('display_name','VARCHAR(255) NOT NULL','挂载时展示名称'),
  ('usage_text','TEXT NULL','单项资源使用说明'),('content_hash','CHAR(64) NULL','挂载内容摘要'),
  ('sort_order','INT NOT NULL DEFAULT 0','本版资源显示顺序'),('created_time',NOW,'挂载建立时间'),
  ('skill_id',V64+' NOT NULL','所属技能编号'),('source_version_id','INT UNSIGNED NULL','本次固定的文件版本主键')],
  ['PRIMARY KEY(id)','UNIQUE KEY uq_binding_source(skill_version_id,source_type,source_id)','CHECK ((file_id IS NULL) = (source_version_id IS NULL))']),
 'keenrobot_skill_debug_runs': ('我方调试任务与技能版本关联及输入信息；执行状态结果只读同事表', [
  ('id',V64+' NOT NULL','我方登记主键'),('run_id','VARCHAR(128) NOT NULL','同事任务唯一编号'),
  ('skill_id',V64+' NOT NULL','技能编号'),('skill_version_id','INT UNSIGNED NOT NULL','实际执行的技能版本'),
  ('build_id',V64+' NULL','实际执行的构建编号'),('conversation_input','LONGTEXT NOT NULL','本次对话输入'),
  ('request_document_count','INT UNSIGNED NOT NULL DEFAULT 0','本次临时输入文档数量，不保存文档原件'),
  ('resource_manifest_hash','CHAR(64) NULL','执行时资源清单摘要'),('result_byte_size','BIGINT UNSIGNED NULL','同事表未保存的既有结果大小信息'),
  ('error_code',V64+' NULL','同事表未保存的既有错误码'),('created_by',V64+' NOT NULL','发起人的平台编号'),
  ('created_time',NOW,'首次登记时间'),('updated_time',NOW,'登记元数据更新时间')],
  ['PRIMARY KEY(id)','UNIQUE KEY uq_debug_run(run_id)','KEY idx_debug_version(skill_id,skill_version_id,created_time)']),
 'keenrobot_skill_publications': ('技能上线和下线操作历史', [
  ('id',V64+' NOT NULL','操作记录主键'),('skill_id',V64+' NOT NULL','技能编号'),
  ('skill_version_id','INT UNSIGNED NOT NULL','操作的技能版本'),('action','VARCHAR(16) NOT NULL','PUBLISH上线 OFFLINE下线'),
  ('operator_id',V64+' NOT NULL','平台操作人编号'),('reason','VARCHAR(500) NULL','操作原因'),('created_time',NOW,'操作时间')],
  ['PRIMARY KEY(id)','KEY idx_publication_skill(skill_id,created_time)'])
}

# child, child columns, parent, parent columns。复合外键同时约束版本归属。
FOREIGN_KEYS = [
 ('keenrobot_skills','current_version_id,id,current_revision','keenrobot_skill_versions','id,skill_id,revision'),
 ('keenrobot_skill_versions','skill_id','keenrobot_skills','id'),
 ('keenrobot_skill_forms','skill_version_id','keenrobot_skill_versions','id'),
 ('keenrobot_skill_forms','skill_class_id','keenrobot_skill_classes','id'),
 ('keenrobot_skill_uploaded_files','category_id','keenrobot_resource_categories','id'),
 ('keenrobot_skill_uploaded_files','current_version_id,id,current_revision','keenrobot_source_versions','id,file_id,revision'),
 ('keenrobot_source_versions','file_id','keenrobot_skill_uploaded_files','id'),
 ('keenrobot_source_versions','category_id','keenrobot_resource_categories','id'),
 ('keenrobot_skill_resource_bindings','skill_version_id,skill_id','keenrobot_skill_versions','id,skill_id'),
 ('keenrobot_skill_resource_bindings','source_version_id,file_id','keenrobot_source_versions','id,file_id'),
 ('keenrobot_skill_resource_bindings','file_id','keenrobot_skill_uploaded_files','id'),
 ('keenrobot_skill_debug_runs','skill_version_id,skill_id','keenrobot_skill_versions','id,skill_id'),
 ('keenrobot_skill_publications','skill_version_id,skill_id','keenrobot_skill_versions','id,skill_id')]

def create_sql(name, actual_name=None):
    comment, columns, keys = TABLES[name]
    specs = [f"`{n}` {t} COMMENT '{c}'" for n,t,c in columns] + keys
    return f"CREATE TABLE `{actual_name or name}` ("+',\n'.join(specs)+f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='{comment}'"
