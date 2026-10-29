"""本轮目标结构：工号/PASO/无外键/无文件版本；只定义WRQ表。"""
from copy import deepcopy
from applications.wrq.migrations.schema_20261026 import TABLES as OLD, NOW, T, V64

TABLES = deepcopy(OLD)
del TABLES['keenrobot_source_versions']


def change(name, removed=(), renamed=None, added=(), keys=None, comment=None):
    old_comment, columns, old_keys = TABLES[name]
    rename = renamed or {}
    columns = [rename.get(n, (n, t, c)) for n, t, c in columns if n not in removed]
    TABLES[name] = (comment or old_comment, columns + list(added), old_keys if keys is None else keys)


TABLES['keenrobot_skill_classes'] = ('技能大类字典；无排序字段', [
    ('id', 'INT NOT NULL AUTO_INCREMENT', '技能大类自增主键'),
    ('name', 'VARCHAR(128) NOT NULL', '技能大类名称'),
    ('is_enabled', 'BOOLEAN NOT NULL DEFAULT TRUE', '是否允许选择')],
    ['PRIMARY KEY(id)', 'UNIQUE KEY uq_skill_class_name(name)'])
change('keenrobot_skills', removed=('description','user_id','is_enabled','last_debug_passed_at'),
    renamed={'current_version_id':('current_version_id','INT NULL','当前技能版本整数主键')}, added=(
        ('create_user_login_name','VARCHAR(10) NOT NULL','平台创建人工号；由可信身份填写'),
        ('update_user_login_name','VARCHAR(10) NULL','最近修改人工号'),
        ('application_paso','VARCHAR(100) NULL','当前应用PASO；星号表示全应用'),
        ('skill_classes_id','INT NOT NULL','当前技能大类整数编号')),
    keys=['PRIMARY KEY(id)', "UNIQUE KEY uq_skills_active_name ((CASE WHEN state=0 THEN LOWER(TRIM(name)) ELSE NULL END))",
        'KEY idx_skill_owner(create_user_login_name,state,updated_time)',
        'KEY idx_skill_pointer(current_version_id,id,current_revision)'])
_skill_comment, _skill_columns, _skill_keys = TABLES['keenrobot_skills']
_skill_columns.append(('published_version_id','INT NULL','最近成功上线的技能版本整数编号'))
TABLES['keenrobot_skills'] = (_skill_comment, _skill_columns, _skill_keys)
change('keenrobot_skill_versions', removed=('created_by',), renamed={
    'id':('id','INT NOT NULL AUTO_INCREMENT','技能版本自增主键')}, added=(
        ('create_user_login_name',"VARCHAR(10) NOT NULL DEFAULT ''",'保存本版的工号；无法核实的历史值为空'),
        ('update_user_login_name','VARCHAR(10) NULL','更新版本元数据的工号')))
_version_comment, _version_columns, _version_keys = TABLES['keenrobot_skill_versions']
_version_columns = [(n, 'VARCHAR(32) NULL' if n == 'version' else t, c) for n, t, c in _version_columns]
TABLES['keenrobot_skill_versions'] = (_version_comment, _version_columns, _version_keys)
change('keenrobot_skill_forms', removed=('skill_markdown',), renamed={
    'skill_version_id':('skill_version_id','INT NOT NULL','技能版本编号；一版一份表单'),
    'skill_class_id':('skill_class_id','INT NOT NULL','技能大类整数编号'),
    'application_id':('application_paso','VARCHAR(100) NULL','门户应用PASO；星号表示全应用')}, added=(
        ('id','INT NOT NULL AUTO_INCREMENT','表单自增主键'),
        ('skill_markdown_path',"VARCHAR(200) NOT NULL DEFAULT ''",'Skill定义相对路径；未生成为空')),
    keys=['PRIMARY KEY(id)','UNIQUE KEY uq_form_version(skill_version_id)','KEY idx_form_class(skill_class_id)'])
change('keenrobot_resource_categories', renamed={'id':('id','INT NOT NULL AUTO_INCREMENT','用途自增主键')})
change('keenrobot_skill_uploaded_files', removed=('current_version_id','current_revision'), renamed={
    'id':('id','INT NOT NULL AUTO_INCREMENT','独立长期文件自增主键'),
    'uploaded_by':('create_user_login_name','VARCHAR(10) NOT NULL','上传人工号'),
    'category_id':('category_id','INT NOT NULL','资源用途整数编号')},
    keys=['PRIMARY KEY(id)','UNIQUE KEY uq_file_category_hash(category_id,sha256)','KEY idx_uploaded_owner(create_user_login_name,state)'],
    comment='独立长期挂载文件；不维护文件版本，不保存沙箱临时输入文档')
change('keenrobot_skill_resource_bindings', removed=('source_version','source_version_id'), renamed={
    'id':('id','INT NOT NULL AUTO_INCREMENT','挂载关联自增主键'),
    'skill_version_id':('skill_version_id','INT NOT NULL','技能版本整数主键'),
    'source_id':('source_id','INT NULL','来源对象整数主键；不表示用途'),
    'file_id':('file_id','INT NULL','长期文件整数主键；非文件来源为空')},
    keys=['PRIMARY KEY(id)','UNIQUE KEY uq_binding_source(skill_version_id,source_type,source_id)','UNIQUE KEY uq_skill_version_file(skill_version_id,file_id)',
        'KEY idx_binding_skill(skill_id,skill_version_id)','KEY idx_binding_file(file_id)'],
    comment='技能版本与上传文件或知识库的挂载关系；关联由业务事务校验')
change('keenrobot_skill_debug_runs', renamed={
    'id':('id','INT NOT NULL AUTO_INCREMENT','任务版本关联自增主键'),
    'skill_version_id':('skill_version_id','INT NOT NULL','本次实际技能版本'),
    'created_by':('create_user_login_name','VARCHAR(10) NOT NULL','任务发起人工号')})
change('keenrobot_skill_publications', renamed={
    'id':('id','INT NOT NULL AUTO_INCREMENT','上下线历史自增主键'),
    'skill_version_id':('skill_version_id','INT NOT NULL','操作的技能版本整数主键'),
    'operator_id':('operator_login_name','VARCHAR(10) NOT NULL','平台操作人工号')}, added=(
        ('version','VARCHAR(32) NULL','操作时的对外版本号'),
        ('reason_code','VARCHAR(32) NULL','下线原因枚举'),
        ('reason_text','VARCHAR(500) NULL','其他原因说明')))
def create_sql(name, actual_name):
    comment, columns, keys = TABLES[name]
    specs = [f"`{n}` {t} COMMENT '{c}'" for n,t,c in columns] + keys
    return f"CREATE TABLE `{actual_name}` (" + ',\n'.join(specs) + \
        f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='{comment}'"
