import test from 'node:test'
import assert from 'node:assert/strict'
import {currentUser} from '../src/api/auth.ts'
import {useAuthStore} from '../src/stores/authStore.ts'

test('登录验证服务不可用时保留刚登录的会话，允许重试', async () => {
  const original = globalThis.fetch
  const session = {token:'test-only-token',username:'test',alias:'测试用户'}
  useAuthStore.getState().setSession(session)
  globalThis.fetch = async () => Response.json({status:'failure',code:'500500',message:'登录验证服务暂不可用，请稍后重试。'}, {status:503})
  try {
    await assert.rejects(currentUser(), /登录验证服务暂不可用/)
    assert.deepEqual(useAuthStore.getState().session, session)
  } finally {
    globalThis.fetch = original
    useAuthStore.getState().setSession(null)
  }
})
