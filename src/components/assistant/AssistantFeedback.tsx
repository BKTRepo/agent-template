import { useState } from 'react'
import Dialog from '@/components/developer/Dialog'

const reasons = ['答非所问', '事实不准', '缺少关键约束', '格式不符合规范', '太啰嗦', '其他']
export default function AssistantFeedback({ onSave, onClose }: { onSave: (reason: string) => Promise<void>; onClose: () => void }) {
  const [reason, setReason] = useState(''), [note, setNote] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const feedbackReason = reason === '其他' ? note.trim() : note.trim() ? `${reason}：${note.trim()}` : reason
  return <Dialog className="assistant-owned-dialog" title="反馈原因" busy={busy} onClose={onClose} footer={<>
    <button className="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy || !reason || !feedbackReason} onClick={() => {
      setBusy(true); void onSave(feedbackReason).then(onClose).catch(value => setError((value as Error).message)).finally(() => setBusy(false))
    }}>提交反馈</button></>}><div className="aip-feedback-form"><div className="aip-feedback-options" role="radiogroup" aria-label="选择反馈原因">{reasons.map(item => <label key={item} className="aip-feedback-option"><input type="radio" name="feedback-reason" checked={reason === item} onChange={() => setReason(item)} /><span>{item}</span></label>)}</div>
      <label className="aip-feedback-note"><span>{reason === '其他' ? '请说明原因' : '补充说明'}</span><textarea aria-label="点踩原因" value={note} maxLength={2000} onChange={event => setNote(event.target.value)} /></label></div>{error && <p role="alert">{error}</p>}</Dialog>
}
