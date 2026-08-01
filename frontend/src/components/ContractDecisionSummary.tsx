import type { ReactNode } from 'react'
import { Alert, Button, Card, Descriptions, Empty, Space, Tag, Typography } from 'antd'
import { ArrowRightOutlined, CheckCircleTwoTone, CloseCircleTwoTone, QuestionCircleTwoTone, SafetyCertificateOutlined } from '@ant-design/icons'
import type { CreditConditions, CreditExposure, Report, Risk, VersionComparison } from '../types'

const { Text, Title } = Typography

type DecisionStatus = 'blocked' | 'passed' | 'unknown'

type DecisionRow = {
  key: string
  label: string
  policy: string
  contract: string
  context: string
  status: DecisionStatus
  risk?: Risk
}

const numberValue = (value: unknown): number | undefined => {
  if (value === null || value === undefined || value === '') return undefined
  if (typeof value === 'number' && Number.isFinite(value)) return value
  const parsed = Number(String(value).replace(/,/g, '').replace(/元|人民币|CNY|RMB/gi, '').trim())
  return Number.isFinite(parsed) ? parsed : undefined
}

const money = (value: unknown, currency = 'CNY') => {
  const parsed = numberValue(value)
  return parsed === undefined ? '—' : `${parsed.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${currency}`
}

const percentage = (value: unknown) => {
  const parsed = numberValue(value)
  return parsed === undefined ? '—' : `${parsed.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}%`
}

const riskFor = (risks: Risk[], ruleId: string) => risks.find(item => item.rule_id === ruleId)
const riskKey = (risk: Risk) => risk.finding_id || `${risk.clause_id}-${risk.rule_id}`

const paymentMethodLabel = (value: unknown) => ({
  acceptance_bill: '银行承兑汇票',
  bank_transfer: '银行转账',
  commercial_acceptance: '商业承兑汇票',
}[String(value || '')] || String(value || '未识别'))

const statusMeta: Record<DecisionStatus, { label: string; color: string; icon: ReactNode }> = {
  blocked: { label: '阻断', color: 'red', icon: <CloseCircleTwoTone twoToneColor="#cf1322" /> },
  passed: { label: '符合', color: 'green', icon: <CheckCircleTwoTone twoToneColor="#389e0d" /> },
  unknown: { label: '待核验', color: 'orange', icon: <QuestionCircleTwoTone twoToneColor="#d48806" /> },
}

