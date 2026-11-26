import type { CatalogMetadata } from '@/api/skillCatalog'
import type { DeveloperCatalogOption } from '@/api/developerCenter'

interface Selections { testStageId: string; classId: string; maintainer: string }

/** Each menu applies the other two selections so users can change its current value. */
export function linkedCatalogOptions(metadata: CatalogMetadata | undefined, stages: DeveloperCatalogOption[], selected: Selections, enabledOnly = false) {
  const classes = (metadata?.skill_classes ?? []).filter(row => !enabledOnly || row.is_enabled)
  const relations = metadata?.filter_relations
  const matchesMaintainer = (id: string) => !selected.maintainer || !relations || relations.some(row => row.class_id === id && row.maintainer === selected.maintainer)
  const classOptions = classes.filter(row => (!selected.testStageId || String(row.test_stage_id ?? '') === selected.testStageId) && matchesMaintainer(row.id))
  const stageClasses = classes.filter(row => (!selected.classId || row.id === selected.classId) && matchesMaintainer(row.id))
  const stageIds = new Set(stageClasses.map(row => String(row.test_stage_id ?? '')))
  const maintainerClasses = new Set(classes.filter(row => (!selected.classId || row.id === selected.classId)
    && (!selected.testStageId || String(row.test_stage_id ?? '') === selected.testStageId)).map(row => row.id))
  const maintainerIds = relations && new Set(relations.filter(row => maintainerClasses.has(row.class_id)).map(row => row.maintainer))
  return {
    classes: classOptions,
    stages: !selected.classId && !selected.maintainer ? stages : stages.filter(row => stageIds.has(row.id)),
    maintainers: (metadata?.maintainers ?? []).filter(row => !maintainerIds || maintainerIds.has(row.id)),
  }
}

export function linkedMountOptions<T extends DeveloperCatalogOption>(classes: T[], stages: DeveloperCatalogOption[], selected: { classId: string; testStageId: string }) {
  const stageIds = new Set(classes.filter(row => !selected.classId || row.id === selected.classId).map(row => String(row.test_stage_id ?? '')))
  return {
    classes: classes.filter(row => !selected.testStageId || String(row.test_stage_id ?? '') === selected.testStageId),
    stages: selected.classId ? stages.filter(row => stageIds.has(row.id)) : stages,
  }
}
