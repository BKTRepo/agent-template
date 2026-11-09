from tortoise import fields, models


class Asset(models.Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=128)
    skill_classes_id = fields.IntField()
    application_identify = fields.CharField(max_length=100)
    created_by = fields.BigIntField()
    visibility = fields.CharField(max_length=16, default="private")
    source_artifact_id = fields.CharField(max_length=128, unique=True)
    created_time = fields.DatetimeField(auto_now_add=True)
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "keenrobot_assets"
        indexes = (("deleted_at", "created_time", "id"), ("skill_classes_id", "deleted_at", "created_time", "id"))


class AssetFile(models.Model):
    id = fields.IntField(pk=True)
    asset = fields.ForeignKeyField("models.Asset", related_name="files", on_delete=fields.RESTRICT)
    file_name = fields.CharField(max_length=255)
    storage_key = fields.CharField(max_length=512, unique=True)
    size_bytes = fields.BigIntField()

    class Meta:
        table = "keenrobot_asset_files"
