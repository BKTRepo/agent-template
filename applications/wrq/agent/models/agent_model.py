"""WRQ模型：版本元数据与唯一表单分开，沙箱执行结果由同事维护。"""
from enum import Enum

from tortoise import fields, models
from applications.base.services.scaffold import ScaffoldModel, StateModel, TimestampMixin, unique_identify

class DeveloperSkillClass(models.Model):
    id = fields.IntField(pk=True, description="技能大类自增主键")
    name = fields.CharField(max_length=128, unique=True, description="技能大类名称")
    is_enabled = fields.BooleanField(default=True, description="是否启用")
    class Meta:
        table = "keenrobot_skill_classes"


class SkillDisplayStatus(str, Enum):
    """技能当前版本的持久化业务状态，与页面状态一一对应。"""
    DRAFT = "DRAFT"
    DEBUGGING = "DEBUGGING"
    DEBUG_SUCCESS = "DEBUG_SUCCESS"
    DEBUG_FAILED = "DEBUG_FAILED"
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"

class Skill(models.Model):
    id = fields.CharField(max_length=64, pk=True, default=unique_identify, description="技能唯一编号")
    name = fields.CharField(max_length=128, description="技能名称；仅未删除记录唯一")
    create_user_login_name = fields.CharField(max_length=10, description="创建人工号")
    update_user_login_name = fields.CharField(max_length=10, null=True, description="最近修改人工号")
    application_paso = fields.CharField(max_length=100, null=True, description="当前应用PASO；星号表示全应用")
    skill_classes_id = fields.IntField(description="当前技能大类编号")
    display_status = fields.CharEnumField(
        enum_type=SkillDisplayStatus,
        max_length=16,
        default=SkillDisplayStatus.DRAFT,
        description="草稿 调试中 调试成功 调试失败 已上线 已下线",
    )
    current_version_id = fields.IntField(null=True, description="当前技能版本整数编号")
    published_version_id = fields.IntField(null=True, description="最近一次成功上线的技能版本整数编号")
    current_revision = fields.IntField(default=1, description="当前修订次数")
    last_debug_run_id = fields.CharField(max_length=128, null=True, description="最近登记的当前版本任务编号")
    published_at = fields.DatetimeField(null=True, description="最近已记录的上线时间")
    offline_at = fields.DatetimeField(null=True, description="最近已记录的下线时间")
    state = fields.SmallIntField(default=0, description="0正常 1软删除")
    created_time = fields.DatetimeField(auto_now_add=True, description="创建时间")
    updated_time = fields.DatetimeField(auto_now=True, description="更新时间")
    class Meta:
        table = "keenrobot_skills"
    # 只供平台旧接口序列化兼容，不在 SQL 中重复保存表单。
    @property
    def config(self):
        return getattr(self, "_form_config", {})
    @config.setter
    def config(self, value):
        self._form_config = value

    @property
    def description(self):
        return self.config.get("description", "")

    @property
    def is_enabled(self):
        return self.display_status == "ONLINE"

class SkillVersion(models.Model):
    id = fields.IntField(pk=True, description="技能版本整数主键")
    skill_id = fields.CharField(max_length=64, index=True, description="所属技能编号")
    version = fields.CharField(max_length=32, null=True, description="对外显示版本号；首次成功上线前为空")
    revision = fields.IntField(description="技能内修订次数")
    build_id = fields.CharField(max_length=64, null=True, description="本版不可变构建编号")
    package_storage_key = fields.CharField(max_length=512, null=True, description="本版构建包位置")
    manifest_hash = fields.CharField(max_length=64, null=True, description="本版指令与固定资源校验摘要")
    create_user_login_name = fields.CharField(max_length=10, description="保存本版的工号；历史缺失不伪造")
    update_user_login_name = fields.CharField(max_length=10, null=True, description="更新版本元数据的工号")
    created_time = fields.DatetimeField(auto_now_add=True, description="版本保存时间")
    updated_time = fields.DatetimeField(auto_now=True, description="版本元数据更新时间")
    class Meta:
        table = "keenrobot_skill_versions"
        unique_together = (("skill_id", "revision"),)

class SkillForm(models.Model):
    id = fields.IntField(pk=True, description="表单自增主键")
    skill_version_id = fields.IntField(unique=True, description="技能版本编号；一版一份表单")
    name = fields.CharField(max_length=128, description="这一版技能名称")
    skill_class_id = fields.IntField(description="所属技能大类整数编号")
    application_paso = fields.CharField(max_length=100, null=True, description="门户应用PASO；星号表示全应用")
    description = fields.TextField(description="描述")
    instructions = fields.TextField(description="执行指令")
    resource_usage = fields.TextField(null=True, description="资源使用说明")
    compatibility = fields.TextField(null=True, description="运行环境要求")
    skill_markdown_path = fields.CharField(max_length=200, default="", description="Skill定义受控相对路径；未生成为空")
    technical_name = fields.CharField(max_length=128, default="", description="该版Skill技术名称")
    class Meta:
        table = "keenrobot_skill_forms"

class ResourceCategory(models.Model):
    id = fields.IntField(pk=True, description="用途分类自增主键")
    code = fields.CharField(max_length=16, unique=True, description="稳定代码")
    name = fields.CharField(max_length=32, description="显示名称")
    is_enabled = fields.BooleanField(default=True, description="是否允许选择")
    class Meta:
        table = "keenrobot_resource_categories"

# Python导入兼容；SQL表名和业务字段均使用category，不再表示来源。
SourceType = ResourceCategory

