"""悬浮窗直连及 CCR 模式的配置与健康检测契约。"""
import os
import unittest
from unittest.mock import patch

for key, value in {
    'AUTH_SECRET_KEY': 'isolated-chat-test-secret-' * 4,
    'DATABASE_HOST': '127.0.0.1', 'DATABASE_PORT': '3306',
    'DATABASE_USERNAME': 'test', 'DATABASE_NAME': 'test',
}.items():
    os.environ[key] = value

import httpx
from applications.chat.services.execution import model_environment
from applications.chat.services.model_health import _identity, probe


class GatewayConfigurationTest(unittest.IsolatedAsyncioTestCase):
    def environment(self, values, model='deepseek'):
        with patch.dict(os.environ, {}, clear=True), \
             patch('services.model_gateway.dotenv_values', return_value=values):
            return model_environment(model)

    def test_direct_mode_keeps_existing_configuration(self):
        result = self.environment({'ANTHROPIC_BASE_URL': 'https://direct.test',
                                   'ANTHROPIC_API_KEY': 'direct-key', 'ANTHROPIC_MODEL': 'deepseek-flash'})
        self.assertEqual(result['ANTHROPIC_BASE_URL'], 'https://direct.test')
        self.assertEqual(result['ANTHROPIC_API_KEY'], 'direct-key')
        self.assertEqual(result['ANTHROPIC_MODEL'], 'deepseek-flash')
        self.assertNotIn('ANTHROPIC_AUTH_TOKEN', result)

    def test_ccr_uses_independent_address_token_and_model(self):
        result = self.environment({'CHAT_GATEWAY_MODE': 'ccr', 'CHAT_CCR_BASE_URL': 'http://ccr.internal:3456',
                                   'CHAT_CCR_API_KEY': 'ccr-key', 'CHAT_MODEL_DEEPSEEK': 'bank,model',
                                   'ANTHROPIC_BASE_URL': 'https://direct.test', 'ANTHROPIC_API_KEY': 'old-key'})
        self.assertEqual(result['ANTHROPIC_BASE_URL'], 'http://ccr.internal:3456')
        self.assertEqual(result['ANTHROPIC_AUTH_TOKEN'], 'ccr-key')
        self.assertNotIn('ANTHROPIC_API_KEY', result)
        self.assertEqual(result['ANTHROPIC_MODEL'], 'bank,model')
        self.assertEqual(result['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'bank,model')

    def test_ccr_x_api_key_and_no_auth_modes(self):
        values = {'CHAT_GATEWAY_MODE': 'ccr', 'CHAT_CCR_BASE_URL': 'http://ccr:3456',
                  'CHAT_CCR_API_KEY': 'ccr-key', 'CHAT_MODEL_GLM51': 'glm51-local-think'}
        result = self.environment(values | {'CHAT_CCR_AUTH_MODE': 'api_key'}, 'glm51')
        self.assertEqual(result['ANTHROPIC_API_KEY'], 'ccr-key')
        self.assertNotIn('ANTHROPIC_AUTH_TOKEN', result)
        result = self.environment(values | {'CHAT_CCR_AUTH_MODE': 'none', 'CHAT_CCR_API_KEY': ''}, 'glm51')
        self.assertEqual(result['ANTHROPIC_AUTH_TOKEN'], 'ccr-no-auth')

    def test_ccr_requires_explicit_settings_and_never_reuses_direct_model(self):
        values = {'CHAT_GATEWAY_MODE': 'ccr', 'ANTHROPIC_MODEL': 'public-model', 'CHAT_CCR_API_KEY': 'x'}
        with self.assertRaisesRegex(RuntimeError, 'CHAT_CCR_BASE_URL'):
            self.environment(values)
        with self.assertRaisesRegex(RuntimeError, '尚未配置实际 API 模型名'):
            self.environment(values | {'CHAT_CCR_BASE_URL': 'http://ccr:3456'})
        with self.assertRaisesRegex(RuntimeError, 'CHAT_CCR_API_KEY'):
            self.environment({'CHAT_GATEWAY_MODE': 'ccr', 'CHAT_CCR_BASE_URL': 'http://ccr:3456',
                              'CHAT_MODEL_DEEPSEEK': 'model'})
        with self.assertRaisesRegex(RuntimeError, 'CHAT_CCR_AUTH_MODE'):
            self.environment(values | {'CHAT_CCR_BASE_URL': 'http://ccr:3456', 'CHAT_CCR_AUTH_MODE': 'invalid'})

    async def test_health_probe_uses_ccr_bearer_and_anthropic_format(self):
        result = self.environment({'CHAT_GATEWAY_MODE': 'ccr', 'CHAT_CCR_BASE_URL': 'http://ccr:3456',
                                   'CHAT_CCR_API_KEY': 'ccr-key', 'CHAT_MODEL_DEEPSEEK': 'bank,model'})
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={'content': []})
        original_client = httpx.AsyncClient
        with patch('applications.chat.services.model_health.httpx.AsyncClient',
                   side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs)):
            sample = await probe('deepseek', result)
        self.assertEqual(sample['status'], 'healthy')
        self.assertEqual(str(requests[0].url), 'http://ccr:3456/v1/messages')
        self.assertEqual(requests[0].headers['authorization'], 'Bearer ccr-key')
        self.assertNotIn('x-api-key', requests[0].headers)
        self.assertNotIn('ccr-key', _identity('deepseek', result))

    async def test_health_probe_uses_x_api_key_when_configured(self):
        result = self.environment({'CHAT_GATEWAY_MODE': 'ccr', 'CHAT_CCR_BASE_URL': 'http://ccr:3456',
            'CHAT_CCR_AUTH_MODE': 'api_key', 'CHAT_CCR_API_KEY': 'ccr-key', 'CHAT_MODEL_DEEPSEEK': 'bank,model'})
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={'content': []})
        original_client = httpx.AsyncClient
        with patch('applications.chat.services.model_health.httpx.AsyncClient',
                   side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs)):
            sample = await probe('deepseek', result)
        self.assertEqual(sample['status'], 'healthy')
        self.assertEqual(requests[0].headers['x-api-key'], 'ccr-key')
        self.assertNotIn('authorization', requests[0].headers)


if __name__ == '__main__':
    unittest.main()
