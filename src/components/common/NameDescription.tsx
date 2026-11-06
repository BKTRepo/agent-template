import type { ReactNode } from 'react'
import { descriptionLines } from '@/lib/descriptionPreview'

export function DescriptionPreview({ description }: { description?: string }) {
  return description?.trim() ? <span className="entity-description" title={description}>{descriptionLines(description).map((line, index) => <span key={index}>{line}</span>)}</span> : null
}
export default function NameDescription({ name, description, children }: { name: string; description?: string; children?: ReactNode }) {
  return <div className="name-description"><div className="entity-name">{name}{children}</div>
    <DescriptionPreview description={description} />
  </div>
}
