import { useEffect, useMemo, useState } from 'react'
import { Badge, Button, Card, Empty, List, Segmented, Space, Spin, Tag, Typography, message } from 'antd'
import { ArrowRightOutlined, CheckCircleOutlined, ClockCircleOutlined, FileAddOutlined, FolderOpenOutlined, SafetyCertificateOutlined, UnorderedListOutlined, WarningOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { WorkboxItem } from '../types'
import { fmtTime } from '../components/common'
import { useAuth } from '../context/AuthContext'
import { stageInfo, workItemAction } from '../components/workflow'

const { Text, Title } = Typography
type Bucket = 'todo' | 'in_progress' | 'draft' | 'done'
type Props = {
  onCreateContract: () => void
  onCreateCredit: () => void
  onOpenCase: (id: string) => void
  onOpenCredit: (id: string) => void
  onNavigate: (path: string) => void
  canCreateContract: boolean
  canCreateCredit: boolean
}

const bucketCopy: Record<Bucket, { label: string; empty: string }> = {
  todo: { label: '待我处理', empty: '当前没有待处理事项。' },
  in_progress: { label: '正在推进', empty: '当前没有在途事项。' },
  draft: { label: '未提交草稿', empty: '没有未提交草稿。' },
  done: { label: '我的记录', empty: '暂无已办记录。' },
}
const roleTitle: Record<string, string> = { business: '我的业务', reviewer: '我的待办', director: '我的决策', admin: '我的决策' }
const stageLabel: Record<string, string> = {
  draft: '草稿', awaiting_credit: '等待有效信审', ai_review: '系统审查中', legal_review: '审核员复核', awaiting_business: '待业务补件', approval: '待主管审批', final_approval: '待最终审批', ready_to_sign: '可签约', archived: '已归档', returned_to_reviewer: '退回审核专员', returned_to_business: '待业务补充', pending_director: '待主管复核', pending_final: '待最终审批', approved: '已生效', rejected: '已拒绝', superseded: '历史版本',
}
const roleLabel: Record<string, string> = { business: '业务申请人', reviewer: '信用审核专员', director: '财务审批主管', admin: '最终审批人', system: '系统' }
const priorityLabel: Record<string, string> = { urgent: '紧急', high: '高优先级', normal: '普通', low: '低' }
const priorityWeight = (value: string) => ({ urgent: 0, high: 1, normal: 2, low: 3 } as Record<string, number>)[value] ?? 4
const roleGuidance: Record<string, { label: string; summary: string; steps: Array<[string, string]> }> = {
  business: {
    label: '业务申请人', summary: '你负责把业务背景和材料交代清楚，并在退回后尽快补齐；系统会替你检查信审与合同的前置条件。',
    steps: [['01', '发起或补齐申请',], ['02', '确认客户已有有效信审',], ['03', '跟进退回意见与签约结果',]],
  },
  reviewer: {
    label: '信用审核专员', summary: '你负责核验事实、处置风险、确认系统建议，并把仍需决策的例外清楚地交给下一审批层。',
    steps: [['01', '先处理高优先级与退回事项',], ['02', '核验证据、风险和信审边界',], ['03', '明确建议后提交复核或退回补件',]],
  },
  director: {
    label: '财务审批主管', summary: '你负责判断申请条件、系统建议和审核意见之间的差异，并决定放行、退回或上报最终审批。',
    steps: [['01', '先看待决事项和阻断门禁',], ['02', '比对申请条件与处理建议',], ['03', '明确决策及后续流转对象',]],
  },
  admin: {
    label: '最终审批人', summary: '你负责处理重大例外和最终商业边界，重点确认未解决风险、审批依据与最终放行后果。',
    steps: [['01', '识别需终审的例外与阻断项',], ['02', '查看前序意见和完整依据',], ['03', '作出最终批准、退回或拒绝决定',]],
  },
}

function actionLabel(item: WorkboxItem) {
  return workItemAction(item)
}

export default function WorkbenchPage({ onCreateContract, onCreateCredit, onOpenCase, onOpenCredit, onNavigate, canCreateContract, canCreateCredit }: Props) {
  const { user } = useAuth()
  const role = user?.role || 'business'
  const [items, setItems] = useState<Record<Bucket, WorkboxItem[]>>({ todo: [], in_progress: [], draft: [], done: [] })
  const [bucket, setBucket] = useState<Bucket>('todo')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const [todo, inProgress, draft, done] = await Promise.all([api.workbox('todo'), api.workbox('in_progress'), api.workbox('draft'), api.workbox('done')])
      setItems({ todo: todo.items || [], in_progress: inProgress.items || [], draft: draft.items || [], done: done.items || [] })
    } catch (error: any) { message.error(error?.message || '待办加载失败') } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const todo = useMemo(() => [...items.todo].sort((a, b) => priorityWeight(a.priority) - priorityWeight(b.priority) || Number(a.due_at || Infinity) - Number(b.due_at || Infinity)), [items.todo])
  const highCount = todo.filter(item => ['urgent', 'high'].includes(item.priority)).length
  const dueSoon = todo.filter(item => item.due_at && item.due_at * 1000 < Date.now() + 48 * 3600 * 1000).length
  const returned = todo.filter(item => ['returned_to_business', 'returned_to_reviewer', 'awaiting_business'].includes(item.current_stage)).length
  const selected = bucket === 'todo' ? todo : items[bucket]
  const focus = todo[0]
  const guidance = roleGuidance[role] || roleGuidance.business
  const open = (item: WorkboxItem) => item.source_type === 'credit' ? onOpenCredit(item.target_id) : onOpenCase(item.target_id)

  const createButtons = () => {
    if (role === 'business') return <Space wrap><Button type="primary" size="large" icon={<SafetyCertificateOutlined />} onClick={onCreateCredit}>发起客户信审</Button><Button size="large" icon={<FileAddOutlined />} onClick={onCreateContract}>发起合同审查</Button></Space>
    if (role === 'reviewer') return <Button type="primary" size="large" icon={<SafetyCertificateOutlined />} onClick={onCreateCredit}>新建信审版本</Button>
    return <Button type="primary" size="large" onClick={() => onNavigate('/approvals')}>进入审批中心</Button>
  }

  return <div className="action-center-page">
    <section className="action-hero">
      <div><span className="section-kicker">{guidance.label}</span><Title level={2}>{roleTitle[role] || '待我处理'}</Title><Text>{guidance.summary}</Text></div>
      <div className="action-hero-controls"><Badge count={highCount} showZero color={highCount ? '#cf1322' : '#52c41a'} text={highCount ? '项高优先级事项待处理' : '当前没有高优先级事项'} /><Space wrap>{createButtons()}<Button size="large" icon={<FolderOpenOutlined />} onClick={() => onNavigate('/customers')}>客户工作台</Button></Space></div>
    </section>

    <section className="action-metrics" aria-label="工作概览">
      <div className="action-metric action-metric-primary"><span><UnorderedListOutlined /></span><div><small>待我处理</small><strong>{todo.length}</strong></div></div>
      <div className="action-metric"><span><WarningOutlined /></span><div><small>高优先级</small><strong>{highCount}</strong></div></div>
      <div className="action-metric"><span><ClockCircleOutlined /></span><div><small>48 小时内到期</small><strong>{dueSoon}</strong></div></div>
      <div className="action-metric"><span><SafetyCertificateOutlined /></span><div><small>被退回 / 待补件</small><strong>{returned}</strong></div></div>
    </section>

    <section className="action-role-guide" aria-label="当前角色处理指引">
      <div className="action-role-guide-head"><span className="section-kicker">HOW TO MOVE WORK FORWARD</span><Text strong>本角色的处理路径</Text><Text type="secondary">先解决当前卡点，再把事项交给正确的下一责任人。</Text></div>
      <div className="action-role-guide-steps">{guidance.steps.map(([number, copy]) => <div className="action-role-guide-step" key={number}><span>{number}</span><Text>{copy}</Text></div>)}</div>
    </section>

    {focus && <Card className="focus-action-card" title={<Space><WarningOutlined /><span>优先处理</span></Space>} extra={<Tag color={focus.source_type === 'credit' ? 'cyan' : 'blue'}>{focus.source_type === 'credit' ? '客户信审' : '合同案件'}</Tag>}>
      <div className="focus-action-content"><div className="focus-action-main"><div className="focus-action-title"><Text strong>{focus.customer_name}</Text><Tag color={focus.priority === 'urgent' ? 'red' : focus.priority === 'high' ? 'orange' : 'default'}>{priorityLabel[focus.priority] || '普通'}</Tag><Tag>{stageLabel[focus.current_stage] || focus.current_stage}</Tag></div><Title level={4}>{focus.title}</Title>{focus.detail && <Text>{focus.detail}</Text>}<div className="focus-action-handoff"><span>责任：{focus.responsible_name === '我' ? '我' : `${roleLabel[focus.responsible_role] || focus.responsible_role} · ${focus.responsible_name}`}</span>{focus.action_hint && <span>下一步：{focus.action_hint}</span>}{focus.due_at && <span>截止：{fmtTime(focus.due_at)}</span>}</div></div><Button type="primary" size="large" icon={<ArrowRightOutlined />} onClick={() => open(focus)}>{actionLabel(focus)}</Button></div>
    </Card>}
    {!focus && bucket === 'todo' && <Card className="focus-action-card focus-empty-card" title={<Space><CheckCircleOutlined /><span>当前没有待办，接下来可以做什么？</span></Space>}>
      <div className="focus-empty-content"><div><Title level={4}>工作队列已清空</Title><Text type="secondary">可以从客户工作台继续推进业务，或查看历史记录和流程结果。</Text></div><Space wrap>{createButtons()}<Button icon={<FolderOpenOutlined />} onClick={() => onNavigate('/customers')}>查看客户工作台</Button></Space></div>
    </Card>}

    <Card className="action-list-card" title="业务队列" extra={<Button type="text" onClick={load}>刷新</Button>}>
      <Segmented className="action-bucket-tabs" value={bucket} onChange={value => setBucket(value as Bucket)} options={(['todo', 'in_progress', 'draft', 'done'] as Bucket[]).map(value => ({ value, label: `${bucketCopy[value].label} (${items[value].length})` }))} />
      {loading ? <div className="page-loading"><Spin /></div> : selected.length ? <List className="action-list" dataSource={selected} renderItem={item => { const meta = stageInfo(item.current_stage); return <List.Item actions={[<Button key="open" type={bucket === 'todo' ? 'primary' : 'link'} onClick={() => open(item)}>{bucket === 'todo' ? actionLabel(item) : '查看详情'}{bucket === 'todo' && <ArrowRightOutlined />}</Button>]}><List.Item.Meta avatar={<span className={`action-kind action-kind-${item.source_type}`}>{item.source_type === 'credit' ? <SafetyCertificateOutlined /> : <FolderOpenOutlined />}</span>} title={<Space wrap><Text strong>{item.customer_name}</Text><Tag color={item.source_type === 'credit' ? 'cyan' : 'blue'}>{item.kind_label}</Tag><Tag color={meta.color}>{meta.label}</Tag></Space>} description={<div className="action-list-copy"><Text strong>{item.title}</Text>{item.detail && <Text>{item.detail}</Text>}{item.action_hint && <Text className="action-list-next">下一步：{item.action_hint}</Text>}<Text type="secondary">责任：{item.responsible_name === '我' ? '我' : `${roleLabel[item.responsible_role] || item.responsible_role} · ${item.responsible_name}`}{item.due_at ? ` · 截止 ${fmtTime(item.due_at)}` : ''}</Text></div>} /></List.Item> }} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<Space direction="vertical"><Text>{bucketCopy[bucket].empty}</Text>{bucket === 'todo' && <Space>{canCreateCredit && <Button type="primary" onClick={onCreateCredit}>发起客户信审</Button>}{canCreateContract && <Button onClick={onCreateContract}>发起合同审查</Button>}</Space>}</Space>} />}
    </Card>
  </div>
}
