export type ImplementationStatus = '草稿' | '已生成' | '调试中' | '调试成功' | '调试失败' | '已上线' | '已下线'
export type DebugStatus = 'idle' | 'queued' | 'running' | 'passed' | 'failed' | 'timeout'
export interface RealtimeDocument {
  filename: string
  format?: string
  size_bytes?: number
  test_case_count?: number
  download_url: string
  expires_at?: string | null
}
export interface RealtimeTask {
  run_id: string
  skill_id: string
  debugger?: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  started_at: string | null
  finished_at: string | null
  error_message: string | null
  documents: RealtimeDocument[]
}
export interface DebugArtifact { key: string; name: string; count?: number; size?: number; format?: 'Markdown' | 'Excel' }
export interface ImplementationForm {
  revision?: number
  skillVersionId?: number
  classId: string
  name: string
  technicalName: string
  system: string
  team: string
  applicationIds?: string[]
  version: string
  modelTier: string
  description: string
  instructions: string
  skillMarkdown?: string
  compatibility?: string
  resourceIds: string[]
  resourceUsage?: string
  knowledgeBases?: KnowledgeSelection[]
  uploadedResources?: UploadedResource[]
}
export interface Implementation extends ImplementationForm {
  creatorId?: string
  creatorName?: string
  id: string
  status: ImplementationStatus
  updatedAt: string
  pendingChanges?: ImplementationForm
  pendingChangedAt?: string
  buildId?: string
  backendSkillId?: string
  backendAccount?: string
  backendVersion?: string
  buildOrigin?: 'backend' | 'mock'
  build?: SkillBuild
  debug?: { id: string; buildId: string; skillVersionId?: number; input: string | DebugInput; conversationInput?: string; requestDocumentCount?: number; status: DebugStatus; output: string; origin?: 'mock' | 'backend'; runId?: string; versionRegistered?: boolean; isCurrentVersion?: boolean; registrationError?: string; monitorError?: string; documentError?: string; documents?: RealtimeDocument[]; artifact?: DebugArtifact; artifacts?: DebugArtifact[] }
  publication?: { origin: 'mock' | 'backend'; buildId: string; publishedAt: string; publisher: string }
}
export interface PublishReply {
  implementationId: string
  buildId: string
  debugId: string
  publication: NonNullable<Implementation['publication']>
}
export interface SkillBuild {
  skill_version_id?: number; current_revision?: number
  build_id: string; skill_id: string; name: string; version: string
  files: { path: string; size: number; sha256: string; role: string }[]
  source: { display_name?: string; version?: string; knowledge_base_ids?: string[]; compatibility?: string; description?: string; instructions?: string; resource_usage?: string }
}
export interface SkillUpload { id: string; file: File; usage: string }
export interface SkillUploads { references: SkillUpload[]; scripts: SkillUpload[] }
export interface KnowledgeSelection { id: string; name: string; source: 'backend' | 'mock' }
export interface KnowledgeBaseOption extends KnowledgeSelection { description: string; scope: string }
export type ResourceCategory = '参考资料' | '模板' | '静态资源' | '脚本'
export interface UploadedResource { sourceId?: number; fileId?: number; sourceVersionId?: number; downloadUrl?: string; savedCategory?: ResourceCategory; id: string; name: string; size: number; lastModified: number; category?: ResourceCategory }
export interface DebugInput { conversation: string; documentText: string; documents: UploadedResource[] }
export interface KnowledgeFile extends UploadedResource { sampleContent?: string }
export interface KnowledgeBase {
  id: string; name: string; version: string; description: string; tag: string
  team: string; scope: 'public' | 'team'; vectorized: boolean; model: string
  files: KnowledgeFile[]; updatedAt: string
  applicationIds?: string[]
  creatorSquadId?: string
  creatorId?: string
  creatorName?: string
  processedFileIds?: string[]
  maintainer?: string
  processingStatus?: '知识处理中' | '知识处理完成' | '知识处理失败'
  processingJobId?: string
  processingOutcome?: 'success' | 'failure'
  history?: { id: string; version: string; summary: string; maintainer: string; updatedAt: string }[]
}
export interface Resource {
  id: string
  name: string
  kind: 'knowledge' | 'file'
  team: string
  scope: 'public' | 'team'
  meta: string
}
export interface SkillClass {
  id: string
  name: string
  sample: Record<string, unknown>
  requiredInput: string
  description?: string
  inputSchema?: string
  outputSchema?: string
  enabled?: boolean
}
