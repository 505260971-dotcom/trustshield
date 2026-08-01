import { Alert, Card, Empty, List, Skeleton, Space, Tag, Typography } from 'antd'
import { ArrowRightOutlined, CheckCircleOutlined, EditOutlined, SafetyCertificateOutlined, WarningOutlined } from '@ant-design/icons'
import type { SignabilityItem, SignabilityPlan as SignabilityPlanData } from '../types'

const { Text } = Typography

const money = (value: number | null | undefined, currency = 'CNY') => value === null || value === undefined
  ? '—'
  : `${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${currency}`

const statusMeta = {
  ready: { label: '已具备签约条件', color: 'green', type: 'success' as const, icon: <CheckCircleOutlined /> },
  contract_revision: { label: '需要合同修订', color: 'orange', type: 'warning' as const, icon: <EditOutlined /> },
  credit_reapproval: { label: '必须更新客户信审', color: 'red', type: 'error' as const, icon: <SafetyCertificateOutlined /> },
}

const itemTag = (item: SignabilityItem) => {
  if (item.status === 'passed') return <Tag color="green">已闭环</Tag>
  if (item.requires_credit_reapproval) return <Tag color="red">需重新信审</Tag>
  if (item.can_resolve_in_contract) return <Tag color="orange">合同可修订</Tag>
  return <Tag color="blue">待核验</Tag>
}

export default function SignabilityPlan({ plan, loading, items }: { plan?: SignabilityPlanData | null; loading?: boolean; items?: SignabilityItem[] }) {
  if (loading && !plan) return <Card className="signability-plan" size="small" title="距可签约还差什么"><Skeleton active paragraph={{ rows: 4 }} /></Card>
  if (!plan) return null
  const meta = statusMeta[plan.status]
  const visibleItems = items || plan.items
  const currency = plan.credit.currency || 'CNY'
  return <Card className="signability-plan" size="small" title={<Space><WarningOutlined />距可签约还差什么<Tag color={meta.color}>{meta.label}</Tag></Space>}>
    <Alert type={meta.type} showIcon message={plan.next_action} description={plan.status === 'credit_reapproval' ? '客户级信用边界不能通过合同例外审批绕过；以下项目中标记为“需重新信审”的事项必须回到信审流程。' : plan.status === 'contract_revision' ? '系统已把当前阻断压缩为可执行的最小修订路径。上传新版本后，系统会重新计算是否回到信审边界。' : '当前报告未发现阻断项，但最终签约仍需满足案件中的审批、补件和处置门禁。'} />
    <div className="signability-metrics">
      <div><span>必须处理</span><strong className={plan.counts.blocked ? 'is-danger' : 'is-success'}>{plan.counts.blocked}</strong><Text type="secondary">阻断项</Text></div>
      <div><span>合同可修订</span><strong className={plan.counts.repairable ? 'is-warning' : 'is-success'}>{plan.counts.repairable}</strong><Text type="secondary">可在当前信审内解决</Text></div>
      <div><span>重新信审</span><strong className={plan.counts.requires_credit_reapproval ? 'is-danger' : 'is-success'}>{plan.counts.requires_credit_reapproval}</strong><Text type="secondary">客户级门禁</Text></div>
      <div><span>待核验</span><strong className={plan.counts.pending ? 'is-warning' : 'is-success'}>{plan.counts.pending}</strong><Text type="secondary">流程或证据</Text></div>
    </div>
    {plan.credit.case_id && <div className="signability-credit-strip">
      <div><span>信审边界</span><strong>{plan.credit.customer_name || '当前客户'} · V{plan.credit.version || '—'}</strong></div>
      <div><span>既有敞口</span><strong>{money(plan.credit.existing_exposure, currency)}</strong></div>
      <div><span>本合同金额</span><strong>{money(plan.credit.contract_amount, currency)}</strong></div>
      <div><span>合同可用空间</span><strong className={plan.credit.available_for_contract !== null && plan.credit.available_for_contract !== undefined && plan.credit.available_for_contract < 0 ? 'is-danger' : 'is-success'}>{money(plan.credit.available_for_contract, currency)}</strong></div>
    </div>}
    {visibleItems.length ? <List className="signability-item-list" dataSource={visibleItems} renderItem={item => <List.Item>
      <List.Item.Meta avatar={<span className={`signability-item-icon is-${item.status}`}>{item.requires_credit_reapproval ? <SafetyCertificateOutlined /> : item.status === 'passed' ? <CheckCircleOutlined /> : <EditOutlined />}</span>} title={<Space wrap><Text strong>{item.title}</Text><Tag>{item.rule_id}</Tag>{itemTag(item)}</Space>} description={<div className="signability-item-copy"><div><span>当前</span><b>{item.current}</b><ArrowRightOutlined /><span>目标</span><b>{item.target}</b></div><Text type="secondary">{item.action}</Text></div>} />
    </List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前角色没有可直接展示的修订项" />}
  </Card>
}
