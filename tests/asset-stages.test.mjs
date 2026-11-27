import test from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import AssetsPage, {AssetStageOverview} from '../src/pages/AssetsPage.tsx'
import {ArchiveStageField} from '../src/components/assistant/ArtifactWorkbench.tsx'
import {getAssetOverview, listAssets, createAsset} from '../src/api/assets.ts'

const stages=['测试规划','测试设计','数据准备','测试执行','测试度量','测试支撑','测试管理']
const overview={total:12,recycle_count:0,recycle_days:30,unassigned_count:0,
  test_stages:stages.map((name,i)=>({id:i+1,name,code:String(i+1),count:i===1?12:0})),
  classes:Array.from({length:25},(_,i)=>({id:i+1,name:`大类${i}`,count:0,enabled:true}))}
const success=data=>Response.json({status:'success',data})

test('概览接口缺失阶段时明确提示，不能静默显示为只有全部资产',async()=>{
  const original=globalThis.fetch
  try {
    for(const data of [{total:37,classes:[]},{...overview,test_stages:[]}]) {
      globalThis.fetch=async()=>success(data)
      await assert.rejects(getAssetOverview(),/测试阶段暂不可用/)
    }
    globalThis.fetch=async()=>success(overview)
    assert.deepEqual((await getAssetOverview()).test_stages,overview.test_stages)
  } finally {globalThis.fetch=original}
})

test('资产概览固定展示全部资产和七阶段，多大类不增加卡片，点击阶段和全部可切换',()=>{
  const changed=[]
  const props={overview,value:2,disabled:false,onChange:value=>changed.push(value)}
  const markup=renderToStaticMarkup(React.createElement(AssetStageOverview,props))
  assert.equal((markup.match(/<button /g)||[]).length,8)
  for(const name of ['全部资产',...stages]) assert.ok(markup.includes(name))
  assert.doesNotMatch(markup,/大类0|大类24/)
  assert.equal((markup.match(/aria-pressed="true"/g)||[]).length,1)
  assert.match(markup,/>12<\/strong>/)
  const buttons=React.Children.toArray(AssetStageOverview(props).props.children)
  buttons[3].props.onClick()
  buttons[0].props.onClick()
  assert.deepEqual(changed,[3,undefined])
})

test('资产列表列名为技能大类',()=>{
  const markup=renderToStaticMarkup(React.createElement(AssetsPage))
  assert.match(markup,/<th scope="col">技能大类<\/th>/)
  assert.doesNotMatch(markup,/资产类型/)
})

test('阶段筛选以 GET 查询参数提交，保留搜索分页且回收站不继承阶段过滤',async()=>{
  const original=globalThis.fetch, urls=[]
  globalThis.fetch=async(url)=>{urls.push(new URL(url,'http://local'));return success({items:[],total:0,page:1,pages:1})}
  try {
    await listAssets({page:2,search:'用例',testStageId:3,sort:'asc',recycle:false})
    assert.equal(urls[0].pathname,'/api/assets/list')
    assert.equal(urls[0].searchParams.get('test_stage_id'),'3')
    assert.equal(urls[0].searchParams.get('skill_classes_id'),null)
    assert.equal(urls[0].searchParams.get('search'),'用例')
    assert.equal(urls[0].searchParams.get('page'),'2')
    await listAssets({page:1,search:'',classId:8,sort:'desc',recycle:false})
    assert.equal(urls[1].searchParams.get('skill_classes_id'),'8')
    await listAssets({page:1,search:'',testStageId:3,sort:'desc',recycle:true})
    assert.equal(urls[2].pathname,'/api/assets/recycle-bin')
    assert.equal(urls[2].searchParams.get('test_stage_id'),null)
  } finally {globalThis.fetch=original}
})

test('纳入产物的测试阶段由所选技能大类带出并只读展示',()=>{
  const empty=renderToStaticMarkup(React.createElement(ArchiveStageField))
  assert.match(empty,/选择技能大类后自动关联/)
  const old=renderToStaticMarkup(React.createElement(ArchiveStageField,{skillClass:{id:'7',name:'旧发布名称',test_stage_name:'测试设计'}}))
  assert.match(old,/readOnly=""/)
  assert.match(old,/value="测试设计"/)
  const published=renderToStaticMarkup(React.createElement(ArchiveStageField,{skillClass:{id:'7',name:'新发布名称',test_stage_name:'数据准备'}}))
  assert.match(published,/value="数据准备"/)
})

test('纳入资产只提交技能大类编号，测试阶段由服务端关联',async()=>{
  const original=globalThis.fetch
  globalThis.fetch=async(url,options)=>{
    assert.equal(url,'/api/assets/create');assert.equal(options.method,'POST')
    const body=JSON.parse(options.body)
    assert.equal(body.skill_classes_id,8)
    assert.equal(Object.hasOwn(body,'test_stage_id'),false)
    return success({included:true,recycled:false,asset_id:1,files:[]})
  }
  try {await createAsset({artifact_id:'test',base_hash:'a'.repeat(64),name:'产物',skill_classes_id:8,application_identify:'app'})}
  finally {globalThis.fetch=original}
})
