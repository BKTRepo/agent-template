export interface ArtifactRevision {
  artifactId: string
  baseHash: string
}

export interface ArtifactFile extends ArtifactRevision {
  name: string
  fileType: string
}

export interface TestCase {
  id: string
  group: string
  name: string
  preconditions: string
  steps: { id: string; action: string; expected?: string }[]
  expected?: string
}

export interface TestCaseArtifact extends ArtifactFile {
  groupingError?: string
  editor: 'cases'
  cases: TestCase[]
  groups: { title: string; caseIds: string[] }[]
}

export interface WordParagraph {
  type: 'paragraph'
  id: string
  text: string
  heading: number
  editable: boolean
  runs: { text: string; bold: boolean; italic: boolean; underline: boolean }[]
}
export type WordBlock = WordParagraph | { type: 'table'; rows: WordBlock[][][] }
export interface WordArtifact extends ArtifactFile { editor: 'word'; blocks: WordBlock[] }
export interface SheetInfo { index: number; name: string; rows: number; columns: number }
export interface SheetArtifact extends ArtifactFile { editor: 'sheet'; sheets: SheetInfo[] }
export interface TextArtifact extends ArtifactFile { editor: 'text'; text: string; encoding: string }
export type OrdinaryArtifact = WordArtifact | SheetArtifact | TextArtifact
export interface DownloadArtifact extends ArtifactFile { editor: 'download' }
export type AssistantArtifact = TestCaseArtifact | OrdinaryArtifact | DownloadArtifact

export type CellValue = string | number | boolean | null
export type EditableCellType = 'text' | 'number' | 'boolean' | 'formula' | 'blank'
export interface CellEdit { sheet_index: number; address: string; type: EditableCellType; value: CellValue }
export interface SheetCell {
  address: string
  type: EditableCellType | 'read_only'
  value: CellValue
  editable: boolean
  bold: boolean
}
export interface SheetPage { offset: number; column_offset: number; rows: SheetCell[][]; columns: string[] }
export type FileChanges = { text: string } | { paragraphs: { id: string; text: string }[] } | { cells: CellEdit[] }
