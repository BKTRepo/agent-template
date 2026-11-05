"""MCP hybrid retrieval, scope enforcement and filtered fallback regressions."""
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from applications.wrq import knowledge
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.models.knowledge_execution_model import KnowledgeToolCall
from applications.knowledge_base.rag import milvus_store as store


def context():
    return SimpleNamespace(run_id='hybrid-test', owner_id=1, scope=[{
        'knowledge_base_id':'1', 'document_id':1, 'filename':'rules.md',
        'jobs':['allowed'], 'chunk_ids':['allowed-chunk-0001']}])


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['hit', 'empty', 'foreign', 'revoked'])
async def test_mcp_hybrid_response_and_authorization(database, monkeypatch, mode):
    authorized=AsyncMock(return_value=context())
    if mode=='revoked':
        authorized.side_effect=[context(), DeveloperError('scope changed',409)]
    monkeypatch.setattr(knowledge,'authorized_execution',authorized)
    monkeypatch.setattr(knowledge,'embed_texts',AsyncMock(return_value=[[1,0,0]]))
    received=[]
    def hybrid(vectors, query, **kwargs):
        received.append((vectors,query,kwargs))
        if mode=='empty':return []
        return [{'id':'foreign' if mode=='foreign' else 'allowed-chunk-0001',
                 'doc_id':'allowed','content':'退款代码 ASTER-7421'}]
    monkeypatch.setattr(knowledge,'hybrid_query_chunks',hybrid)
    if mode in ('foreign','revoked'):
        with pytest.raises(DeveloperError):await knowledge.search('run-token','退款代码',3)
        call=await KnowledgeToolCall.get(run_id='hybrid-test')
        assert call.status=='failed' and call.matches==[]
    else:
        result=await knowledge.search('run-token','退款代码',3)
        assert result['status']=='ok'
        assert len(result['matches'])==(0 if mode=='empty' else 1)
        if result['matches']:
            assert result['matches'][0]==dict(knowledge_base_id='1',document_id=1,
                chunk_id='allowed-chunk-0001',filename='rules.md',text='退款代码 ASTER-7421')
        assert (await KnowledgeToolCall.get(id=result['search_id'])).status=='success'
    assert received==[([[1,0,0]],'退款代码',{'top_k':3,'filter_expr':'doc_id in ["allowed"]'})]
    assert authorized.await_count==2


@pytest.mark.parametrize('fallback', [False,True])
def test_all_hybrid_branches_and_fallback_keep_scope(monkeypatch,fallback):
    expression='doc_id in ["allowed"]'
    observed={}
    class Client:
        def query(self,**kwargs):return [{'id':'probe'}]
        def hybrid_search(self,**kwargs):
            observed['hybrid']=kwargs
            if fallback:raise RuntimeError('explicit hybrid failure')
            return [[{'id':'allowed-chunk-0001','entity':{'doc_id':'allowed','content':'rule'}}]]
    client=Client()
    monkeypatch.setattr(store,'_ensure_collection',lambda _:None)
    monkeypatch.setattr(store,'_run_milvus_read_with_retry',lambda name,operation:operation(client))
    def dense(actual_client,vectors,top_k,filter_expr=''):
        observed['fallback']=(actual_client,vectors,top_k,filter_expr)
        return [{'id':'allowed-chunk-0001','doc_id':'allowed','content':'rule'}]
    monkeypatch.setattr(store,'_search_chunks',dense)
    result=store.hybrid_query_chunks([[1,0,0]],'退款','refund',top_k=3,filter_expr=expression)
    assert len(result)==1
    requests=observed['hybrid']['reqs']
    assert len(requests)==3
    assert all(request.expr==expression for request in requests)
    assert observed['hybrid']['limit']==3
    if fallback:
        assert observed['fallback']==(client,[[1,0,0]],3,expression)
        assert result[0]['source']=='milvus_dense_fallback'
    else:
        assert 'fallback' not in observed
        assert result[0]['source']=='milvus_hybrid'


@pytest.mark.skipif(not os.getenv('LIVE_MILVUS_URI'),reason='explicit live Milvus opt-in required')
def test_real_milvus_hybrid_excludes_private_documents(monkeypatch):
    from configure import PROJECT_CONFIG
    from pymilvus import MilvusClient
    name='mcp_hybrid_test_'+uuid.uuid4().hex
    monkeypatch.setattr(PROJECT_CONFIG,'MILVUS_URI',os.environ['LIVE_MILVUS_URI'])
    monkeypatch.setattr(PROJECT_CONFIG,'EMBEDDING_DIM',3)
    monkeypatch.setattr(store,'_COLLECTION_NAME',name)
    monkeypatch.setattr(store,'_collection_ready',False)
    client=MilvusClient(uri=os.environ['LIVE_MILVUS_URI'])
    try:
        for job,content,vector in [('allowed','退款 ASTERCODE7421',[1,0,0]),
                                   ('other','私有退款 ASTERCODE7421',[1,0,0])]:
            store.upsert_chunks([{'order':1,'content':content,'vector':vector,'tokens':5}],file_path=job+'.md',doc_id=job)
        client.flush(collection_name=name)
        result=store.hybrid_query_chunks([[1,0,0]],'退款 ASTERCODE7421',top_k=5,filter_expr='doc_id in ["allowed"]')
        assert result and all(x['source']=='milvus_hybrid' for x in result)
        assert {x['doc_id'] for x in result}=={'allowed'}
        assert 'ASTERCODE7421' in result[0]['content']
    finally:
        if client.has_collection(collection_name=name):client.drop_collection(collection_name=name)
        client.close()
