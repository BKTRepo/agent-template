import asyncio

import pytest
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError

from applications.agent.models.agent_model import Skill
from applications.agent.skill_names import skill_name_key
from applications.agent.services.skill_name_migration import migrate_skill_names
from test_skill_package_api import setup, token
from test_skill_developer_form import form, submit


@pytest.mark.asyncio
async def test_names_global_normalized_edit_and_delete(setup):
    client, owner, other, skill = setup
    created = (await client.post('/skills/', headers=token(owner), json={'name': ' Skill ABC ', 'is_enabled': False})).json()
    assert created['status'] == 'success'
    skill_id = created['data']['id']
    assert created['data']['name'] == 'Skill ABC'
    duplicate = (await client.post('/skills/', headers=token(other), json={'name': 'ＳＫＩＬＬ ａｂｃ'})).json()
    assert duplicate['status'] == 'failure' and duplicate['data']['errors'][0]['field'] == 'skill_name'
    check = '/skills/name-availability'
    assert not (await client.get(check, headers=token(other), params={'name': 'skill abc'})).json()['data']['available']
    assert (await client.get(check, headers=token(owner), params={'name': 'skill abc', 'exclude_id': skill_id})).json()['data']['available']
    denied = (await client.get(check, headers=token(other), params={'name': 'skill abc', 'exclude_id': skill_id})).json()
    assert denied['status'] == 'failure' and denied['message'] == '技能不存在'
    edit = (await client.put(f'/skills/{skill_id}', headers=token(owner), json={'name': 'skill abc'})).json()
    assert edit['status'] == 'success'
    for name in [None, '   ', skill.name]:
        bad = (await client.put(f'/skills/{skill_id}', headers=token(owner), json={'name': name})).json()
        assert bad['status'] == 'failure' and bad['data']['errors'][0]['field'] == 'skill_name'
    assert (await client.delete(f'/skills/{skill_id}', headers=token(owner))).json()['status'] == 'success'
    replacement = await Skill.create(name='Skill ABC', user_id=other.id)
    deleted = await Skill.get(id=skill_id)
    assert deleted.name_key is None
    deleted.state = 0
    with pytest.raises(IntegrityError):
        await deleted.save()
    assert replacement.name_key == skill_name_key('skill abc')


@pytest.mark.asyncio
async def test_concurrent_creation_and_database_constraint(setup):
    client, owner, _, skill = setup
    replies = await asyncio.gather(*[
        client.post('/skills/', headers=token(owner), json={'name': name})
        for name in ['Parallel Skill', 'ＰＡＲＡＬＬＥＬ ＳＫＩＬＬ']
    ])
    assert sorted(response.json()['status'] for response in replies) == ['failure', 'success']
    assert await Skill.filter(name_key=skill_name_key('parallel skill')).count() == 1
    # 绕过 API 预查询，模型写入仍受到数据库唯一约束保护。
    with pytest.raises(IntegrityError):
        await Skill.create(name=' PARALLEL SKILL ', user_id=owner.id)


@pytest.mark.asyncio
async def test_form_duplicate_does_not_publish_or_rename(setup):
    client, owner, other, skill = setup
    await Skill.create(name='别人的技能', user_id=other.id)
    original = skill.name
    result = await submit(client, owner, form(skill, skill_name='别人的技能'))
    assert result['status'] == 'failure' and result['data']['errors'][0]['field'] == 'skill_name'
    await skill.refresh_from_db()
    assert skill.name == original
    history = (await client.get(f'/skills/{skill.id}/builds', headers=token(owner))).json()['data']
    assert history['total'] == 0


@pytest.mark.asyncio
async def test_migration_audits_before_any_schema_change(database):
    connection = Tortoise.get_connection('default')
    await connection.execute_script('DROP TABLE keenrobot_skills; CREATE TABLE keenrobot_skills (id TEXT PRIMARY KEY, name TEXT, state INT);')
    await connection.execute_query('INSERT INTO keenrobot_skills VALUES (?, ?, ?)', ['one', 'Skill ABC', 0])
    await connection.execute_query('INSERT INTO keenrobot_skills VALUES (?, ?, ?)', ['two', 'ＳＫＩＬＬ ａｂｃ', 0])
    conflict = await migrate_skill_names(connection, apply=True)
    assert not conflict['ready'] and not conflict['applied'] and conflict['duplicate_ids'] == [['one', 'two']]
    columns = await connection.execute_query_dict('PRAGMA table_info(keenrobot_skills)')
    assert 'name_key' not in [row['name'] for row in columns]
    await connection.execute_query('UPDATE keenrobot_skills SET state = 1 WHERE id = ?', ['two'])
    audit = await migrate_skill_names(connection)
    assert audit['ready'] and not audit['applied']
    assert (await migrate_skill_names(connection, apply=True))['applied']
    assert (await migrate_skill_names(connection, apply=True))['applied']
    rows = await connection.execute_query_dict('SELECT * FROM keenrobot_skills ORDER BY id')
    assert rows[0]['name'] == 'Skill ABC' and rows[0]['name_key'] == skill_name_key('skill abc')
    assert rows[1]['name_key'] is None and rows[1]['name'] == 'ＳＫＩＬＬ ａｂｃ'
    with pytest.raises(IntegrityError):
        await connection.execute_query('INSERT INTO keenrobot_skills VALUES (?, ?, ?, ?)', ['three', 'skill abc', 0, skill_name_key('skill abc')])


@pytest.mark.asyncio
async def test_migration_invalid_active_name_is_blocked(database):
    connection = Tortoise.get_connection('default')
    await connection.execute_script('DROP TABLE keenrobot_skills; CREATE TABLE keenrobot_skills (id TEXT PRIMARY KEY, name TEXT, state INT);')
    await connection.execute_query('INSERT INTO keenrobot_skills VALUES (?, ?, ?)', ['one', '  ', 0])
    result = await migrate_skill_names(connection, apply=True)
    assert not result['ready'] and result['invalid_ids'] == ['one'] and not result['applied']
