import { apiClient } from './client'
import type { ModelsResponse } from '@/types/api'

export async function getModels(): Promise<ModelsResponse> {
  const { data } = await apiClient.get<ModelsResponse>('/models')
  return data
}
