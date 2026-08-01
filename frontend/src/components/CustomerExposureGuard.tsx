import { useState } from 'react'
import { Alert, Button, Card, Descriptions, Empty, InputNumber, List, Progress, Space, Tag, Typography } from 'antd'
import { CalculatorOutlined, CloudSyncOutlined, ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import type { CustomerHeadroom } from '../types'

const { Text } = Typography

const money = (value: number | null | undefined, currency = 'CNY') => value === null || value === undefined
  ? '—'
  : `${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${currency}`

const statusMeta = {
  healthy: { label: '敞口健康', color: 'green', alert: 'success' as const },
  warning: { label: '接近上限', color: 'orange', alert: 'warning' as const },
  blocked: { label: '客户级阻断', color: 'red', alert: 'error' as const },
  unknown: { label: '待补敞口快照', color: 'default', alert: 'warning' as const },
}

type Props = { headroom?: CustomerHeadroom | null; loading?: boolean; onRefresh?: () => void; onSimulate?: (amount: number) => Promise<void> }

export default function CustomerExposureGuard({ headroom, loading, onRefresh, onSimulate }: Props) {
  const [amount, setAmount] = useState<number | null>(null)
  const [simulating, setSimulating] = useState(false)
  if (!headroom && loading) return <Card className="customer-exposure-guard" title={<Space><CloudSyncOutlined />客户级动态敞口守卫</Space>} loading />
  if (!headroom) return <Card className="customer-exposure-guard" title={<Space><CloudSyncOutlined />客户级动态敞口守卫</Space>}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可用客户敞口数据" /></Card>

  const meta = statusMeta[headroom.status]
  const simulation = headroom.simulation
  const canSimulate = typeof amount === 'number' && amount >= 0
  const simulate = async () => {
    if (!onSimulate || !canSimulate) return
    setSimulating(true)
    try { await onSimulate(amount || 0) } finally { setSimulating(false) }
  }
  const utilization = Math.min(100, Math.max(0, headroom.utilization_pct || 0))
  return <Card className="customer-exposure-guard" title={<Space><CloudSyncOutlined />客户级动态敞口守卫<Tag color={meta.color}>{meta.label}</Tag></Space>} extra={<Button size="small" icon={<ReloadOutlined />} onClick={onRefresh}>刷新</Button>}>
    <Alert type={meta.alert} showIcon message={headroom.alerts.length ? headroom.alerts[0].message : '当前客户的既有敞口、在途合同和信审上限处于可解释状态。'} description="CRM/ERP 快照代表既有敞口；未归档合同代表在途承诺，两者分开计算，避免刷新快照后重复计入。" />
    <div className="exposure-guard-metrics">
      <div><span>信审上限</span><strong>{money(headroom.credit_limit, headroom.currency)}</strong><Text type="secondary">当前有效 V{headroom.credit_version || '—'}</Text></div>
      <div><span>既有敞口</span><strong>{money(headroom.existing_exposure, headroom.currency)}</strong><Text type="secondary">应收 + 已入单</Text></div>
      <div><span>在途合同</span><strong>{money(headroom.pipeline_contract_amount, headroom.currency)}</strong><Text type="secondary">未归档合同</Text></div>
      <div><span>预计剩余</span><strong className={(headroom.headroom_after_pipeline || 0) < 0 ? 'is-danger' : headroom.status === 'warning' ? 'is-warning' : 'is-success'}>{money(headroom.headroom_after_pipeline, headroom.currency)}</strong><Text type="secondary">合同计入后</Text></div>
    </div>
    <div className="exposure-guard-progress"><div><Text strong>当前客户额度使用率</Text><Text type="secondary">{headroom.utilization_pct === null || headroom.utilization_pct === undefined ? '待补快照' : `${headroom.utilization_pct.toFixed(1)}%`}</Text></div><Progress percent={utilization} status={headroom.status === 'blocked' ? 'exception' : headroom.status === 'warning' ? 'active' : 'normal'} showInfo={false} strokeColor={headroom.status === 'blocked' ? '#cf1322' : headroom.status === 'warning' ? '#d48806' : '#389e0d'} /></div>
    <div className="exposure-guard-simulator">
      <div className="exposure-guard-simulator-head"><div><Text strong><CalculatorOutlined /> 模拟新订单</Text><Text type="secondary">不写入 CRM/ERP，只预览加入新订单后的客户级门禁。</Text></div><Space.Compact><InputNumber min={0} precision={2} value={amount ?? undefined} onChange={value => setAmount(typeof value === 'number' ? value : null)} placeholder="输入金额" addonAfter={headroom.currency} /><Button type="primary" icon={<CalculatorOutlined />} loading={simulating} disabled={!canSimulate} onClick={simulate}>计算</Button></Space.Compact></div>
      {simulation.amount > 0 && <div className={`exposure-guard-simulation is-${simulation.status}`}><div><span>模拟订单</span><strong>{money(simulation.amount, headroom.currency)}</strong></div><div><span>模拟后总敞口</span><strong>{money(simulation.projected_total_exposure, headroom.currency)}</strong></div><div><span>模拟后剩余</span><strong>{money(simulation.headroom, headroom.currency)}</strong></div><div><span>模拟后使用率</span><strong>{simulation.utilization_pct === null || simulation.utilization_pct === undefined ? '—' : `${simulation.utilization_pct.toFixed(1)}%`}</strong></div>{simulation.alerts.map(alert => <Alert key={alert.code} type={alert.level === 'blocked' ? 'error' : 'warning'} showIcon message={alert.message} />)}</div>}
    </div>
    {headroom.snapshot && <Descriptions className="exposure-guard-source" size="small" column={{ xs: 1, md: 3 }}>
      <Descriptions.Item label="快照来源">{headroom.snapshot.source || '—'}</Descriptions.Item>
      <Descriptions.Item label="快照时间">{headroom.snapshot.as_of ? new Date(headroom.snapshot.as_of * 1000).toLocaleString('zh-CN') : '—'}</Descriptions.Item>
      <Descriptions.Item label="最长逾期">{headroom.snapshot.overdue_days ?? '—'} 天</Descriptions.Item>
    </Descriptions>}
    {headroom.contracts.length > 0 && <List className="exposure-guard-contracts" size="small" header={<Space><SafetyCertificateOutlined />计入预测的在途合同（{headroom.contracts.length}）</Space>} dataSource={headroom.contracts.slice(0, 5)} renderItem={contract => <List.Item><List.Item.Meta title={<Space wrap><Tag color={contract.stage === 'ready_to_sign' ? 'green' : 'blue'}>{contract.version_label || contract.stage}</Tag><Text strong>{contract.filename || contract.case_id}</Text></Space>} description={<Text type="secondary">{money(contract.amount, contract.currency || headroom.currency)} · {contract.review_status || '待审查'} · {contract.case_id}</Text>} /></List.Item>} />}
    {headroom.contracts.length > 5 && <Text type="secondary">还有 {headroom.contracts.length - 5} 个在途合同未展开。</Text>}
  </Card>
}
