"""沿用项目 Tortoise ORM；试用 SQLite 与正式 MySQL 共用同一组模型。"""
from tortoise import Model, fields


class TrimmerConfig(Model):
    key = fields.CharField(max_length=64, pk=True)
    version = fields.CharField(max_length=64)
    value = fields.JSONField(description='裁剪规则、文案及默认选项')
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = 'keenrobot_trimmer_config'


class SystemAutomationAsset(Model):
    id = fields.BigIntField(pk=True)
    system_name = fields.CharField(max_length=100, unique=True)
    has_automation = fields.BooleanField()
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = 'keenrobot_system_automation_asset'


class MarkdownDocument(Model):
    id = fields.BigIntField(pk=True)
    document_id = fields.CharField(max_length=32, unique=True)
    requirement_id = fields.CharField(max_length=100, default='', index=True)
    requirement_name = fields.CharField(max_length=200, index=True)
    filename = fields.CharField(max_length=160)
    file_key = fields.CharField(max_length=40, unique=True)
    download_url = fields.CharField(max_length=240)
    config_version = fields.CharField(max_length=64)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)

    class Meta:
        table = 'keenrobot_trimmer_markdown_document'
        indexes = (('requirement_id', 'created_at'), ('requirement_name', 'created_at'))