class Source(models.Model):
    id = fields.IntField(pk=True, description="长期资源编号")
    original_name = fields.CharField(max_length=255, description="当前原始文件名")
    extension = fields.CharField(max_length=16, description="当前文件扩展名")
    mime_type = fields.CharField(max_length=128, null=True, description="当前文件MIME类型")
    byte_size = fields.BigIntField(description="当前文件真实字节数")
    sha256 = fields.CharField(max_length=64, null=True, description="当前原件摘要；历史缺失原件时为空")
    storage_key = fields.CharField(max_length=512, description="当前原件受控存储位置")
    create_user_login_name = fields.CharField(max_length=10, description="上传人工号")
    update_user_login_name = fields.CharField(max_length=10, null=True, description="最后修改人工号")
    state = fields.CharField(max_length=16, default="ACTIVE", description="ACTIVE正常 MISSING历史原件缺失 DELETED已删除")
    deleted_at = fields.DatetimeField(null=True, description="文件软删除时间")
    category_id = fields.IntField(description="文件用途字典编号")
    created_time = fields.DatetimeField(auto_now_add=True, description="上传时间")
    updated_time = fields.DatetimeField(auto_now=True, description="最后修改时间")
    class Meta:
        table = "keenrobot_skill_uploaded_files"
        unique_together = (("category_id", "sha256"),)

    @property
    def file_name(self):
        return self.original_name

class SkillResourceBinding(models.Model):
    id = fields.IntField(pk=True, description="关联主键")
    skill_id = fields.CharField(max_length=64, description="技能编号")
    skill_version_id = fields.IntField(index=True, description="技能表单版本编号")
    source_type = fields.CharField(max_length=32, description="来源：upload knowledge_base knowledge_document")
    source_id = fields.IntField(null=True, description="来源对象整数主键；不表示用途")
    file_id = fields.IntField(null=True, description="上传文件编号；整库挂载为空")
    display_name = fields.CharField(max_length=255, default="", description="挂载时展示名称")
    usage_text = fields.TextField(null=True, description="单项资源使用说明")
    content_hash = fields.CharField(max_length=64, null=True, description="挂载内容校验摘要")
    sort_order = fields.IntField(default=0, description="该技能版本内资源展示顺序")
    created_time = fields.DatetimeField(auto_now_add=True, description="挂载建立时间")
    update_user_login_name = fields.CharField(max_length=10, null=True, description="最后修改人工号")
    updated_time = fields.DatetimeField(auto_now=True, description="最后修改时间")
    class Meta:
        table = "keenrobot_skill_resource_bindings"
        unique_together = (("skill_version_id", "source_type", "source_id"), ("skill_version_id", "file_id"))

class SkillDebugRun(models.Model):
    id = fields.IntField(pk=True, description="我方任务关联自增主键")
    run_id = fields.CharField(max_length=128, unique=True, description="同事沙箱任务编号")
    skill_id = fields.CharField(max_length=64, description="关联技能编号")
    skill_version_id = fields.IntField(index=True, description="实际执行的表单版本编号")
    build_id = fields.CharField(max_length=64, null=True, description="实际使用的构建编号")
    conversation_input = fields.TextField(default="", description="本次调试输入，不保存临时文档原件")
    request_document_count = fields.IntField(default=0, description="本次输入文档数量")
    resource_manifest_hash = fields.CharField(max_length=64, null=True, description="执行时资源清单摘要")
    result_byte_size = fields.BigIntField(null=True, description="既有结果字节数；保留同事表没有的历史信息")
    error_code = fields.CharField(max_length=64, null=True, description="既有错误码；不替代同事的任务状态")
    create_user_login_name = fields.CharField(max_length=10, description="任务发起人工号")
    created_time = fields.DatetimeField(auto_now_add=True, description="登记时间")
    updated_time = fields.DatetimeField(auto_now=True, description="关联元数据更新时间")
    class Meta:
        table = "keenrobot_skill_debug_runs"

class SkillPublication(models.Model):
    id = fields.IntField(pk=True, description="上下线操作自增主键")
    skill_id = fields.CharField(max_length=64, description="技能编号")
    skill_version_id = fields.IntField(description="操作的技能版本")
    action = fields.CharField(max_length=16, description="PUBLISH上线 OFFLINE下线")
    version = fields.CharField(max_length=32, null=True, description="操作时的对外版本号")
    operator_login_name = fields.CharField(max_length=10, description="操作人工号")
    reason_code = fields.CharField(max_length=32, null=True, description="下线原因枚举")
    reason_text = fields.CharField(max_length=500, null=True, description="选择其他时填写的具体原因")
    reason = fields.CharField(max_length=500, null=True, description="旧接口兼容原因文本")
    created_time = fields.DatetimeField(auto_now_add=True, description="操作时间")
    update_user_login_name = fields.CharField(max_length=10, null=True, description="最后修改人工号")
    updated_time = fields.DatetimeField(auto_now=True, description="最后修改时间")
    class Meta:
        table = "keenrobot_skill_publications"


class McpServer(ScaffoldModel, StateModel, TimestampMixin):
    """MCP 服务配置"""
    id = fields.CharField(
        default=unique_identify, max_length=64, pk=True, description="MCP服务ID"
    )
    name = fields.CharField(max_length=128, description="服务名称")
    description = fields.TextField(null=True, description="服务描述")
    user = fields.ForeignKeyField(
        "models.User",
        related_name="mcp_servers",
        on_delete=fields.CASCADE,
        description="所属用户",
    )
    is_enabled = fields.BooleanField(default=True, description="是否启用")
    transport = fields.CharField(
        max_length=32, default="stdio", description="传输方式(stdio/sse/http)"
    )
    config = fields.JSONField(null=True, description="连接配置")

    class Meta:
        table = "keenrobot_mcp_servers"