function comparisonRows(report: Report, visibleRiskKeys: Set<string>): DecisionRow[] {
  const fields = report.contract_fields || {}
  const decision = report.credit_decision
  const conditions: Partial<CreditConditions> = decision?.conditions || {}
  const risks = report.risks || []
  const exposure: Partial<NonNullable<CreditExposure['payload']>> = decision?.exposure_snapshot_at_review || {}
  const currency = conditions.currency || fields.currency || 'CNY'
  const amountRisk = riskFor(risks, 'CREDIT_EXPOSURE')
  const termRisk = riskFor(risks, 'CREDIT_TERM')
  const prepaymentRisk = riskFor(risks, 'CREDIT_PREPAYMENT')
  const paymentRisk = riskFor(risks, 'CREDIT_PAYMENT_METHOD')
  const deliveryRisk = riskFor(risks, 'CREDIT_DELIVERY_MODE')
  const contractAmount = numberValue(fields.total_amount) ?? numberValue(amountRisk?.facts?.contract_amount)
  const receivables = numberValue(exposure.current_receivables) || 0
  const bookedOrders = numberValue(exposure.booked_order_amount) || 0
  const existingExposure = receivables + bookedOrders
  const totalExposure = numberValue(amountRisk?.facts?.total_exposure) ?? (contractAmount === undefined ? undefined : existingExposure + contractAmount)
  const maxCredit = numberValue(conditions.max_credit_amount)
  const termDays = numberValue(termRisk?.facts?.term_days)
  const prepayment = numberValue(prepaymentRisk?.facts?.prepayment_ratio)
  const paymentTerms = String(fields.payment_terms || '')
  const paymentContract = paymentRisk
    ? paymentMethodLabel(paymentRisk.facts?.payment_method || 'acceptance_bill')
    : /承兑|acceptance\s+bill/i.test(paymentTerms) ? '银行承兑汇票' : paymentTerms || '未识别付款方式'
  const paymentPass = !paymentRisk && /银行转账|bank\s*transfer/i.test(paymentContract)
  const deliveryContract = deliveryRisk ? 'VMI/JIT' : '未发现 VMI/JIT'

  return [
    {
      key: 'exposure', label: '额度占用合计',
      policy: maxCredit === undefined ? '信用审核额度未提供' : `≤ ${money(maxCredit, currency)}`,
      contract: contractAmount === undefined ? '未识别合同金额' : money(contractAmount, currency),
      context: totalExposure === undefined ? '未读取已有额度占用' : `已有 ${money(existingExposure, currency)} · 合计 ${money(totalExposure, currency)}`,
      status: amountRisk ? 'blocked' : totalExposure === undefined || maxCredit === undefined ? 'unknown' : totalExposure <= maxCredit ? 'passed' : 'blocked',
      risk: amountRisk,
    },
    {
      key: 'term', label: '最长账期',
      policy: conditions.max_payment_days === undefined ? '信用审核账期未提供' : `≤ ${conditions.max_payment_days} 天`,
      contract: termDays === undefined ? (paymentTerms || '未识别账期') : `${termDays} 天`,
      context: termRisk && visibleRiskKeys.has(riskKey(termRisk)) ? termRisk.numeric_note : '合同账期与信用审核上限的比较结果',
      status: termRisk ? 'blocked' : termDays === undefined || conditions.max_payment_days === undefined ? 'unknown' : termDays <= Number(conditions.max_payment_days) ? 'passed' : 'blocked',
      risk: termRisk,
    },
    {
      key: 'prepayment', label: '交付前收款',
      policy: conditions.min_prepayment_ratio === undefined ? '信用审核收款比例未提供' : `≥ ${percentage(conditions.min_prepayment_ratio)}`,
      contract: prepayment === undefined ? '未识别比例' : percentage(prepayment),
      context: prepaymentRisk && visibleRiskKeys.has(riskKey(prepaymentRisk)) ? prepaymentRisk.numeric_note : '合同收款比例与信用审核下限的比较结果',
      status: prepaymentRisk ? 'blocked' : prepayment === undefined || conditions.min_prepayment_ratio === undefined ? 'unknown' : prepayment >= Number(conditions.min_prepayment_ratio) ? 'passed' : 'blocked',
      risk: prepaymentRisk,
    },
    {
      key: 'payment_method', label: '付款方式',
      policy: (conditions.allowed_payment_methods || []).map(paymentMethodLabel).join('、') || '未提供',
      contract: paymentContract,
      context: paymentRisk && visibleRiskKeys.has(riskKey(paymentRisk)) ? paymentRisk.evidence : '合同字段/付款节点',
      status: paymentRisk ? 'blocked' : paymentPass ? 'passed' : 'unknown',
      risk: paymentRisk,
    },
    {
      key: 'delivery_mode', label: '交付模式',
      policy: conditions.allow_vmi_jit ? '允许 VMI/JIT' : '不允许 VMI/JIT',
      contract: deliveryContract,
      context: deliveryRisk && visibleRiskKeys.has(riskKey(deliveryRisk)) ? deliveryRisk.evidence : '合同正文检查结果',
      status: deliveryRisk ? 'blocked' : decision ? 'passed' : 'unknown',
      risk: deliveryRisk,
    },
  ]
}

