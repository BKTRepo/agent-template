import { useState } from 'react'
import { openArtifactDemo } from '@/api/assistantArtifacts'
import ArtifactWorkbench from './ArtifactWorkbench'

const kinds = [['test_cases','测试案例导图'],['docx','测试报告 DOCX'],['xlsx','测试数据 XLSX'],['py','Python 脚本'],['js','JavaScript 脚本'],['ts','TypeScript 脚本'],['sh','Shell 脚本'],['sql','SQL 脚本'],['md','Markdown 文档'],['json','JSON 数据']]
export default function ArtifactDemo() {
  const [kind,setKind] = useState('test_cases'), [id,setId] = useState(''), [error,setError] = useState(''), [busy,setBusy] = useState(false)
  async function open() { setBusy(true);setError('');try {setId((await openArtifactDemo(kind)).artifactId)} catch(reason){setError((reason as Error).message)} finally {setBusy(false)} }
  return <><div className="assistant-artifact-entry"><select aria-label="产出物样例类型" value={kind} disabled={busy} onChange={event=>setKind(event.target.value)}>{kinds.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select><button className="button small" disabled={busy} onClick={()=>void open()}>打开产出物样例</button>{error&&<span role="alert">{error}</span>}</div>{id&&<ArtifactWorkbench key={id} artifactId={id} onClose={()=>setId('')} />}</>
}
