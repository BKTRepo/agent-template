import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from applications.chat.services.history_files import HistoryFileStore


class HistoryFileStoreTest(unittest.TestCase):
    def test_user_scope_append_and_concurrent_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryFileStore(directory)
            session = 'a' * 32
            store.ensure(12, session, {'title': '测试'})
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda n: store.append_many(12, session, [{'type': 'message', 'data': n}]), range(40)))
            events = store.read(12, session)
            self.assertEqual(len(events), 41)
            self.assertEqual({item['data'] for item in events[1:]}, set(range(40)))
            with self.assertRaises(FileNotFoundError):
                store.read(13, session)
            with self.assertRaises(ValueError):
                store.read(12, '../outside')

    def test_replace_and_delete_keep_other_users_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryFileStore(directory)
            first, second = 'a' * 32, 'b' * 32
            store.ensure(1, first, {'title': '一'})
            store.ensure(2, second, {'title': '二'})
            store.append_many(1, first, [{'type': 'message', 'content': '旧消息'}])
            store.replace(1, first, [{'type': 'created', 'data': {'title': '一'}}])
            self.assertEqual(len(store.read(1, first)), 1)
            self.assertEqual(store.list_ids(1), [first])
            store.delete(1, first)
            self.assertEqual(store.list_ids(1), [])
            self.assertEqual(len(store.read(2, second)), 1)

    def test_index_id_and_idempotent_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryFileStore(directory)
            session = 'a' * 32
            self.assertTrue(store.ensure(1, session, {'title': '原标题'}))
            store.append_many(1, session, [{'type': 'message', 'content': '内容'}])
            self.assertFalse(store.ensure(1, session, {'title': '不应覆盖'}))
            self.assertEqual(len(store.read(1, session)), 2)
            self.assertEqual(store.read(1, session)[0]['data']['title'], '原标题')

    def test_message_text_events_are_scoped_to_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryFileStore(directory)
            session = 'a' * 32
            store.ensure(1, session, {'generation': 1})
            store.append_many(1, session, [
                {'type': 'message_content', 'generation': 1, 'message_id': 1, 'content': '旧内容'},
                {'type': 'message_content', 'generation': 1, 'message_id': 1, 'content': '最新内容'},
                {'type': 'message_content', 'generation': 2, 'message_id': 2, 'content': '新一代'},
            ])
            self.assertEqual(store.message_contents(1, session, 1), {1: '最新内容'})
            self.assertEqual(store.message_contents(1, session, 2), {2: '新一代'})
