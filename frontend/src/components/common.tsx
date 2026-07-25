import type { Risk } from '../types'
import type { Role } from '../context/RoleContext'
import { CheckCircleTwoTone, ExclamationCircleTwoTone, CloseCircleTwoTone } from '@ant-design/icons'

export const sev2Icon: Record<string, any> = {
  high: <CloseCircleTwoTone twoToneColor="#cf1322" />,
  mid: <ExclamationCircleTwoTone twoToneColor="#d48806" />,
  low: <CheckCircleTwoTone twoToneColor="#389e0d" />
}

export const overallColor = (level?: string) =>
  (level||'').startsWith('阻断') ? 'error' : (level||'').startsWith('需重点') ? 'warning' : 'success'

export const riskTableCols = [
  { title: '条款', dataIndex: 'clause_id', width: 70,
    render: (v:string, r:Risk) => <span style={{fontWeight:600}}>{v} <span style={{fontSize:11,color:'#999'}}>·{r.source_ref || `p${r.page}`}</span></span> },
  { title: '风险等级', width: 165, render: (_:any, r:Risk) =>
    <span style={{color: sevColorOf(r),lineHeight:1.5}}>{sev2Icon[r.severity]} {r.level}</span> },
  { title: '违反底限条款', dataIndex: 'rule_id', width: 240, render: (v:string, r:Risk) => <>
    <span style={{fontWeight:600}}>{v}</span><br/><span style={{fontSize:12,color:'#888'}}>{r.rule_baseline}</span></> },
  { title: '风险证据', dataIndex: 'evidence', width: 320, render: (v:string)=> <span className="risk-cell-text">{v || '—'}</span> },
  { title: '数值依据', dataIndex: 'numeric_note', width: 190, render:(v:string)=>
    v ? <span className="risk-cell-text" style={{color:'#722ed1'}}>{v}</span> : <span style={{color:'#ccc'}}>—</span> },
  { title: '规则裁决', width: 220, render:(_:any,r:Risk)=> <span className="risk-cell-text">{r.decision === 'requires_approval' ? `需 ${r.approval_required?.toUpperCase()} 审批` : r.decision === 'needs_human_confirmation' ? '待补材料/人工确认' : '已确认风险'}{r.facts && Object.keys(r.facts).length ? `；事实：${Object.entries(r.facts).filter(([,value])=>value!==null&&value!==undefined&&value!=='').map(([key,value])=>`${key}=${value}`).join('，')}` : ''}</span> },
  { title: '修改建议', dataIndex: 'suggestion', width: 380, render:(v:string)=> <span className="risk-cell-text">{v || '—'}</span> }
]

const sevColorOf = (r: Risk) => r.severity==='high' ? '#cf1322' : r.severity==='mid' ? '#d48806' : '#389e0d'

export const clauseTableCols = [
  { title: '条款', dataIndex: 'id', width: 70 },
  { title: '定位', width: 150, render: (_:unknown, r:{start_page:number;source_ref?:string}) => <span>{r.source_ref || `p${r.start_page}`}</span> },
  { title: '条款内容', dataIndex: 'text',
    render:(v:string)=> <span style={{whiteSpace:'pre-wrap', fontSize:13}}>{v}</span> }
]

export const fmtTime = (ts?: number) => {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
}

export const downloadText = (name: string, text: string, type='text/plain') => {
  const blob = new Blob([text], { type: `${type};charset=utf-8` })
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; a.click()
}

/* ============= 评审角色过滤 / 高亮 ============= */
/** 当前角色下该风险是否可见 */
export const roleRiskVisible = (r: Risk, role: Role): boolean => {
  if (role === 'CEO') return r.severity === 'high'
  if (role === '总监') return r.severity === 'high' || r.severity === 'mid'
  if (role === '业务人员') return false
  return true
}

/** 当前角色下该风险是否需要高亮 */
export const roleRiskHighlight = (r: Risk, role: Role): boolean => {
  if (role === 'CEO') return r.severity === 'high'
  if (role === '总监') return r.severity === 'high'
  return false
}
