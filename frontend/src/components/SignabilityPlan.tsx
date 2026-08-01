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
  credit_reapproval: { label: '必须更新客户信用审核', color: 'red', type: 'error' as const, icon: <SafetyCertificateOutlined /> },
}

const itemTag = (item: SignabilityItem) => {
  if (item.status === 'passed') return <Tag color="green">已处理</Tag>
  if (item.requires_credit_reapproval) return <Tag color="red">需重新进行信用审核</Tag>
  if (item.can_resolve_in_contract) return <Tag color="orange">合同可修订</Tag>
  return <Tag color="blue">待核验</Tag>
}

export default function SignabilityPlan({ plan, loading, items }: { plan?: SignabilityPlanData | null; loading?: boolean; items?: SignabilityItem[] }) {
  if (loading && !plan) return <Card className="signability-plan" size="small" title="距可签约还差什么"><Skeleton active paragraph={{ rows: 4 }} /></Card>
  if (!plan) return null
  const meta = statusMeta[plan.status]
  const visibleItems = items || plan.items
  const currency = plan.credit.currency || 'CNY'
  return <Card className="signability-plan" size="small" title={<Space><WarningOutlined />距离签约还差什么<Tag color={meta.color}>{meta.label}</Tag></Space>}>
    <Alert type={meta.type} showIcon message={plan.next_action} description={plan.status === 'credit_reapproval' ? '客户信用条件不能通过合同例外审批绕过；标记为“需重新进行信用审核”的事项，必须回到信用审核流程处理。' : plan.status === 'contract_revision' ? '系统已整理出可以直接执行的最小修改路径。上传新版本后，系统会重新检查是否符合信用审核条件。' : '当前报告未发现阻止放行的问题，但最终签约仍需完成案件中的审批、补充材料和风险处理。'} />
    <div className="signability-metrics">
      <div><span>必须处理</span><strong className={plan.counts.blocked ? 'is-danger' : 'is-success'}>{plan.counts.blocked}</strong><Text type="secondary">阻断项</Text></div>
      <div><span>合同可修订</span><strong className={plan.counts.repairable ? 'is-warning' : 'is-success'}>{plan.counts.repairable}</strong><Text type="secondary">可在当前信用审核条件内解决</Text></div>
      <div><span>需重新审核</span><strong className={plan.counts.requires_credit_reapproval ? 'is-danger' : 'is-success'}>{plan.counts.requires_credit_reapproval}</strong><Text type="secondary">客户信用条件问题</Text></div>
      <div><span>待核验</span><strong className={plan.counts.pending ? 'is-warning' : 'is-success'}>{plan.counts.pending}</strong><Text type="secondary">流程或证据</Text></div>
    </div>
    {plan.credit.case_id && <div className="signability-credit-strip">
      <div><span>信用审核条件</span><strong>{plan.credit.customer_name || '当前客户'} · V{plan.credit.version || '—'}</strong></div>
      <div><span>已有额度占用</span><strong>{money(plan.credit.existing_exposure, currency)}</strong></div>
      <div><span>本合同金额</span><strong>{money(plan.credit.contract_amount, currency)}</strong></div>
      <div><span>合同可用额度</span><strong className={plan.credit.available_for_contract !== null && plan.credit.available_for_contract !== undefined && plan.credit.available_for_contract < 0 ? 'is-danger' : 'is-success'}>{money(plan.credit.available_for_contract, currency)}</strong></div>
    </div>}
    {visibleItems.length ? <List className="signability-item-list" dataSource={visibleItems} renderItem={item => <List.Item>
      <List.Item.Meta avatar={<span className={`signability-item-icon is-${item.status}`}>{item.requires_credit_reapproval ? <SafetyCertificateOutlined /> : item.status === 'passed' ? <CheckCircleOutlined /> : <EditOutlined />}</span>} title={<Space wrap><Text strong>{item.title}</Text><Tag>{item.rule_id}</Tag>{itemTag(item)}</Space>} description={<div className="signability-item-copy"><div><span>当前</span><b>{item.current}</b><ArrowRightOutlined /><span>目标</span><b>{item.target}</b></div><Text type="secondary">{item.action}</Text></div>} />
    </List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前角色没有可直接展示的修订项" />}
  </Card>
}
