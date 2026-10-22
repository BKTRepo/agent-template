import { applications, ALL_APPLICATIONS, applicationText } from '@/lib/access'
import SearchSelect from './SearchSelect'
export default function ApplicationPicker({ value = [], onChange, disabled = false, required = false }: { value?: string[]; onChange: (ids: string[]) => void; disabled?: boolean; required?: boolean }) {
  return <div className="form-field"><span>所属应用 {required && <em>*</em>}</span>{disabled ? <div className="form-hint">{applicationText({ applicationIds: value })}</div> : <SearchSelect label="所属应用" value={value.length === 1 ? value[0] : ''} options={[{ id: ALL_APPLICATIONS, name: '全应用适用' }, ...applications]} placeholder="请选择所属应用" required={required} onChange={id => onChange(id ? [id] : [])} />}{value.length > 1 && <p className="helper-text">历史关联：{applicationText({ applicationIds: value })}。保存前请选择一个所属应用。</p>}<p className="helper-text">从全量应用目录中搜索选择，不支持填写未登记的应用。</p></div>
}
