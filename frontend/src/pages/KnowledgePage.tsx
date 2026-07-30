import { useEffect, useState } from 'react'
import { Card, Empty, List, Select, Space, Spin, Tag, Typography } from 'antd'
import { BookOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { KnowledgeItem, RuleItem } from '../types'
import { fmtTime } from '../components/common'

const { Text } = Typography

export default function KnowledgePage() {
  const [rules, setRules] = useState<RuleItem[]>([])
  const [items, setItems] = useState<KnowledgeItem[]>([])
  const [ruleId, setRuleId] = useState('')
  const [loading, setLoading] = useState(true)
  const load = async (value = ruleId) => {
    setLoading(true)
    try { const result = await api.knowledge(value); setItems(result.items) } finally { setLoading(false) }
  }
  useEffect(() => { api.rules().then(x => setRules(x.rules)); load('') }, [])
  const coveredRules=new Set(items.map(item=>item.rule_id)).size
  return <div className="role-page knowledge-page">
    <section className="page-hero page-hero-light">
      <div><span className="section-kicker">APPROVED KNOWLEDGE</span><Typography.Title level={2}>风险条款知识库</Typography.Title><Typography.Paragraph>仅沉淀人工采纳或编辑后采纳的脱敏案例。它用于辅助理解历史风险处置，不替代当前案件的规则判断。</Typography.Paragraph></div>
      <div className="page-hero-actions"><Select allowClear placeholder="按规则筛选" style={{ width: 250 }} value={ruleId || undefined} options={rules.map(x => ({ value: x.id, label: `${x.id} ${x.baseline}` }))} onChange={value => { setRuleId(value || ''); load(value || '') }} /></div>
    </section>
    <section className="compact-metrics" aria-label="知识库概览">
      <div className="compact-metric"><span className="compact-metric-icon"><BookOutlined/></span><div><small>可复用案例</small><strong>{items.length}</strong><em>当前筛选范围内</em></div></div>
      <div className="compact-metric metric-attention"><span className="compact-metric-icon"><BookOutlined/></span><div><small>覆盖规则</small><strong>{coveredRules}</strong><em>已有可回溯案例</em></div></div>
      <div className="compact-metric"><span className="compact-metric-icon"><BookOutlined/></span><div><small>规则目录</small><strong>{rules.length}</strong><em>可作为筛选条件</em></div></div>
    </section>
    <Card className="page-data-card knowledge-list-card" title={<div><span className="card-kicker">REFERENCE CASES</span><span>已采纳案例</span></div>}>
      {loading ? <div className="page-loading"><Spin /> <Text type="secondary">正在整理脱敏案例…</Text></div> : items.length ? <List dataSource={items} renderItem={item => <List.Item><List.Item.Meta avatar={<Tag color="blue">{item.rule_id}</Tag>} title={<Space wrap><Text strong>{item.source_ref || '历史条款'}</Text><Tag color="green">{item.outcome}</Tag><Tag>{item.business_type || '一般'}</Tag></Space>} description={<div className="knowledge-case-copy"><div><b>证据</b>{item.evidence || '—'}</div><div><b>推荐改写</b>{item.suggested_text || '—'}</div><Text type="secondary">沉淀时间：{fmtTime(item.created_at)}</Text></div>} /></List.Item>} /> : <Empty image={<BookOutlined style={{fontSize:48}} />} description="尚无已人工采纳的脱敏风险案例" />}
    </Card>
  </div>
}
