import asyncio
import pytest
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError
from applications.wrq.agent.models.agent_model import Skill, SkillVersion
from applications.wrq.agent.skill_names import skill_name_key
from applications.wrq.agent.services.skill_name_migration import migrate_skill_names
from developer_contract_helpers import developer_setup, payload, create_saved, update_saved
from test_skill_package_api import token


@pytest.mark.asyncio
async def test_names_global_normalized_edit_and_delete(developer_setup):
    client, owner, other = developer_setup
    row = await create_saved(client, owner, name=' Skill ABC ')
    assert row['name'] == 'Skill ABC'
    duplicate = await client.post('/skills/developer/', headers=token(other), json=payload(name='ＳＫＩＬＬ ａｂｃ'))
    assert duplicate.status_code == 409 and duplicate.json()['data']['errors'][0]['field'] == 'name'
    check = '/skills/name-availability'
    assert not (await client.get(check, headers=token(other), params={'name': 'skill abc'})).json()['data']['available']
    assert (await client.get(check, headers=token(owner), params={'name': 'skill abc', 'exclude_id': row['id']})).json()['data']['available']
    denied = await client.get(check, headers=token(other), params={'name': 'skill abc', 'exclude_id': row['id']})
    assert denied.status_code == 404 and denied.json()['status'] == 'failure'
    edited = await update_saved(client, owner, row, name='skill abc')
    assert edited.status_code == 200, edited.text
    row = edited.json()['data']
    existing = await create_saved(client, other, name='别人的名称')
    for value, status in [(None, 422), ('   ', 400), (existing['name'], 409)]:
        bad = await update_saved(client, owner, row, name=value)
        assert bad.status_code == status, bad.text
        assert bad.json()['data']['errors'][0]['field'] == 'name'
    deleted = await client.delete(f"/skills/developer/{row['id']}", headers=token(owner))
    assert deleted.status_code == 200
    replacement = await create_saved(client, other, name='Skill ABC')
    old = await Skill.get(id=row['id'])
    assert old.state == 1 and replacement['id'] != old.id
    assert await Skill.filter(state=0, name__iexact='skill abc').count() == 1
    # 恢复已删除行会撞上新记录，数据库级约束仍应拦截。
    with pytest.raises(IntegrityError):
        await Skill.filter(id=old.id).update(state=0)


@pytest.mark.asyncio
async def test_concurrent_creation_and_database_constraint(developer_setup):
    client, owner, _ = developer_setup
    responses = await asyncio.gather(*[client.post('/skills/developer/', headers=token(owner), json=payload(name=name))
        for name in ['Parallel Skill', 'ＰＡＲＡＬＬＥＬ ＳＫＩＬＬ']])
    assert sorted(v.status_code for v in responses) == [200, 409], [v.text for v in responses]
    assert await Skill.filter(state=0).count() == 1
    assert await SkillVersion.all().count() == 1
    # 不经过API预检查，直接写入同名也必须失败；未删除记录lower(trim)索引。
    winner = next(v.json()['data'] for v in responses if v.status_code == 200)
    with pytest.raises(IntegrityError):
        await Skill.create(name=' ' + winner['name'].lower() + ' ', user_id=str(owner.id))


@pytest.mark.asyncio
async def test_form_duplicate_does_not_publish_or_rename(developer_setup):
    client, owner, other = developer_setup
    await create_saved(client, other, name='别人的技能')
    row = await create_saved(client, owner)
    response = await update_saved(client, owner, row, name='别人的技能')
    assert response.status_code == 409 and response.json()['data']['errors'][0]['field'] == 'name'
    skill = await Skill.get(id=row['id'])
    assert skill.name == row['name'] and skill.current_revision == 1 and skill.display_status == 'DRAFT'
    assert await SkillVersion.filter(skill_id=row['id']).count() == 1
    history = (await client.get(f"/skills/{row['id']}/builds", headers=token(owner))).json()['data']
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