export function ContractDecisionSummary({ report, visibleRisks, onSelectRisk }: { report: Report; visibleRisks?: Risk[]; onSelectRisk?: (risk: Risk) => void }) {
  const fields = report.contract_fields || {}
  const decision = report.credit_decision
  const conditions: Partial<CreditConditions> = decision?.conditions || {}
  const visibleRiskKeys = new Set((visibleRisks || report.risks || []).map(riskKey))
  const rows = comparisonRows(report, visibleRiskKeys)
  const creditRisks = (report.risks || []).filter(item => item.rule_id?.startsWith('CREDIT_'))
  const blocked = creditRisks.length > 0
  const unknown = rows.filter(row => row.status === 'unknown').length
  const conclusion = !decision
    ? '未绑定已生效的信用审核版本，无法确定合同条件边界'
    : blocked
      ? `当前版本不能签约，有 ${creditRisks.length} 项合同条件不符合信用审核要求`
      : unknown
        ? `信用审核条件未发现阻止放行的问题，但仍有 ${unknown} 项商业条件待核验`
        : '当前版本符合信用审核条件，可以继续处理合同底线风险'

  return <Card className="contract-decision-summary" size="small" title={<Space><SafetyCertificateOutlined />合同决策摘要</Space>}>
    <Alert
      type={!decision || blocked ? 'error' : unknown ? 'warning' : 'success'}
      showIcon
      message={conclusion}
      description={blocked ? '合同条件不符合信用审核要求，不能在合同端采纳、忽略或通过普通例外审批放行；请修订合同或重新发起信用审核。' : '摘要中的商业条件均来自当前报告、已生效信用审核记录或合同原文提取结果。'}
    />
    <div className="decision-summary-facts">
      <div><span>客户</span><strong>{decision?.customer_name || fields.parties?.['甲方'] || '未识别'}</strong><Text type="secondary">{decision ? `信用审核 V${decision.version}` : '未绑定信用审核'}</Text></div>
      <div><span>业务类型</span><strong>{fields.business_type || decision?.business_type || '—'}</strong><Text type="secondary">{report.filename || '当前合同'}</Text></div>
      <div><span>合同金额</span><strong>{money(fields.total_amount, fields.currency || conditions.currency || 'CNY')}</strong><Text type="secondary">{fields.currency || conditions.currency || '币种待确认'}</Text></div>
      <div><span>审查结论</span><strong className={blocked ? 'is-danger' : unknown ? 'is-warning' : 'is-success'}>{report.summary?.overall_level || '待确认'}</strong><Text type="secondary">风险 {report.summary?.n_risks || 0} 条 · 高风险 {report.summary?.high || 0} 条</Text></div>
    </div>
    <div className="decision-summary-section-head"><div><span className="card-kicker">商业条件检查</span><Title level={5}>信用审核条件 / 合同 / 额度占用对比</Title></div><Text type="secondary">点击不符合项可回到原文依据</Text></div>
    <div className="decision-compare-table">
      <div className="decision-compare-row is-header"><span>商业条件</span><span>已生效信用审核</span><span>合同提取</span><span>额度占用 / 上下文</span><span>结果</span></div>
      {rows.map(row => {
        const meta = statusMeta[row.status]
        return <div className={`decision-compare-row is-${row.status}`} key={row.key}>
          <strong>{row.label}</strong><span>{row.policy}</span><span>{row.contract}</span><span>{row.context}</span>
          <span className="decision-result-cell">{meta.icon}<Tag color={meta.color}>{meta.label}</Tag>{row.risk && onSelectRisk && visibleRiskKeys.has(riskKey(row.risk)) && <Button type="link" size="small" icon={<ArrowRightOutlined />} onClick={() => onSelectRisk(row.risk!)}>证据</Button>}</span>
        </div>
      })}
    </div>
    {decision && <Descriptions className="decision-summary-boundary" size="small" column={{ xs: 1, md: 3 }}>
      <Descriptions.Item label="信用审核额度">{money(conditions.max_credit_amount, conditions.currency)}</Descriptions.Item>
      <Descriptions.Item label="最长账期">{conditions.max_payment_days ?? '—'} 天</Descriptions.Item>
      <Descriptions.Item label="最低交付前收款">{percentage(conditions.min_prepayment_ratio)}</Descriptions.Item>
      <Descriptions.Item label="允许付款方式">{(conditions.allowed_payment_methods || []).map(paymentMethodLabel).join('、') || '—'}</Descriptions.Item>
      <Descriptions.Item label="VMI/JIT">{conditions.allow_vmi_jit ? '允许' : '不允许'}</Descriptions.Item>
      <Descriptions.Item label="额度占用数据">{decision.exposure_snapshot_at_review ? '已读取 CRM/ERP 数据' : '未提供数据'}</Descriptions.Item>
    </Descriptions>}
  </Card>
}

