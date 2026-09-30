from contextlib import contextmanager
import pytest
from applications.jiayueyang.rag import milvus_store


@pytest.mark.parametrize('always_fail', [False, True])
def test_closed_channel_uses_new_connection_and_only_one_retry(monkeypatch, always_fail):
    clients=[]
    @contextmanager
    def connection():
        client=object();clients.append(client);yield client
    def operation(client):
        if always_fail or len(clients)==1:
            raise ValueError('Cannot invoke RPC on closed channel!')
        return 'recovered'
    monkeypatch.setattr(milvus_store,'_milvus_client',connection)
    if always_fail:
        with pytest.raises(ValueError):
            milvus_store._run_milvus_read_with_retry('test',operation)
    else:
        assert milvus_store._run_milvus_read_with_retry('test',operation)=='recovered'
    assert len(clients)==2 and clients[0] is not clients[1]
