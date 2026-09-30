import asyncio

import pytest

from applications.jiayueyang.rag import query_rewriter as rewriter
from applications.jiayueyang.rag.llm import LLMTruncatedError
from configure import PROJECT_CONFIG


@pytest.fixture(autouse=True)
def clean_rewrite_state(monkeypatch):
    async def fresh():
        pass

    monkeypatch.setattr(rewriter, '_ensure_indices_fresh', fresh)
    monkeypatch.setattr(rewriter, '_indices', {'doc': {}})
    rewriter.clear_rewrite_cache()
    yield
    rewriter.clear_rewrite_cache()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['timeout', 'empty', 'truncated'])
async def test_failed_primary_is_retried_next_request_not_frozen_in_outer_cache(monkeypatch, failure):
    calls = []

    async def rewrite(*args):
        calls.append(args)
        if len(calls) == 1:
            if failure == 'timeout':
                raise asyncio.TimeoutError()
            if failure == 'truncated':
                raise LLMTruncatedError('test limit', partial='incomplete')
            return None
        return '完整的增量授权检索查询'

    async def translate(*args):
        return 'incremental authorization'

    monkeypatch.setattr(rewriter, '_llm_rewrite', rewrite)
    monkeypatch.setattr(rewriter, '_llm_translate_query', translate)
    first = await rewriter.rewrite_query_bilingual('追加授权')
    assert first.original_query == '追加授权'
    assert not rewriter._cache and not rewriter._bilingual_cache
    second = await rewriter.rewrite_query_bilingual('追加授权')
    assert second.primary_query.startswith('完整的增量授权检索查询')
    assert len(calls) == 2
    assert await rewriter.rewrite_query_bilingual('追加授权') == second
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['timeout', 'empty', 'truncated'])
async def test_failed_translation_retries_without_repeating_successful_primary(monkeypatch, failure):
    calls = {'primary': 0, 'english': 0}

    async def rewrite(*args):
        calls['primary'] += 1
        return '增量授权'

    async def translate(*args):
        calls['english'] += 1
        if calls['english'] == 1:
            if failure == 'timeout':
                raise asyncio.TimeoutError()
            if failure == 'truncated':
                raise LLMTruncatedError('test limit')
            return None
        return 'original transaction identifier'

    monkeypatch.setattr(rewriter, '_llm_rewrite', rewrite)
    monkeypatch.setattr(rewriter, '_llm_translate_query', translate)
    first = await rewriter.rewrite_query_bilingual('追加授权')
    # 确定性英文补词可能非空，但不能把翻译失败伪装为成功并缓存。
    assert first.english_query == 'incremental authorization'
    assert rewriter._cache and not rewriter._bilingual_cache
    second = await rewriter.rewrite_query_bilingual('追加授权')
    assert 'original transaction identifier' in second.english_query
    assert calls == {'primary': 1, 'english': 2}
    assert await rewriter.rewrite_query_bilingual('追加授权') == second
    assert calls == {'primary': 1, 'english': 2}


@pytest.mark.asyncio
async def test_valid_unchanged_query_remains_cacheable(monkeypatch):
    calls = []

    async def rewrite(query, *args):
        calls.append(query)
        return query

    monkeypatch.setattr(rewriter, '_llm_rewrite', rewrite)
    assert await rewriter.rewrite_query('Field 39 code 11') == 'Field 39 code 11'
    assert await rewriter.rewrite_query('Field 39 code 11') == 'Field 39 code 11'
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_missing_index_does_not_freeze_bilingual_result(monkeypatch):
    monkeypatch.setattr(rewriter, '_indices', {})

    async def translate(*args):
        return 'balance inquiry'

    monkeypatch.setattr(rewriter, '_llm_translate_query', translate)
    await rewriter.rewrite_query_bilingual('余额查询')
    assert not rewriter._bilingual_cache


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['primary', 'english'])
@pytest.mark.parametrize('always_truncated', [False, True])
async def test_truncation_retry_is_bounded_and_reuses_same_prompt(monkeypatch, stage, always_truncated):
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        if always_truncated or len(calls) == 1:
            raise LLMTruncatedError('test limit', partial='unfinished')
        return 'Field 39 Response Code 11'

    monkeypatch.setattr('applications.jiayueyang.rag.llm.chat_completion', completion)
    monkeypatch.setattr(PROJECT_CONFIG, 'QUERY_REWRITE_MAX_TOKENS', 512)
    monkeypatch.setattr(PROJECT_CONFIG, 'QUERY_TRANSLATE_MAX_TOKENS', 512)
    monkeypatch.setattr(PROJECT_CONFIG, 'QUERY_REWRITE_RETRY_MAX_TOKENS', 1024)
    monkeypatch.setattr(PROJECT_CONFIG, 'QUERY_REWRITE_TRUNCATION_RETRY_ENABLED', True)
    operation = rewriter._llm_rewrite('39域返回11', 'Field 39', 'unchanged terms') if stage == 'primary' else rewriter._llm_translate_query('39域返回11')
    if always_truncated:
        with pytest.raises(LLMTruncatedError):
            await operation
    else:
        assert await operation == 'Field 39 Response Code 11'
    assert [call['max_tokens'] for call in calls] == [512, 1024]
    assert calls[0]['messages'] == calls[1]['messages']
    assert calls[0]['temperature'] == calls[1]['temperature'] == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [asyncio.TimeoutError, RuntimeError])
async def test_non_truncation_failure_does_not_add_retry(monkeypatch, failure):
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        raise failure('test failure')

    monkeypatch.setattr('applications.jiayueyang.rag.llm.chat_completion', completion)
    with pytest.raises(failure):
        await rewriter._llm_translate_query('question')
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled,ceiling', [(False, 1024), (True, 512)])
async def test_disabled_or_non_expanding_retry_makes_one_call(monkeypatch, enabled, ceiling):
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        raise LLMTruncatedError('test limit')

    monkeypatch.setattr('applications.jiayueyang.rag.llm.chat_completion', completion)
    monkeypatch.setattr(PROJECT_CONFIG, 'QUERY_TRANSLATE_MAX_TOKENS', 512)
    monkeypatch.setattr(PROJECT_CONFIG, 'QUERY_REWRITE_RETRY_MAX_TOKENS', ceiling)
    monkeypatch.setattr(PROJECT_CONFIG, 'QUERY_REWRITE_TRUNCATION_RETRY_ENABLED', enabled)
    with pytest.raises(LLMTruncatedError):
        await rewriter._llm_translate_query('question')
    assert len(calls) == 1
