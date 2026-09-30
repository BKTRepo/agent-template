import pytest
from applications.jiayueyang.rag.query import QueryParam, _generate_answer_reusing_evidence
from applications.jiayueyang.rag.llm import LLMTruncatedError
from configure import PROJECT_CONFIG


@pytest.mark.asyncio
@pytest.mark.parametrize('second_truncated',[False,True])
async def test_final_answer_retry_keeps_identical_evidence_and_is_bounded(monkeypatch,second_truncated):
    calls=[]
    async def generate(**kwargs):
        calls.append(kwargs)
        if len(calls)==1 or second_truncated:
            raise LLMTruncatedError('test limit',partial='已生成的部分答案')
        return '精简后的完整答案'
    monkeypatch.setattr('applications.jiayueyang.rag.query.chat_completion',generate)
    monkeypatch.setattr(PROJECT_CONFIG,'ANSWER_TRUNCATION_RETRY_ENABLED',True)
    monkeypatch.setattr(PROJECT_CONFIG,'ANSWER_PARTIAL_FALLBACK_ENABLED',True)
    raw={'chunks':[{'id':'fixed-evidence','content':'same original evidence'}]}
    prompt='Evidence: fixed-evidence / same original evidence'
    result=await _generate_answer_reusing_evidence('test question',QueryParam(stream=False),prompt,raw)
    assert len(calls)==2
    assert calls[0]['messages']==calls[1]['messages']
    assert calls[1]['system_prompt'].startswith(calls[0]['system_prompt'])
    assert raw['chunks']==[{'id':'fixed-evidence','content':'same original evidence'}]
    if second_truncated:
        assert '已生成的部分答案' in result and '长度上限' in result
        assert raw['metadata']['answer_fallback']=='partial'
    else:
        assert result=='精简后的完整答案'