const versionValue = (value: any) => {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  return String(value)
}

const riskTags = (items: string[] | undefined, color: string) => items?.length
  ? <Space wrap size={[4, 4]}>{items.map(item => <Tag color={color} key={item}>{item}</Tag>)}</Space>
  : <Text type="secondary">无</Text>

export function VersionEffectSummary({ comparison }: { comparison?: VersionComparison | null }) {
  if (!comparison) return null
  const counts = comparison.risk_counts || { baseline: 0, current: 0, resolved: comparison.resolved_risks?.length || 0, new: comparison.new_risks?.length || 0, persisting: comparison.persisting_risks?.length || 0 }
  const changedFields = (comparison.field_changes || []).filter(item => item.changed)
  const currentCreditBlocked = (comparison.new_risks || []).some(item => item.startsWith('CREDIT_')) || String(comparison.current?.summary?.overall_level || '').includes('信用审核条件不符')
  return <Card className="version-effect-summary" size="small" title={<Space><ArrowRightOutlined />修订效果摘要</Space>}>
    <Alert type={currentCreditBlocked ? 'error' : counts.resolved > 0 ? 'success' : 'info'} showIcon message={currentCreditBlocked ? '修订后仍有不符合信用审核条件的问题' : counts.resolved > 0 ? '修订已消除部分历史风险，请继续核对剩余放行条件' : '已完成版本对比，请继续核对当前版本的放行条件'} description={`${comparison.baseline?.filename || comparison.baseline_job_id} → ${comparison.current?.filename || comparison.job_id}`} />
    <div className="version-effect-metrics">
      <div><span>基线风险</span><strong>{counts.baseline}</strong></div>
      <div><span>当前风险</span><strong className={counts.current ? 'is-danger' : 'is-success'}>{counts.current}</strong></div>
      <div><span>已解决风险</span><strong className="is-success">{counts.resolved}</strong></div>
      <div><span>仍存在风险</span><strong className={counts.persisting ? 'is-warning' : 'is-success'}>{counts.persisting}</strong></div>
    </div>
    <div className="version-effect-section"><Text strong>商业字段变化</Text>{changedFields.length ? <div className="version-field-changes">{changedFields.map(item => <div key={item.key}><span>{item.label}</span><Text delete={false}>{versionValue(item.baseline)}</Text><ArrowRightOutlined /><Text strong>{versionValue(item.current)}</Text></div>)}</div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未发现结构化字段变化" />}</div>
    <div className="version-effect-section"><Text strong>变更条款</Text>{comparison.changed_clauses?.length ? <Space wrap size={[4, 4]} className="version-clause-changes">{comparison.changed_clauses.map(item => <Tag color="blue" key={item}>{item}</Tag>)}</Space> : <Text type="secondary">未识别到条款级变化</Text>}</div>
    <div className="version-effect-risk-grid">
      <div><Text strong>已消除</Text>{riskTags(comparison.resolved_risks, 'green')}</div>
      <div><Text strong>新增</Text>{riskTags(comparison.new_risks, 'red')}</div>
      <div><Text strong>持续</Text>{riskTags(comparison.persisting_risks, 'orange')}</div>
    </div>
    {comparison.review_scope?.mode === 'incremental' && <Text type="secondary" className="version-effect-scope">部分复审：变更条款 {comparison.review_scope.changed_clause_ids?.length || 0} 条，连同上下文条款 {comparison.review_scope.context_clause_ids?.length || 0} 条一起检查。</Text>}
  </Card>
}
