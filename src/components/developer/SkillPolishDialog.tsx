import { useEffect, useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import Dialog from './Dialog'
import { polishFields, polishKeys, requestSkillPolish, type SkillPolishText } from '@/api/skillPolish'
import './skillPolish.css'

export default function SkillPolishDialog({ original, onClose, onApply }: {
  original: SkillPolishText; onClose: () => void; onApply: (suggestion: SkillPolishText) => void
}) {
  const [suggestion, setSuggestion] = useState<SkillPolishText>()
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    // Defer dispatch until after React's development-only effect cleanup.
    const timer = window.setTimeout(() => void requestSkillPolish(original, controller.signal)
      .then(result => { if (!controller.signal.aborted) setSuggestion(result) })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message || '润色失败，请重试。') }), 0)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [original, attempt])

  const changed = suggestion ? polishKeys.filter(key => original[key].trim() && original[key] !== suggestion[key]) : []
  return <Dialog title="AI 润色建议" wide onClose={onClose} footer={<>
    <button type="button" className="button" onClick={onClose}>取消</button>
    {error && <button type="button" className="button primary" onClick={() => { setError(''); setAttempt(value => value + 1) }}>重试</button>}
    {suggestion && <button type="button" className="button primary" disabled={!changed.length} onClick={() => onApply(suggestion)}>应用建议</button>}
  </>}>
    {error ? <p className="error-banner" role="alert">{error}</p>
      : !suggestion ? <p className="skill-polish-progress" role="status"><LoaderCircle size={16} className="spin" />正在生成润色建议…</p>
      : !changed.length ? <p role="status">AI 建议保留现有表述。</p>
      : <><p className="helper-text">核对业务要求后应用建议，再按原流程保存草稿或调试。</p>
        {changed.map(key => <section className="skill-polish-field" key={key}>
          <h3>{polishFields[key]}</h3>
          <div className="skill-polish-comparison">
            <div><b>原文</b><pre>{original[key]}</pre></div>
            <div><b>建议</b><pre>{suggestion[key]}</pre></div>
          </div>
        </section>)}
      </>}
  </Dialog>
}
