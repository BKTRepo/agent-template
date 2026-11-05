"""Per-request evidence of executed query stages, never inferred from route names."""
from contextvars import ContextVar
from time import monotonic
from functools import wraps
stages = ContextVar('query_stages', default=None)

def observed(name, function):
    @wraps(function)
    async def call(*args, **kwargs):
        started = monotonic()
        record = dict(stage=name, status='running')
        trace = stages.get()
        if trace is not None:
            trace.append(record)
        try:
            result = await function(*args, **kwargs)
            record['status'] = 'success'
            if isinstance(result, list):
                record['count'] = len(result)
                if name == 'rerank' and result:
                    record['status'] = 'success' if any('rerank_score' in c for c in result) else 'fallback'
            return result
        except BaseException as exc:
            record.update(status='failed', error_type=type(exc).__name__)
            raise
        finally:
            record['duration_ms'] = round((monotonic()-started)*1000)
    return call
