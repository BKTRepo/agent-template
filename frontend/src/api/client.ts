import axios from 'axios'
import { API_BASE } from '@/lib/constants'

export const apiClient = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

/**
 * 后端统一响应信封: { code, status, message, data, total }
 * - code === '000000' 视为成功, 解包 data 作为响应体
 * - 其余 code 抛出携带后端中文 message 的 Error
 * - 非信封响应（如纯文本下载）原样透传
 */
apiClient.interceptors.response.use(
  (response) => {
    const body = response.data as
      | { code?: string; message?: string; data?: unknown }
      | undefined
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === '000000') {
        response.data = body.data
      } else {
        return Promise.reject(new Error(body.message || '请求失败'))
      }
    }
    return response
  },
  (error) => Promise.reject(error),
)
