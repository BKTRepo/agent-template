"""开发者中心沙箱和悬浮窗共享网关配置。"""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

for key, value in {
    'AUTH_SECRET_KEY': 'isolated-chat-test-secret-' * 4,
    'DATABASE_HOST': '127.0.0.1', 'DATABASE_PORT': '3306',
    'DATABASE_USERNAME': 'test', 'DATABASE_NAME': 'test',
}.items():
    os.environ[key] = value

from applications.chat.services.execution import model_environment as chat_environment
from applications.zhaoyunlong.services.online_debug_service import OnlineDebugError, OnlineDebugService
from services.model_gateway import configured_model_registry, default_model, model_ids, model_registry

_path = Path(__file__).resolve().parents[1] / 'applications/zhaoyunlong/sandbox/online-debug-skill/run.py'
_spec = importlib.util.spec_from_file_location('sandbox_entry_for_gateway_test', _path)
_entry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_entry)


class SharedGatewayTest(unittest.TestCase):
    def resolve(self, values):
        with patch.dict(os.environ, {}, clear=True), patch('services.model_gateway.dotenv_values', return_value=values):
            return chat_environment(default_model()), OnlineDebugService._model_environment()

    def test_direct_mode_shares_address_model_and_credential(self):
        values = {'ANTHROPIC_BASE_URL': 'https://public.test', 'ANTHROPIC_API_KEY': 'public-key',
                  'ANTHROPIC_MODEL': 'deepseek-flash', 'CLAUDE_MAX_TURNS': '5'}
        chat, sandbox = self.resolve(values)
        self.assertEqual(chat, sandbox)
        self.assertEqual(sandbox['ANTHROPIC_MODEL'], 'deepseek-flash')
        self.assertEqual(sandbox['CLAUDE_MAX_TURNS'], '5')
        with patch.dict(os.environ, sandbox, clear=True):
            self.assertEqual(_entry.load_config()['model'], 'deepseek-flash')

    def test_ccr_bearer_shares_model_and_token(self):
        values = {'CHAT_GATEWAY_MODE': 'ccr', 'CHAT_CCR_BASE_URL': 'http://ccr:3456',
                  'CHAT_CCR_AUTH_MODE': 'bearer', 'CHAT_CCR_API_KEY': 'ccr-key',
                  'CHAT_MODEL_DEEPSEEK': 'bank,deepseek'}
        chat, sandbox = self.resolve(values)
        self.assertEqual(chat, sandbox)
        self.assertEqual(sandbox['ANTHROPIC_AUTH_TOKEN'], 'ccr-key')
        self.assertNotIn('ANTHROPIC_API_KEY', sandbox)
        with patch.dict(os.environ, sandbox, clear=True):
            self.assertEqual(_entry.load_config()['model'], 'bank,deepseek')

    def test_default_model_is_shared_and_ccr_never_uses_public_model(self):
        values = {'CHAT_GATEWAY_MODE': 'ccr', 'CHAT_CCR_BASE_URL': 'http://ccr:3456',
                  'CHAT_CCR_API_KEY': 'ccr-key', 'CHAT_DEFAULT_MODEL': 'glm51',
                  'CHAT_MODEL_GLM51': 'bank,glm', 'ANTHROPIC_MODEL': 'public-model'}
        chat, sandbox = self.resolve(values)
        self.assertEqual(chat['ANTHROPIC_MODEL'], 'bank,glm')
        self.assertEqual(chat, sandbox)
        del values['CHAT_MODEL_GLM51']
        with self.assertRaisesRegex(RuntimeError, '尚未配置实际 API 模型名'):
            self.resolve(values)
        with patch.dict(os.environ, {}, clear=True), patch('services.model_gateway.dotenv_values', return_value=values):
            with self.assertRaises(OnlineDebugError):
                OnlineDebugService._model_environment()

    def test_ccr_other_auth_modes_work_in_online_container(self):
        base = {'CHAT_GATEWAY_MODE': 'ccr', 'CHAT_CCR_BASE_URL': 'http://ccr:3456',
                'CHAT_CCR_API_KEY': 'ccr-key', 'CHAT_MODEL_DEEPSEEK': 'bank,deepseek'}
        for mode in ('api_key', 'none'):
            with self.subTest(mode=mode):
                chat, sandbox = self.resolve(base | {'CHAT_CCR_AUTH_MODE': mode})
                self.assertEqual(chat, sandbox)
                with patch.dict(os.environ, sandbox, clear=True):
                    self.assertEqual(_entry.load_config()['model'], 'bank,deepseek')

    def test_switching_gateway_keeps_public_and_ccr_models_separate(self):
        common = {'ANTHROPIC_BASE_URL': 'https://public.test', 'ANTHROPIC_API_KEY': 'public-key',
                  'ANTHROPIC_MODEL': 'public-model', 'CHAT_CCR_BASE_URL': 'http://ccr:3456',
                  'CHAT_CCR_API_KEY': 'ccr-key', 'CHAT_CCR_MODEL_DEEPSEEK': 'bank,deepseek'}
        direct, direct_sandbox = self.resolve(common | {'CHAT_GATEWAY_MODE': 'direct'})
        ccr, ccr_sandbox = self.resolve(common | {'CHAT_GATEWAY_MODE': 'ccr'})
        self.assertEqual(direct['ANTHROPIC_MODEL'], 'public-model')
        self.assertEqual(ccr['ANTHROPIC_MODEL'], 'bank,deepseek')
        self.assertEqual(direct, direct_sandbox)
        self.assertEqual(ccr, ccr_sandbox)

    def test_online_container_rejects_missing_credential(self):
        with patch.dict(os.environ, {'ANTHROPIC_BASE_URL': 'http://ccr:3456',
                                    'ANTHROPIC_MODEL': 'model'}, clear=True):
            with self.assertRaises(_entry.DebugExecutionError):
                _entry.load_config()

    def test_custom_registry_is_shared_and_not_limited_to_five(self):
        rows = [{'id': f'model-{i}', 'name': f'模型 {i}', 'direct_model': f'public-{i}',
                 'ccr_model': f'bank,model-{i}'} for i in range(7)]
        common = {'CHAT_MODEL_REGISTRY': json.dumps(rows), 'CHAT_DEFAULT_MODEL': 'model-6',
                  'ANTHROPIC_BASE_URL': 'https://public.test', 'ANTHROPIC_API_KEY': 'public-key',
                  'CHAT_CCR_BASE_URL': 'http://ccr:3456', 'CHAT_CCR_API_KEY': 'ccr-key'}
        with patch.dict(os.environ, {}, clear=True), patch('services.model_gateway.dotenv_values', return_value=common):
            self.assertEqual(len(model_ids()), 7)
            self.assertEqual(model_registry()[6]['name'], '模型 6')
        direct, sandbox = self.resolve(common | {'CHAT_GATEWAY_MODE': 'direct'})
        self.assertEqual(direct, sandbox)
        self.assertEqual(direct['ANTHROPIC_MODEL'], 'public-6')
        ccr, sandbox = self.resolve(common | {'CHAT_GATEWAY_MODE': 'ccr'})
        self.assertEqual(ccr, sandbox)
        self.assertEqual(ccr['ANTHROPIC_MODEL'], 'bank,model-6')

    def test_invalid_registry_and_missing_mapping_fail_closed(self):
        values = {'CHAT_MODEL_REGISTRY': '[{"id":"x"},{"id":"x"}]',
                  'ANTHROPIC_BASE_URL': 'https://public.test', 'ANTHROPIC_API_KEY': 'key'}
        with patch.dict(os.environ, {}, clear=True), patch('services.model_gateway.dotenv_values', return_value=values):
            with self.assertRaisesRegex(RuntimeError, '重复'):
                model_ids()
            values['CHAT_MODEL_REGISTRY'] = '[{"id":"x","ccr_model":"bank,x"}]'
            with self.assertRaisesRegex(RuntimeError, '尚未配置实际 API 模型名'):
                chat_environment('x')
            with self.assertRaisesRegex(RuntimeError, '不在 CHAT_MODEL_REGISTRY'):
                chat_environment('unknown')

    def test_only_models_configured_for_current_gateway_are_listed(self):
        values = {'ANTHROPIC_BASE_URL': 'https://public.test', 'ANTHROPIC_API_KEY': 'key',
                  'ANTHROPIC_MODEL': 'deepseek-flash', 'CHAT_CCR_BASE_URL': 'http://ccr:3456',
                  'CHAT_CCR_API_KEY': 'key', 'CHAT_CCR_MODEL_GLM51': 'bank,glm51-local-think'}
        with patch.dict(os.environ, {}, clear=True), patch('services.model_gateway.dotenv_values', return_value=values):
            self.assertEqual(configured_model_registry(), [{'id': 'deepseek', 'model_name': 'deepseek-flash'}])
            values['CHAT_GATEWAY_MODE'] = 'ccr'
            self.assertEqual(configured_model_registry(), [{'id': 'glm51', 'model_name': 'bank,glm51-local-think'}])
            values['CHAT_CCR_API_KEY'] = ''
            self.assertEqual(configured_model_registry(), [])


if __name__ == '__main__':
    unittest.main()
