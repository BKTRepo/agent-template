"""显式执行 python -m applications.wrq.migrations.review_20261024 --apply。

默认只读规划；备份我们自己的旧数据与DDL，保护所有其它表。
MySQL DDL会自动提交，因此保存逐步日志和迁移前快照，禁止启动时调用。
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import ssl
import sys
import asyncmy
from asyncmy.cursors import DictCursor
from configure import PROJECT_CONFIG

ROOT=Path(__file__).resolve().parents[3]
OWNED={'keenrobot_skills','keenrobot_skill_classes','keenrobot_skill_forms','keenrobot_source_types',
       'keenrobot_sources','keenrobot_source_versions','keenrobot_skill_resource_bindings',
       'keenrobot_skill_knowledge_bindings','keenrobot_skill_debug_runs'}
LEGACY={'keenrobot_skill_versions','keenrobot_skill_uploaded_files','keenrobot_skill_debug_documents','keenrobot_skill_publications'}

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

async def connect():
    cfg=PROJECT_CONFIG
    ctx=ssl.create_default_context()
    if cfg.DATABASE_SSL_CA:
        ctx.load_verify_locations(cafile=cfg.DATABASE_SSL_CA)
    else:
        ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    return await asyncmy.connect(host=cfg.DATABASE_HOST,port=int(cfg.DATABASE_PORT),
        user=cfg.DATABASE_USERNAME,password=cfg.DATABASE_PASSWORD,db=cfg.DATABASE_NAME,
        ssl=ctx,autocommit=True,cursor_cls=DictCursor,connect_timeout=15,read_timeout=30)

async def snapshot(cur):
    await cur.execute('SHOW TABLES')
    names=[next(iter(r.values())) for r in await cur.fetchall()]
    result={}
    for name in names:
        await cur.execute(f'SHOW CREATE TABLE `{name}`')
        ddl=(await cur.fetchone())['Create Table']
        await cur.execute(f'SELECT * FROM `{name}`')
        rows=list(await cur.fetchall())
        rows.sort(key=lambda r:json.dumps(r,sort_keys=True,default=str))
        result[name]={'ddl':ddl,'count':len(rows),'hash':digest(rows)}
        if name in OWNED|LEGACY:
            result[name]['rows']=rows
    return result

async def run(apply=False):
    conn=await connect()
    folder=ROOT.parent/'.tmp/wrq-db-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder.mkdir(parents=True,exist_ok=True)
    journal=[]
    try:
        async with conn.cursor() as cur:
            before=await snapshot(cur)
            (folder/'before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            await cur.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            tls=await cur.fetchone()
            if not tls['Value']:
                raise RuntimeError('拒绝无TLS迁移')
            # 所有业务数据先备份；没有显式 --apply 就停在只读规划。
            if not apply:
                print(json.dumps({'mode':'plan','backup':str(folder),'tls':tls['Value'],
                    'owned_existing':sorted(OWNED&before.keys()),'protected':sorted(before.keys()-OWNED-LEGACY)},ensure_ascii=False))
                return
            if 'keenrobot_skill_forms' in before:
                raise RuntimeError('目标表已存在；请核对迁移日志，禁止重复套用旧结构迁移')
            if before['keenrobot_skill_resource_bindings']['count']:
                raise RuntimeError('旧文件关联非空，需要先人工映射；本迁移拒绝丢弃关联')
            # 若同事将自己的外键指向将调整的列，先停止，不操作其表。
            await cur.execute('SELECT TABLE_NAME,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE '
                'WHERE REFERENCED_TABLE_SCHEMA=%s AND REFERENCED_TABLE_NAME IN (%s,%s)',
                [PROJECT_CONFIG.DATABASE_NAME,'keenrobot_skills','keenrobot_skill_debug_runs'])
            for ref in await cur.fetchall():
                if ref['TABLE_NAME'] not in OWNED and ref['REFERENCED_COLUMN_NAME']!='id':
                    raise RuntimeError('存在其它模块外键，停止迁移')

            async def execute(sql,args=None):
                mutation=re.match(r'\s*(?:CREATE TABLE(?: IF NOT EXISTS)?|ALTER TABLE|DROP TABLE|INSERT INTO|UPDATE|DELETE FROM)\s+`?(\w+)',sql,re.I)
                if mutation and mutation[1] not in OWNED:
                    raise RuntimeError('拒绝写入不属于WRQ的表')
                await cur.execute(sql,args)
                journal.append({'statement':sql,'affected':cur.rowcount})
                (folder/'journal.json').write_text(json.dumps(journal,ensure_ascii=False,indent=2,default=str),encoding='utf8')

            design=(ROOT.parent/'deliverables/开发者中心_数据库设计_按11项评审修订_20261023_目标结构_仅供评审.sql').read_text('utf8')
            definitions={name:sql for name,sql in [(m[1],m[0]) for m in re.finditer(r'CREATE TABLE (\w+) \([\s\S]*?\) ENGINE[^;]+;',design)]}
            forms=definitions['keenrobot_skill_forms'].replace('  created_by VARCHAR(64)',
                "  build_id VARCHAR(64) NULL COMMENT '本版本构建编号，定位不可变原文件包',\n  created_by VARCHAR(64)")
            knowledge=definitions['keenrobot_skill_knowledge_bindings'].replace('  skill_version_id INT',
                "  id INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '知识库挂载关联主键',\n  skill_version_id INT",1).replace(
                'PRIMARY KEY (skill_version_id, knowledge_base_id)',
                'PRIMARY KEY (id),\n  UNIQUE KEY uq_knowledge_binding (skill_version_id, knowledge_base_id)')
            for name,sql in [('keenrobot_source_types',definitions['keenrobot_source_types']),('keenrobot_skill_forms',forms),
                ('keenrobot_sources',definitions['keenrobot_sources']),('keenrobot_source_versions',definitions['keenrobot_source_versions']),
                ('keenrobot_skill_knowledge_bindings',knowledge)]:
                await execute(sql)
            await execute("INSERT INTO keenrobot_source_types (id,code,name,is_enabled) VALUES (1,'reference','参考资料',1),(2,'template','模板',1),(3,'asset','静态资源',1),(4,'script','脚本',1)")
            # 门户ID由字符串保存；只移除我们技能表上的旧用户FK，不改用户表。
            await cur.execute('SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=%s '
                'AND TABLE_NAME=%s AND REFERENCED_TABLE_NAME IS NOT NULL',[PROJECT_CONFIG.DATABASE_NAME,'keenrobot_skills'])
            for row in await cur.fetchall():
                await execute(f"ALTER TABLE keenrobot_skills DROP FOREIGN KEY `{row['CONSTRAINT_NAME']}`")
            await execute("ALTER TABLE keenrobot_skills MODIFY user_id VARCHAR(64) NOT NULL COMMENT '门户创建者编号', ADD current_form_id INT UNSIGNED NULL COMMENT '迁移中的当前表单版本编号'")
            skills=before['keenrobot_skills']['rows']; versions=before['keenrobot_skill_versions']['rows']
            version_map={}
            for skill in skills:
                config=skill.get('config') or {}
                if isinstance(config,str): config=json.loads(config)
                histories=sorted([r for r in versions if r['skill_id']==skill['id']],key=lambda r:r['revision'])
                if not histories:
                    histories=[{'id':None,'revision':skill.get('current_revision') or 1}]
                for old in histories:
                    current=(old.get('id')==skill.get('current_version_id')) or (old is histories[-1] and not skill.get('current_version_id'))
                    revision=old['revision']
                    values={'skill_id':skill['id'],'revision':revision,'skill_name':skill['name'],
                        'skill_class_id':old.get('skill_class_id') or config.get('class_id') or 'SKILL-CASE-001',
                        'application_id':old.get('application_id'),'description':old.get('description') or skill.get('description') or '',
                        'instructions':old.get('instructions') or '', 'resource_usage':old.get('resource_usage'),
                        'compatibility':old.get('compatibility'),'skill_markdown':old.get('skill_markdown') or '',
                        'build_id':old.get('build_id'),'created_by':str(old.get('created_by') or skill['user_id']),
                        'created_time':old.get('created_time') or skill['created_time']}
                    if current:
                        for key in ['instructions','resource_usage','compatibility','skill_markdown']:
                            if config.get(key) is not None: values[key]=config[key]
                        values['skill_class_id']=config.get('class_id') or values['skill_class_id']
                        values['application_id']=(config.get('application_ids') or [values['application_id']])[0]
                        values['build_id']=config.get('latest_build_id') or values['build_id']
                    fields=','.join(values)
                    await execute(f"INSERT INTO keenrobot_skill_forms ({fields}) VALUES ({','.join(['%s']*len(values))})",list(values.values()))
                    new_id=cur.lastrowid
                    if old.get('id'): version_map[old['id']]=new_id
                    if current or old is histories[-1]:
                        await execute('UPDATE keenrobot_skills SET current_form_id=%s,current_revision=%s,updated_time=%s WHERE id=%s',[new_id,revision,skill['updated_time'],skill['id']])
                    if current:
                        for kb in config.get('resource_ids',[]):
                            await execute('INSERT INTO keenrobot_skill_knowledge_bindings (skill_version_id,knowledge_base_id,knowledge_base_version) VALUES (%s,%s,%s)',[new_id,kb,'legacy'])
            # 旧文件关联当前为空；新表结构严格关联技能/文件的具体版本。
            await execute('DROP TABLE keenrobot_skill_resource_bindings')
            await execute(definitions['keenrobot_skill_resource_bindings'])
            # 只保留关联键。状态、结果路径等以同事现有表为唯一来源。
            await execute('DROP TABLE keenrobot_skill_debug_runs')
            await execute("""CREATE TABLE keenrobot_skill_debug_runs (
                run_id VARCHAR(128) NOT NULL COMMENT '同事沙箱任务唯一编号',
                skill_id VARCHAR(64) NOT NULL COMMENT '技能编号',
                skill_version_id INT UNSIGNED NOT NULL COMMENT '实际执行的技能表单版本编号',
                user_id VARCHAR(64) NOT NULL COMMENT '门户发起人编号',
                created_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '登记时间',
                PRIMARY KEY(run_id), KEY idx_debug_version(skill_id,skill_version_id,created_time),
                CONSTRAINT fk_debug_form FOREIGN KEY(skill_version_id,skill_id) REFERENCES keenrobot_skill_forms(id,skill_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='WRQ技能版本与同事run_id的关联；不重复保存沙箱运行结果'""")
            for old in before['keenrobot_skill_debug_runs']['rows']:
                vid=version_map.get(old['skill_version_id'])
                if vid:
                    await execute('INSERT INTO keenrobot_skill_debug_runs (run_id,skill_id,skill_version_id,user_id,created_time) VALUES (%s,%s,%s,%s,%s)',
                        [old['run_id'],old['skill_id'],vid,str(old['created_by']),old['created_time']])
            removed=['name_key','description','is_enabled','current_version_id','last_debug_run_id','last_debug_passed_at','published_at','offline_at','config']
            await execute('ALTER TABLE keenrobot_skills '+', '.join('DROP COLUMN '+col for col in removed)+
                ", CHANGE current_form_id current_version_id INT UNSIGNED NULL COMMENT '当前技能表单版本编号',"+
                " MODIFY name VARCHAR(128) NOT NULL COMMENT '技能名称；仅未删除记录唯一',"+
                " MODIFY current_revision INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '当前修订次数，从1开始',"+
                " MODIFY display_status ENUM('DRAFT','DEBUGGING','DEBUG_SUCCESS','DEBUG_FAILED','ONLINE','OFFLINE') NOT NULL DEFAULT 'DRAFT' COMMENT '草稿 调试中 调试成功 调试失败 已上线 已下线',"+
                " MODIFY state TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0正常 1软删除',"+
                " MODIFY id VARCHAR(64) NOT NULL COMMENT '技能唯一编号',"+
                " MODIFY created_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',"+
                " MODIFY updated_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',"+
                " COMMENT='WRQ技能主表；表单内容另存版本快照，门户用户仅引用编号'")
            await execute("ALTER TABLE keenrobot_skills ADD UNIQUE INDEX uq_skills_active_name ((CASE WHEN state=0 THEN LOWER(TRIM(name)) ELSE NULL END))")
            await execute("ALTER TABLE keenrobot_skills ADD CONSTRAINT fk_skills_current_form FOREIGN KEY(current_version_id,id) REFERENCES keenrobot_skill_forms(id,skill_id)")
            await execute("ALTER TABLE keenrobot_sources ADD CONSTRAINT fk_sources_current_version FOREIGN KEY(current_version_id,id) REFERENCES keenrobot_source_versions(id,source_id)")
            await execute("ALTER TABLE keenrobot_skill_classes DROP COLUMN sort_order, MODIFY id VARCHAR(64) NOT NULL COMMENT '技能大类编号', MODIFY name VARCHAR(128) NOT NULL COMMENT '技能大类名称', MODIFY is_enabled BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否启用', COMMENT='WRQ技能大类字典；不维护排序字段'")
            # 旧表保留只读备查，不删除历史版本/文件/发布数据，不更新aerich。
            after=await snapshot(cur)
            protected=before.keys()-OWNED-LEGACY
            checks={name:{'ddl_unchanged':before[name]['ddl']==after[name]['ddl'],
                'rows_unchanged':before[name]['hash']==after[name]['hash']} for name in protected}
            report={'backup':str(folder),'tls':tls['Value'],'protected_tables':checks,
                'migrated_skill_count':len(skills),'form_count':after['keenrobot_skill_forms']['count'],
                'owned_tables':sorted(OWNED),'legacy_tables_retained':sorted(LEGACY)}
            (folder/'after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            if not all(r['ddl_unchanged'] and r['rows_unchanged'] for r in checks.values()):
                raise RuntimeError('检测到共享表在迁移期间变化；请核对报告，不自动回滚同事数据')
            print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        conn.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--apply',action='store_true'); args=parser.parse_args()
    if sys.platform=='win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run(args.apply))
