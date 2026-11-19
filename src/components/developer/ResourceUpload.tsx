import { useId, useRef, useState, type ChangeEvent } from 'react'
import { Paperclip } from 'lucide-react'
import type { UploadedResource } from '@/types/developer'
import { skillResourceExtensions, skillResourceLimits } from '@/lib/skillForm'
import type { ResourceCategory, ResourceCategoryOption } from '@/types/developer'
import type { ResourceFileLimits } from '@/lib/skillForm'

export default function ResourceUpload({ items, activeIds, disabled, error, onAdd, onRemove, onCategory, label = '资源上传', extensions = skillResourceExtensions, hint = '拖拽或点击上传脚本、文档、图片等', limits = skillResourceLimits, required = false, categories = [] }: { categories?: ResourceCategoryOption[]; items: UploadedResource[]; activeIds: string[]; disabled: boolean; error?: string; onAdd: (files: File[]) => void; onRemove: (id: string) => void; onCategory?: (id: string, category: ResourceCategory | undefined) => void; label?: string; extensions?: string[]; hint?: string; limits?: ResourceFileLimits; required?: boolean }) {
  const labelId = useId()
  const folderInput = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function selectFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? [])
    event.currentTarget.value = ''
    if (files.length) onAdd(files)
  }

  return <section className="form-field resource-upload" aria-labelledby={labelId} tabIndex={-1}><span id={labelId}>{label}{required && <em> *</em>}</span>{onCategory && <small className="resource-category-hint">上传后请为每个文件选择用途分类</small>}
    <label className={`resource-dropzone ${dragging ? 'dragging' : ''} ${disabled ? 'disabled' : ''}`} onDragOver={event => { event.preventDefault(); if (!disabled) setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (!disabled) onAdd(Array.from(event.dataTransfer.files)) }}>
      <input className="resource-file-input" type="file" accept={extensions.join(',')} multiple disabled={disabled} aria-label={`上传${label}文件`} onChange={selectFiles} />
      <span>{hint}</span><span>支持 {extensions.join(' / ')}</span><small>支持多文件{limits.maxFileBytes !== undefined && `，单个不超过 ${limits.maxFileBytes / 1024 / 1024} MB`}{limits.maxFiles !== undefined && `，最多 ${limits.maxFiles} 个`}{limits.maxTotalBytes !== undefined && `，总大小不超过 ${limits.maxTotalBytes / 1024 / 1024} MB`}</small>
    </label>
    <input ref={folderInput} type="file" multiple {...{ webkitdirectory: '' }} hidden disabled={disabled} onChange={selectFiles} />
    <button type="button" className="button small" disabled={disabled} onClick={() => folderInput.current?.click()}>选择文件夹</button>
    {items.map(item => {
      const available = categories.some(category => category.name === item.category)
      const invalid = !!error && (!item.category || !available)
      return <div className="resource-row" key={item.id}>
        <Paperclip size={16} />
        <div className="uploaded-name"><b>{item.relativePath || item.name}</b><small>{(item.size / 1024).toFixed(1)} KB{!activeIds.includes(item.id) && ' · 请重新选择文件'}</small></div>
        {onCategory && <select aria-label={`${item.name} 的资源用途分类`} value={item.category ?? ''}
          aria-invalid={invalid} aria-describedby={invalid ? `${labelId}-error` : undefined}
          disabled={disabled || !categories.length} onChange={event => onCategory(item.id, event.target.value || undefined)}>
          <option value="">请选择分类（必选）</option>
          {item.category && !available && <option value={item.category} disabled>{item.category}（已停用）</option>}
          {categories.map(category => <option key={category.id} value={category.name}>{category.name}</option>)}
        </select>}
        <button type="button" className="button small" aria-label={`移除 ${item.name}`} disabled={disabled} onClick={() => onRemove(item.id)}>移除</button>
      </div>
    })}
    {onCategory && !categories.length && <p className="helper-text">暂无启用的资源用途分类，请联系管理员配置。</p>}
    {error && <p id={`${labelId}-error`} className="platform-field-error" role="alert">{error}</p>}
    {items.some(item => !activeIds.includes(item.id)) && <p className="helper-text">请重新选择缺失的文件，或将其移除。</p>}
  </section>
}
