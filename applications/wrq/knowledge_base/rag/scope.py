"""Every query executes inside an explicit document scope, including empty scope."""
from contextvars import ContextVar
from contextlib import contextmanager
current_scope = ContextVar('knowledge_query_scope', default=frozenset())
model_connection = ContextVar('knowledge_query_model_connection', default={})

@contextmanager
def query_scope(job_ids):
    token = current_scope.set(frozenset(map(str, job_ids)))
    try:
        yield
    finally:
        current_scope.reset(token)
