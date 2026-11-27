"""Run isolated asset/auth regressions without a business database or Redis."""
import os
from pathlib import Path
import secrets
import sys
import unittest

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)
for key, value in {
    'AUTH_SECRET_KEY': secrets.token_hex(32), 'DATABASE_USERNAME': 'image_qa',
    'DATABASE_HOST': '127.0.0.1', 'DATABASE_PORT': '3306', 'DATABASE_NAME': 'image_qa',
    'DATABASE_AUTO_MIGRATION': 'false', 'REDIS_HOST': '127.0.0.1', 'REDIS_PORT': '6379',
}.items():
    os.environ.setdefault(key, value)
suite = unittest.TestSuite(unittest.defaultTestLoader.discover('tests', pattern=name)
                           for name in ('test_asset_stages.py', 'test_auth_middleware.py'))
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
