import { useEffect, useRef } from 'react'
import { basicSetup, EditorView } from 'codemirror'
import { javascript } from '@codemirror/lang-javascript'
import { json } from '@codemirror/lang-json'
import { markdown } from '@codemirror/lang-markdown'
import { python } from '@codemirror/lang-python'
import { sql } from '@codemirror/lang-sql'
import { StreamLanguage } from '@codemirror/language'
import { shell } from '@codemirror/legacy-modes/mode/shell'

const languages = {
  js: javascript(), ts: javascript({ typescript: true }), py: python(), sh: StreamLanguage.define(shell),
  sql: sql(), json: json(), md: markdown(),
}

export default function ArtifactCodeEditor({ text, type, readOnly, onChange }: {
  text: string; type: string; readOnly: boolean; onChange: (text: string) => void
}) {
  const parent = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const latest = useRef({ text, onChange })
  latest.current = { text, onChange }

  useEffect(() => {
    const editor = new EditorView({
      doc: latest.current.text,
      parent: parent.current!,
      extensions: [basicSetup, languages[type as keyof typeof languages] || [], EditorView.editable.of(!readOnly),
        EditorView.contentAttributes.of({ 'aria-label': readOnly ? '文件文本预览' : '编辑文件文本' }),
        EditorView.updateListener.of(update => {
          if (update.docChanged && !readOnly) {
            const value = update.state.doc.toString()
            if (value !== latest.current.text.replace(/\r\n?/g, '\n')) latest.current.onChange(value)
          }
        }),
      ],
    })
    view.current = editor
    return () => { view.current = null; editor.destroy() }
  }, [type, readOnly])

  useEffect(() => {
    const editor = view.current
    const normalized = text.replace(/\r\n?/g, '\n')
    if (editor && editor.state.doc.toString() !== normalized) {
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: normalized } })
    }
  }, [text])

  return <div className="artifact-code-editor" ref={parent} />
}
