import { useState } from 'react'
import { Button, Card, Input, Space, Tag, Typography } from 'antd'
import { ArrowRightOutlined, RobotOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import type { CreditConditions, Report, Risk } from '../types'

const { Text } = Typography

type AssistantMessage = { id: number; role: 'user' | 'assistant'; text: string; risks?: Risk[] }

const riskKey = (risk: Risk) => risk.finding_id || `${risk.clause_id}-${risk.rule_id}`
const money = (value: unknown, currency = 'CNY') => {
  const parsed = Number(String(value ?? '').replace(/,/g, ''))
  return Number.isFinite(parsed) && value !== '' && value !== null && value !== undefined
    ? `${parsed.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${currency}`
    : '—'
}

export default function CaseReviewAssistant({ report, risks, onSelectRisk }: { report: Report; risks: Risk[]; onSelectRisk?: (risk: Risk) => void }) {
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<AssistantMessage[]>([
    { id: 1, role: 'assistant', text: '我只参考当前合同报告、已生效的信用审核条件、规则依据和审查状态。你可以问我“为什么不能放行”“合同关键条件是什么”或“下一步怎么处理”。' },
  ])
  const [nextId, setNextId] = useState(2)
  const decision = report.credit_decision
  const conditions: Partial<CreditConditions> = decision?.conditions || {}
  const fields = report.contract_fields || {}
  const creditRisks = risks.filter(item => item.rule_id?.startsWith('CREDIT_'))
  const pendingRisks = risks.filter(item => !item.action_status || item.action_status === 'pending')

  const answer = (raw: string): AssistantMessage => {
    const query = raw.trim()
    const normalized = query.toLowerCase()
    if (/阻断|为什么|原因|越界/.test(normalized)) {
      if (creditRisks.length) {
        return {
          id: nextId + 1, role: 'assistant',
          text: `当前不能签约，因为发现 ${creditRisks.length} 项信用审核条件不符。问题来自客户已生效的信用审核版本 V${decision?.version || '—'}，不能在合同端忽略，也不能通过普通例外审批绕过。`,
          risks: creditRisks.slice(0, 6),
        }
      }
      return { id: nextId + 1, role: 'assistant', text: report.summary?.overall_level?.includes('阻断') ? '当前报告存在合同底线问题，请打开风险清单查看对应规则和放行条件。' : '当前报告没有发现可见的信用审核条件不符；如果仍不能推进，请检查待人工确认、补充材料和条款例外审批。', risks: pendingRisks.slice(0, 5) }
    }
    if (/条件|金额|账期|预付款|付款|vmi|jit|交付/.test(normalized)) {
      return {
        id: nextId + 1, role: 'assistant',
        text: `当前合同金额为 ${money(fields.total_amount, fields.currency || conditions.currency)}；已生效信用审核额度上限为 ${money(conditions.max_credit_amount, conditions.currency)}；最长账期 ${conditions.max_payment_days ?? '—'} 天；交付前最低收款比例为 ${conditions.min_prepayment_ratio ?? '—'}%；允许付款方式为 ${(conditions.allowed_payment_methods || []).join('、') || '未提供'}；VMI/JIT ${conditions.allow_vmi_jit ? '允许' : '不允许'}。`,
        risks: creditRisks.slice(0, 6),
      }
    }
    if (/风险|未闭环|尚未处理|还有|剩余/.test(normalized)) {
      if (!pendingRisks.length) return { id: nextId + 1, role: 'assistant', text: '当前没有尚未记录处理结果的可见风险。仍请核对待人工确认和审批条件，再决定是否导出或归档。' }
      return { id: nextId + 1, role: 'assistant', text: `当前还有 ${pendingRisks.length} 项可见风险或待处理事项。建议先处理高风险，再检查待补材料和条款例外审批。`, risks: pendingRisks.slice(0, 6) }
    }
    if (/下一步|怎么办|处理|推进|签约/.test(normalized)) {
      if (creditRisks.length) return { id: nextId + 1, role: 'assistant', text: '下一步：调整合同金额、账期、收款比例、付款方式或交付模式，使其符合已生效的信用审核条件；如果业务确实需要放宽条件，应先发起新的信用审核版本，再重新审查合同。', risks: creditRisks.slice(0, 6) }
      if (pendingRisks.length) return { id: nextId + 1, role: 'assistant', text: '下一步：逐条处理待处理风险，并补齐必要材料或例外审批。当前报告的风险处理、审批和导出状态都会记录在案件中。', risks: pendingRisks.slice(0, 6) }
      return { id: nextId + 1, role: 'assistant', text: '当前没有可见的风险放行条件问题。请继续核对案件待办和审批状态，完成后再导出修订建议稿或归档。' }
    }
    return { id: nextId + 1, role: 'assistant', text: '我目前只回答当前案件范围内的问题：合同商业条件、信用审核条件、无法放行的原因、风险处理和下一步流程。请换一种问法，或点击下方快捷问题。' }
  }

  const ask = (value: string) => {
    const query = value.trim()
    if (!query) return
    const result = answer(query)
    setMessages(current => [...current, { id: nextId, role: 'user', text: query }, result])
    setNextId(id => id + 2)
    setQuestion('')
  }

  return <Card className="case-review-assistant" size="small" title={<Space><RobotOutlined />案件审查助理 <Tag color="blue">仅回答本案</Tag></Space>}>
    <div className="case-review-assistant-note"><SafetyCertificateOutlined /><Text type="secondary">仅根据当前合同、信用审核记录、规则依据和案件状态回答，不回答与本案无关的泛化法律问题。</Text></div>
    <div className="case-review-assistant-messages">
      {messages.map(item => <div className={`case-review-assistant-message is-${item.role}`} key={item.id}>
        <span className="case-review-assistant-avatar">{item.role === 'assistant' ? <RobotOutlined /> : '我'}</span>
        <div><Text>{item.text}</Text>{item.risks?.length ? <div className="case-review-assistant-sources"><Text type="secondary">相关依据：</Text>{item.risks.map(risk => <Button key={riskKey(risk)} type="link" size="small" icon={<ArrowRightOutlined />} onClick={() => onSelectRisk?.(risk)}>{risk.rule_id} · {risk.clause_id || '当前条款'}</Button>)}</div> : null}</div>
      </div>)}
    </div>
    <Space wrap className="case-review-assistant-chips">
      {['为什么不能放行？', '合同关键条件是什么？', '还有哪些风险尚未处理？', '下一步怎么处理？'].map(item => <Button key={item} size="small" onClick={() => ask(item)}>{item}</Button>)}
    </Space>
    <Input.Search value={question} onChange={event => setQuestion(event.target.value)} onSearch={ask} enterButton="提问" placeholder="输入当前案件的问题，例如：为什么账期不符合信用审核条件？" />
  </Card>
}
