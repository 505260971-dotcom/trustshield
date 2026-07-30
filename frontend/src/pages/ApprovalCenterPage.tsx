import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Empty, List, Segmented, Space, Spin, Tag, Typography, message } from 'antd'
import { ArrowRightOutlined, CheckCircleOutlined, FolderOpenOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { WorkboxItem } from '../types'
import { fmtTime } from '../components/common'

const { Text, Title } = Typography
type Props = { onOpenCase: (id: string) => void; onOpenCredit: (id: string) => void }
type ApprovalScope = 'all' | 'credit' | 'contract'
const stageText: Record<string, string> = { pending_director: '待主管复核', pending_final: '待最终批核', approval: '待主管审批', final_approval: '待最终审批' }

export default function ApprovalCenterPage({ onOpenCase, onOpenCredit }: Props) {
  const [items, setItems] = useState<WorkboxItem[]>([])
  const [scope, setScope] = useState<ApprovalScope>('all')
  const [loading, setLoading] = useState(true)
  const load = async () => { setLoading(true); try { setItems((await api.workbox('todo')).items || []) } catch (error: any) { message.error(error?.message || '审批中心加载失败') } finally { setLoading(false) } }
  useEffect(() => { load() }, [])
  const approvalItems = useMemo(() => items.filter(item => ['pending_director', 'pending_final', 'approval', 'final_approval'].includes(item.current_stage)), [items])
  const visible = useMemo(() => scope === 'all' ? approvalItems : approvalItems.filter(item => item.source_type === scope), [approvalItems, scope])
  const creditCount = approvalItems.filter(item => item.source_type === 'credit').length
  const contractCount = approvalItems.filter(item => item.source_type === 'contract').length
  const open = (item: WorkboxItem) => item.source_type === 'credit' ? onOpenCredit(item.target_id) : onOpenCase(item.target_id)
  return <div className="approval-center-page role-page">
    <section className="page-hero page-hero-light">
      <div><span className="section-kicker">DECISION CENTER</span><Title level={2}>审批中心</Title><Typography.Paragraph>只呈现当前需要你作出决定的信审与合同事项。先看建议结论、关键差异和未完成门禁，再进入详情批准、退回或上报。</Typography.Paragraph></div>
      <div className="page-hero-actions"><Button onClick={load}>刷新决策队列</Button></div>
    </section>
    <section className="compact-metrics"><div className="compact-metric metric-attention"><span className="compact-metric-icon"><SafetyCertificateOutlined /></span><div><small>待决信审</small><strong>{creditCount}</strong><em>授信条件、路由与风险依据</em></div></div><div className="compact-metric metric-warning"><span className="compact-metric-icon"><FolderOpenOutlined /></span><div><small>待决合同</small><strong>{contractCount}</strong><em>合同放行与例外处理</em></div></div><div className="compact-metric"><span className="compact-metric-icon"><CheckCircleOutlined /></span><div><small>全部待决</small><strong>{approvalItems.length}</strong><em>请逐项明确决策结论</em></div></div></section>
    <Card className="approval-queue-card" title="待我决策" extra={<Segmented value={scope} onChange={value => setScope(value as ApprovalScope)} options={[{ value: 'all', label: `全部 (${approvalItems.length})` }, { value: 'credit', label: `信审 (${creditCount})` }, { value: 'contract', label: `合同 (${contractCount})` }]} />}>
      <Alert showIcon type="info" style={{ marginBottom: 14 }} message="审批前请确认三件事" description="申请条件与建议条件的差异、尚未完成的风险/补件门禁、以及本次决策后将进入的下一审批或签约阶段。" />
      {loading ? <div className="page-loading"><Spin /><Text type="secondary">正在整理待决事项…</Text></div> : visible.length ? <List className="approval-decision-list" dataSource={visible} renderItem={item => <List.Item actions={[<Button key="open" type="primary" icon={<ArrowRightOutlined />} iconPosition="end" onClick={() => open(item)}>查看并决策</Button>]}><List.Item.Meta avatar={<span className={`action-kind action-kind-${item.source_type}`}>{item.source_type === 'credit' ? <SafetyCertificateOutlined /> : <FolderOpenOutlined />}</span>} title={<Space wrap><Text strong>{item.customer_name}</Text><Tag color={item.source_type === 'credit' ? 'cyan' : 'blue'}>{item.source_type === 'credit' ? '客户信审' : '合同案件'}</Tag><Tag color="purple">{stageText[item.current_stage] || item.current_stage}</Tag></Space>} description={<div className="approval-card-copy"><Text strong>{item.title}</Text><Text>当前需要你决定：{item.action_hint || '批准、退回或上报后续审批。'}</Text><Text type="secondary">申请 / 处理摘要：{item.detail || '进入详情查看完整依据、差异和历史意见。'}</Text><Text type="secondary">提交时间或最近更新：{fmtTime(item.updated_at || item.created_at || 0)}</Text></div>} /></List.Item>} /> : <Empty description="当前没有等待你决策的信审或合同事项" />}
    </Card>
  </div>
}
