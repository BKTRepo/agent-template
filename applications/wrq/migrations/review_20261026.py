"""显式迁移WRQ自有表。默认只读规划，--apply才执行，启动服务绝不调用。

先备份/逐值规划、影子表加载和约束验证，最后原子换名；同事任务表、用户、应用、
审计和aerich全程禁止写入。MySQL DDL自动提交，每一步留下本地日志。
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
from pathlib import Path
import sys
from applications.wrq.migrations.review_20261024 import connect, digest
from applications.wrq.migrations.schema_20261026 import TABLES, FOREIGN_KEYS, create_sql
from configure import PROJECT_CONFIG

ROOT=Path(__file__).resolve().parents[3]
PROTECTED={'keenrobot_user','keenrobot_applications','keenrobot_online_debug_runs','keenrobot_audit','aerich'}
EXTRA={'keenrobot_sources','keenrobot_skill_knowledge_bindings'}
OLD_CATEGORY='keenrobot_source_types'
NEW_PREFIX='_wrq26_new_'
OLD_PREFIX='_wrq26_old_'
CONTENT=('skill_class_id','application_id','description','instructions','resource_usage','compatibility','skill_markdown')

def serial(value):
    return json.dumps(value,ensure_ascii=False,indent=2,default=str)

async def snapshot(cur):
    await cur.execute('SHOW TABLES')
    names=[next(iter(r.values())) for r in await cur.fetchall()]
    result={}
    for name in names:
        if not name.replace('_','').isalnum(): raise RuntimeError('非法表名')
        await cur.execute(f'SHOW CREATE TABLE `{name}`'); ddl=(await cur.fetchone())['Create Table']
        await cur.execute(f'SELECT * FROM `{name}`'); rows=list(await cur.fetchall())
        rows.sort(key=lambda r:json.dumps(r,sort_keys=True,default=str))
        entry={'ddl':ddl,'count':len(rows),'hash':digest(rows)}
        if name not in PROTECTED: entry['rows']=rows
        result[name]=entry
    return result

def build_plan(before, history):
    """纯数据映射，可离线测试；有实质冲突时拒绝迁移。"""
    data={n:[] for n in TABLES}; issues=[]; notes=[]; version_map={}
    rows=lambda name:before.get(name,{}).get('rows',[])
    old_skills={r['id']:r for r in history.get('keenrobot_skills',{}).get('rows',[])}
    known_config={'class_id','application_ids','description','instructions','resource_usage','compatibility',
        'technical_name','skill_markdown','uploaded_resources','resource_ids','knowledge_bases'}
    for sid,row in old_skills.items():
        config=row.get('config') or {}; config=json.loads(config) if isinstance(config,str) else config
        for key,value in config.items():
            if key not in known_config and value not in (None,'',[],{}):
                issues.append({'kind':'unmapped_config_key','skill':sid,'key':key})
        if len(config.get('application_ids') or [])>1:
            issues.append({'kind':'historical_multiple_applications','skill':sid})
    old_debug={r['run_id']:r for r in history.get('keenrobot_skill_debug_runs',{}).get('rows',[])}
    skills={r['id']:r for r in rows('keenrobot_skills')}
    current_forms={r['id']:r for r in rows('keenrobot_skill_forms')}
    by_revision={(r['skill_id'],r['revision']):r for r in current_forms.values()}
    old_versions=rows('keenrobot_skill_versions')
    old_by_revision={}
    for v in old_versions:
        key=(v['skill_id'],v['revision']); old_by_revision[key]=v
        match=by_revision.get(key)
        if not match:
            issues.append({'kind':'missing_historical_version','version':v['id']}); continue
        version_map[v['id']]=match['id']
        for field in CONTENT:
            if (v.get(field) or '')!=(match.get(field) or ''):
                issues.append({'kind':'version_content_conflict','version':v['id'],'field':field})
    data['keenrobot_resource_categories']=[dict(r) for r in rows(OLD_CATEGORY)]
    if len(data['keenrobot_resource_categories'])!=4: issues.append({'kind':'unexpected_categories'})
    for form in current_forms.values():
        old=old_by_revision.get((form['skill_id'],form['revision']),{})
        version_map[str(form['id'])]=form['id']
        skill=skills.get(form['skill_id'])
        if not skill: issues.append({'kind':'orphan_form','id':form['id']}); continue
        source=old_skills.get(form['skill_id'],{}).get('config') or {}
        if isinstance(source,str): source=json.loads(source)
        technical=source.get('technical_name') or 'skill-'+hashlib.sha256(form['skill_id'].encode()).hexdigest()[:24]
        package=old.get('package_storage_key'); manifest_hash=old.get('manifest_hash')
        updated=old.get('updated_time') or form['created_time']
        if form.get('build_id'):
            base=Path(PROJECT_CONFIG.SKILL_BUILD_DIR)/str(form['created_by'])/form['skill_id']/form['build_id']
            manifest=base/'manifest.json'
            if base.resolve().is_relative_to(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).resolve()) and manifest.is_file():
                raw=manifest.read_bytes(); info=json.loads(raw)
                if str(info.get('skill_id'))!=form['skill_id'] or info.get('build_id')!=form['build_id']:
                    issues.append({'kind':'manifest_identity_conflict','form':form['id']})
                technical=info.get('name') or technical
                package=str(base/'package.zip'); manifest_hash=hashlib.sha256(raw).hexdigest()
            else: notes.append({'kind':'missing_historical_build','version':form['id']})
        data['keenrobot_skill_versions'].append({'id':form['id'],'skill_id':form['skill_id'],
            'version':old.get('version') or f"1.0.{form['revision']-1}",'revision':form['revision'],
            'build_id':form.get('build_id'),'package_storage_key':package,'manifest_hash':manifest_hash,
            'created_by':str(form['created_by']),'created_time':form['created_time'],'updated_time':updated})
        data['keenrobot_skill_forms'].append({'skill_version_id':form['id'],'name':form['skill_name'],
            **{k:form.get(k) for k in CONTENT},'technical_name':technical})
    for skill in skills.values():
        form=current_forms.get(skill['current_version_id'])
        if not form or form['skill_id']!=skill['id'] or form['revision']!=skill['current_revision']:
            issues.append({'kind':'invalid_current_version','skill':skill['id']}); continue
        historic=old_skills.get(skill['id'],{})
        data['keenrobot_skills'].append({**skill,'description':form['description'],
            'is_enabled':skill['display_status']=='ONLINE',
            **{k:historic.get(k) for k in ('last_debug_run_id','last_debug_passed_at','published_at','offline_at')}})
    file_versions={}
    for v in rows('keenrobot_source_versions'):
        path=Path(v['storage_key']); sha=None
        if path.resolve().is_relative_to(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).resolve()) and path.is_file():
            with path.open('rb') as f: sha=hashlib.file_digest(f,'sha256').hexdigest()
            if path.stat().st_size!=v['byte_size']: issues.append({'kind':'file_size_changed','id':v['id']})
        else: notes.append({'kind':'missing_historical_original','file_version':v['id']})
        item={'id':v['id'],'file_id':v['source_id'],'revision':v['revision'],
            'original_name':v['original_name'],'extension':Path(v['original_name']).suffix.lower(),
            'mime_type':mimetypes.guess_type(v['original_name'])[0],'byte_size':v['byte_size'],
            'sha256':sha,'storage_key':v['storage_key'],'category_id':v['source_type_id'],
            'uploaded_by':str(v['created_by']),'state':'ACTIVE' if sha else 'MISSING',
            'created_time':v['created_time'],'deleted_at':None}
        data['keenrobot_source_versions'].append(item); file_versions[v['id']]=item
    if rows('keenrobot_skill_uploaded_files'):
        issues.append({'kind':'legacy_uploaded_files_need_id_mapping'})
    for src in rows('keenrobot_sources'):
        v=file_versions.get(src['current_version_id'])
        if not v or v['file_id']!=src['id'] or v['revision']!=src['current_revision']:
            issues.append({'kind':'invalid_current_file_version','id':src['id']}); continue
        data['keenrobot_skill_uploaded_files'].append({k:v[k] for k in ('original_name','extension','mime_type',
            'byte_size','sha256','storage_key','state','deleted_at','category_id')} | {
            'id':src['id'],'uploaded_by':str(src['created_by']),'created_time':src['created_time'],
            'current_version_id':src['current_version_id'],'current_revision':src['current_revision']})
    for row in rows('keenrobot_skill_resource_bindings'):
        v=file_versions.get(row['source_version_id'])
        f=current_forms.get(row['skill_version_id'])
        if not v or v['file_id']!=row['source_id'] or not f or f['skill_id']!=row['skill_id']:
            issues.append({'kind':'invalid_resource_binding','id':row['id']}); continue
        data['keenrobot_skill_resource_bindings'].append({'id':row['id'],'skill_id':row['skill_id'],
            'skill_version_id':row['skill_version_id'],'source_type':'upload','source_id':str(row['source_id']),
            'source_version':str(v['revision']),'file_id':row['source_id'],'source_version_id':v['id'],
            'display_name':v['original_name'],'usage_text':None,'content_hash':v['sha256'],
            'sort_order':row['id'],'created_time':f['created_time']})
    next_binding=max([r['id'] for r in data['keenrobot_skill_resource_bindings']]+[0])+1
    for row in rows('keenrobot_skill_knowledge_bindings'):
        f=current_forms.get(row['skill_version_id'])
        if not f: issues.append({'kind':'orphan_knowledge_binding','id':row['id']}); continue
        data['keenrobot_skill_resource_bindings'].append({'id':next_binding,'skill_version_id':f['id'],
            'skill_id':f['skill_id'],'source_type':'knowledge_base','source_id':row['knowledge_base_id'],
            'source_version':row['knowledge_base_version'],'file_id':None,'source_version_id':None,
            'display_name':row['knowledge_base_id'],'usage_text':None,'content_hash':None,
            'sort_order':next_binding,'created_time':f['created_time']}); next_binding+=1
    vm={v['id']:v for v in data['keenrobot_skill_versions']}
    for link in rows('keenrobot_skill_debug_runs'):
        old=old_debug.get(link['run_id'],{}); v=vm.get(link['skill_version_id'])
        if not v or v['skill_id']!=link['skill_id']:
            issues.append({'kind':'invalid_debug_link','run_id':link['run_id']}); continue
        data['keenrobot_skill_debug_runs'].append({'id':old.get('id') or 'wrq-'+hashlib.sha256(link['run_id'].encode()).hexdigest()[:40],
            'run_id':link['run_id'],'skill_id':link['skill_id'],'skill_version_id':link['skill_version_id'],
            'build_id':v['build_id'],'conversation_input':old.get('conversation_input') or '',
            'request_document_count':old.get('request_document_count') or 0,
            'resource_manifest_hash':old.get('resource_manifest_hash') or v['manifest_hash'],
            'result_byte_size':old.get('result_byte_size'),'error_code':old.get('error_code'),
            'created_by':str(link['user_id']),'created_time':link['created_time'],
            'updated_time':old.get('updated_time') or link['created_time']})
    for pub in rows('keenrobot_skill_publications'):
        vid=version_map.get(str(pub['skill_version_id']))
        if not vid: issues.append({'kind':'invalid_publication','id':pub['id']}); continue
        data['keenrobot_skill_publications'].append({**pub,'skill_version_id':vid,'operator_id':str(pub['operator_id'])})
    return data,issues,notes,version_map

async def run(apply=False):
    conn=await connect(); journal=[]; swapped=False
    folder=ROOT.parent/'.tmp/wrq-db-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-review26')
    folder.mkdir(parents=True,exist_ok=False)
    try:
        async with conn.cursor() as cur:
            await cur.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'"); tls=(await cur.fetchone())['Value']
            if not tls: raise RuntimeError('拒绝无TLS连接')
            await cur.execute("SELECT GET_LOCK('wrq_review_20261026',0) AS acquired")
            if (await cur.fetchone())['acquired']!=1: raise RuntimeError('另一个WRQ迁移正在执行')
            before=await snapshot(cur)
            (folder/'before.json').write_text(serial(before),encoding='utf8')
            if any(n.startswith((NEW_PREFIX,OLD_PREFIX)) for n in before):
                raise RuntimeError('发现上次迁移临时表，请先核对日志，不自动清除')
            if 'keenrobot_resource_categories' in before:
                raise RuntimeError('新结构已存在；拒绝重复运行旧结构迁移')
            hpath=ROOT.parent/'.tmp/wrq-db-backups/20261024T140007Z/before.json'
            if not hpath.is_file(): raise RuntimeError('恢复历史字段需要已知迁移前备份，当前未找到')
            history=json.loads(hpath.read_text('utf8'))
            data,issues,notes,version_map=build_plan(before,history)
            approved=set(TABLES)|EXTRA|{OLD_CATEGORY,'keenrobot_skill_debug_documents'}
            await cur.execute('SELECT TABLE_NAME,CONSTRAINT_NAME,REFERENCED_TABLE_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL')
            foreign=list(await cur.fetchall())
            affected=(set(TABLES)&before.keys())|{OLD_CATEGORY}
            for ref in foreign:
                if ref['REFERENCED_TABLE_NAME'] in affected and ref['TABLE_NAME'] not in approved:
                    issues.append({'kind':'external_foreign_key','table':ref['TABLE_NAME'],'target':ref['REFERENCED_TABLE_NAME']})
            report={'mode':'plan','tls':tls,'backup':str(folder),'issues':issues,'notes':notes,
                'target_counts':{n:len(v) for n,v in data.items()},'version_id_map':version_map,
                'protected_tables':sorted(PROTECTED),'shared_table_switch_required':False,
                'legacy_extra_tables_retained':sorted(EXTRA), 'unrecoverable_history':'从未记录的历史时间和缺失原件不编造；详见notes'}
            (folder/'plan.json').write_text(serial(report),encoding='utf8')
            (folder/'target_data.json').write_text(serial(data),encoding='utf8')
            if issues: raise RuntimeError('规划存在冲突，未修改数据库；详见plan.json')
            if not apply:
                print(serial({k:v for k,v in report.items() if k!='version_id_map'})); return

            async def mutate(sql,args=None,*,target):
                if target not in approved and not target.startswith((NEW_PREFIX,OLD_PREFIX)):
                    raise RuntimeError('禁止写共享表')
                await cur.execute(sql,args)
                journal.append({'target':target,'sql':sql,'affected':cur.rowcount})
                (folder/'journal.json').write_text(serial(journal),encoding='utf8')

            # 活表完全不变，先在WRQ影子表中装载和建立所有约束。
            for name in TABLES:
                await mutate(create_sql(name,NEW_PREFIX+name),target=NEW_PREFIX+name)
            for name,records in data.items():
                cols=[c[0] for c in TABLES[name][1]]
                for record in records:
                    sql=f"INSERT INTO `{NEW_PREFIX+name}` ({','.join('`'+c+'`' for c in cols)}) VALUES ({','.join(['%s']*len(cols))})"
                    await mutate(sql,[record.get(c) for c in cols],target=NEW_PREFIX+name)
            for i,(child,cols,parent,refs) in enumerate(FOREIGN_KEYS):
                parent_actual=NEW_PREFIX+parent if parent in TABLES else parent
                await mutate(f'ALTER TABLE `{NEW_PREFIX+child}` ADD CONSTRAINT `wrq26_fk_{i}` FOREIGN KEY ({cols}) REFERENCES `{parent_actual}` ({refs})',target=NEW_PREFIX+child)
            for name,records in data.items():
                await cur.execute(f'SELECT * FROM `{NEW_PREFIX+name}`'); actual=list(await cur.fetchall())
                norm=lambda rows:sorted(json.dumps({k:int(v) if isinstance(v,bool) else v for k,v in r.items()},sort_keys=True,default=str) for r in rows)
                expected=[{c[0]:r.get(c[0]) for c in TABLES[name][1]} for r in records]
                # 从JSON恢复的历史时间是字符串；MySQL读回datetime的str保持同样表示。
                if norm(actual)!=norm(expected): raise RuntimeError('影子表逐值核验失败：'+name)
            # 活表若被其他客户端修改则中止，绝不覆盖新的业务记录。
            for name in approved & before.keys():
                await cur.execute(f'SELECT * FROM `{name}`'); current=list(await cur.fetchall())
                current.sort(key=lambda r:json.dumps(r,sort_keys=True,default=str))
                if digest(current)!=before[name]['hash']: raise RuntimeError('活表已被修改，停止换表：'+name)
            renames=[]
            for name in TABLES:
                if name in before: renames.append(f'`{name}` TO `{OLD_PREFIX+name}`')
                renames.append(f'`{NEW_PREFIX+name}` TO `{name}`')
            renames.append(f'`{OLD_CATEGORY}` TO `{OLD_PREFIX+OLD_CATEGORY}`')
            await mutate('RENAME TABLE '+','.join(renames),target=NEW_PREFIX+'swap')
            swapped=True
            # 旧精简方案的额外表保留数据，仅把其外键重新指向新的真实版本和用途。
            for name in EXTRA:
                refs={r['CONSTRAINT_NAME'] for r in foreign if r['TABLE_NAME']==name}
                for key in refs:
                    await mutate(f'ALTER TABLE `{name}` DROP FOREIGN KEY `{key}`',target=name)
            if 'keenrobot_sources' in before:
                await mutate('ALTER TABLE keenrobot_sources ADD CONSTRAINT wrq26_legacy_source_category FOREIGN KEY(source_type_id) REFERENCES keenrobot_resource_categories(id), ADD CONSTRAINT wrq26_legacy_source_pointer FOREIGN KEY(current_version_id,id) REFERENCES keenrobot_source_versions(id,file_id)',target='keenrobot_sources')
            if 'keenrobot_skill_knowledge_bindings' in before:
                await mutate('ALTER TABLE keenrobot_skill_knowledge_bindings ADD CONSTRAINT wrq26_legacy_knowledge_version FOREIGN KEY(skill_version_id) REFERENCES keenrobot_skill_versions(id)',target='keenrobot_skill_knowledge_bindings')
            # 本地完整备份已保存。移除换名产生的临时旧副本，不保留两套活结构。
            old_names=[OLD_PREFIX+n for n in TABLES if n in before]+[OLD_PREFIX+OLD_CATEGORY]
            for name in old_names:
                await cur.execute('SELECT DISTINCT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND REFERENCED_TABLE_NAME IS NOT NULL',[name])
                for ref in await cur.fetchall():
                    await mutate(f"ALTER TABLE `{name}` DROP FOREIGN KEY `{ref['CONSTRAINT_NAME']}`",target=name)
            for name in old_names:
                await mutate(f'DROP TABLE `{name}`',target=name)
            if 'keenrobot_skill_debug_documents' in before:
                await mutate('DROP TABLE keenrobot_skill_debug_documents',target='keenrobot_skill_debug_documents')
            after=await snapshot(cur)
            (folder/'after.json').write_text(serial(after),encoding='utf8')
            protected={n:{'ddl_unchanged':before[n]['ddl']==after[n]['ddl'],
                'rows_unchanged':before[n]['hash']==after[n]['hash']} for n in PROTECTED if n in before}
            report.update(mode='applied',swapped=True,protected_checks=protected,
                field_counts={n:len(t[1]) for n,t in TABLES.items()})
            (folder/'report.json').write_text(serial(report),encoding='utf8')
            if not all(x['ddl_unchanged'] for x in protected.values()):
                raise RuntimeError('共享表结构发生外部变化，详见报告；未主动修改共享表')
            print(serial({k:v for k,v in report.items() if k!='version_id_map'}))
    except BaseException as exc:
        (folder/'error.json').write_text(serial({'error':type(exc).__name__,'message':str(exc),'swapped':swapped}),encoding='utf8')
        raise
    finally:
        conn.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--apply',action='store_true'); args=p.parse_args()
    if sys.platform=='win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run(args.apply))
