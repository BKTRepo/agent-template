from applications.wrq.database import wrq_connections


def test_own_pool_preserves_shared_configuration_and_tls():
    shared = {'default': {'engine': 'tortoise.backends.mysql', 'credentials': {
        'minsize': 10, 'maxsize': 40, 'ssl': {'verify_mode': True}, 'pool_recycle': 120}}}
    own = wrq_connections(shared)
    assert own['default']['credentials']['minsize'] == 1
    assert own['default']['credentials']['maxsize'] == 4
    assert own['default']['credentials']['ssl'] == {'verify_mode': True}
    assert shared['default']['credentials']['minsize'] == 10
    assert shared['default']['credentials']['maxsize'] == 40
