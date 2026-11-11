"""Only facts without an existing durable source: login, chat request and new knowledge mounts."""
from tortoise import fields, models


class OverviewEvent(models.Model):
    id = fields.BigIntField(pk=True)
    event_key = fields.CharField(max_length=128, unique=True)
    kind = fields.CharField(max_length=32, index=True)
    occurred_at = fields.DatetimeField(index=True)
    operator_login_name = fields.CharField(max_length=32)
    data = fields.JSONField(default=dict)

    class Meta:
        table = 'keenrobot_overview_events'
        indexes = (('kind', 'occurred_at'),)
