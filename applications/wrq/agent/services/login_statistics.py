"""Persist successful platform logins atomically; keep only observed historical facts."""
from datetime import datetime
from uuid import uuid4

from tortoise.transactions import in_transaction

from applications.user.models.user_model import User
from applications.wrq.models.overview_event_model import OverviewEvent


async def record_successful_login(user_id):
    async with in_transaction() as db:
        user = await User.filter(id=user_id).using_db(db).select_for_update().get()
        # Match the stable platform user ID; a later account rename must not reset statistics.
        _, existing = await db.execute_query(
            "SELECT id FROM keenrobot_overview_events WHERE kind=%s "
            "AND JSON_UNQUOTE(JSON_EXTRACT(data,'$.user_id'))=%s LIMIT 1",
            ['login', str(user.id)],
        )
        if not existing and user.last_login is not None:
            # last_login proves one actual earlier login, not a complete historical total.
            await OverviewEvent.get_or_create(event_key=f'login:observed-last-login:{user.id}',
                using_db=db, defaults={'kind': 'login', 'occurred_at': user.last_login,
                    'operator_login_name': user.username,
                    'data': {'user_id': user.id, 'username': user.alias or user.username,
                             'source': 'observed_last_login'}})
        logged_at = datetime.now()
        await OverviewEvent.create(event_key='login:' + uuid4().hex, kind='login', occurred_at=logged_at,
            operator_login_name=user.username, data={'user_id': user.id, 'username': user.alias or user.username},
            using_db=db)
        await User.filter(id=user.id).using_db(db).update(last_login=logged_at)
        return logged_at
