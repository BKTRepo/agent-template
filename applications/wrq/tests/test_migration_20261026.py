"""迁移冲突拒绝与历史信息保留；不连接数据库。"""
from copy import deepcopy
from datetime import datetime
import unittest
from applications.wrq.migrations.review_20261026 import build_plan, PROTECTED
from applications.wrq.migrations.schema_20261026 import TABLES

class MigrationPlanTests(unittest.TestCase):
    def fixture(self):
        now=datetime(2026,10,26,10)
        form={'id':7,'skill_id':'skill-a','revision':1,'skill_name':'测试技能','skill_class_id':'class-a',
            'application_id':'*','description':'历史描述','instructions':'历史指令','resource_usage':None,
            'compatibility':None,'skill_markdown':'','build_id':None,'created_by':'1','created_time':now}
        old={k:form[k] for k in ('skill_id','revision','skill_class_id','application_id','description',
            'instructions','resource_usage','compatibility','skill_markdown','build_id','created_time')}
        old.update(id='old-version',version='1.0.0',created_by=1,updated_time=now,
            package_storage_key=None,manifest_hash=None)
        skill={'id':'skill-a','name':'测试技能','user_id':'1','display_status':'DRAFT','current_version_id':7,
            'current_revision':1,'state':0,'created_time':now,'updated_time':now}
        before={'keenrobot_skills':{'rows':[skill]},'keenrobot_skill_forms':{'rows':[form]},
            'keenrobot_skill_versions':{'rows':[old]},'keenrobot_source_types':{'rows':[
                {'id':i,'code':str(i),'name':str(i),'is_enabled':1} for i in range(1,5)]},
            'keenrobot_skill_debug_runs':{'rows':[{'run_id':'run-a','skill_id':'skill-a','skill_version_id':7,'user_id':'1','created_time':now}]}}
        history={'keenrobot_skills':{'rows':[{**skill,'config':{'technical_name':'original-technical-name'},'published_at':now}]},
            'keenrobot_skill_debug_runs':{'rows':[{'run_id':'run-a','id':'original-run-id','conversation_input':'历史对话',
                'request_document_count':2,'result_byte_size':4096,'error_code':'OLD_CODE','updated_time':now}]}}
        return before,history

    def test_preserves_version_id_content_inputs_and_known_history(self):
        before,history=self.fixture(); data,issues,notes,mapping=build_plan(before,history)
        self.assertEqual(issues,[]); self.assertEqual(notes,[])
        self.assertEqual(mapping['old-version'],7)
        self.assertEqual(data['keenrobot_skill_versions'][0]['id'],7)
        self.assertEqual(data['keenrobot_skill_forms'][0]['instructions'],'历史指令')
        self.assertEqual(data['keenrobot_skill_forms'][0]['technical_name'],'original-technical-name')
        self.assertEqual(data['keenrobot_skills'][0]['published_at'],history['keenrobot_skills']['rows'][0]['published_at'])
        run=data['keenrobot_skill_debug_runs'][0]
        self.assertEqual((run['id'],run['conversation_input'],run['request_document_count'],run['result_byte_size'],run['error_code']),
                         ('original-run-id','历史对话',2,4096,'OLD_CODE'))
        self.assertFalse(set(TABLES)&PROTECTED)

    def test_conflicting_history_is_not_silently_overwritten(self):
        before,history=self.fixture()
        before['keenrobot_skill_versions']['rows'][0]['instructions']='不同的历史值'
        _,issues,_,_=build_plan(before,history)
        self.assertIn('version_content_conflict',{r['kind'] for r in issues})

    def test_unknown_config_prevents_drop(self):
        before,history=self.fixture()
        history['keenrobot_skills']['rows'][0]['config']['important_unmapped_value']='不可丢失'
        _,issues,_,_=build_plan(before,history)
        self.assertIn('unmapped_config_key',{r['kind'] for r in issues})

    def test_wrong_current_version_owner_rejected(self):
        before,history=self.fixture()
        before['keenrobot_skills']['rows'][0]['current_revision']=2
        _,issues,_,_=build_plan(before,history)
        self.assertIn('invalid_current_version',{r['kind'] for r in issues})
