"""产物路径限制在 chat_results 目录内。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

for key, value in {'AUTH_SECRET_KEY': 'isolated-chat-test-secret-' * 4,
                   'DATABASE_HOST': '127.0.0.1', 'DATABASE_PORT': '3306',
                   'DATABASE_USERNAME': 'test', 'DATABASE_NAME': 'test'}.items():
    os.environ[key] = value

from applications.chat.services.artifacts import artifact_path, artifact_root


class ArtifactPathTest(unittest.TestCase):
    def test_new_default_root_is_in_chat_directory(self):
        self.assertEqual(artifact_root(), Path(__file__).resolve().parents[1] / 'applications/chat/chat_results')

    def test_only_configured_root_is_used(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            new, old = root / 'new', root / 'old'
            old.mkdir(); new.mkdir()
            (old / 'a.xlsx').write_bytes(b'old')
            with patch('applications.chat.services.artifacts.artifact_root', return_value=new):
                self.assertEqual(artifact_path('a.xlsx'), new / 'a.xlsx')
                self.assertFalse(artifact_path('a.xlsx').exists())
                (new / 'a.xlsx').write_bytes(b'new')
                self.assertEqual(artifact_path('a.xlsx'), new / 'a.xlsx')
                with self.assertRaises(ValueError):
                    artifact_path('../outside')
