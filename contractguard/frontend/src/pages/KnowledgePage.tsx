import { useEffect, useState } from 'react'
import { Empty, List, Select, Space, Spin, Tag, Typography } from 'antd'
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
  return <>
    <div className="page-intro"><div><Typography.Title level={3}>风险条款知识库</Typography.Title><Text type="secondary">仅沉淀已被人工采纳或编辑后采纳的脱敏风险案例和推荐改写。</Text></div><Select allowClear placeholder="按规则筛选" style={{ width: 220 }} value={ruleId || undefined} options={rules.map(x => ({ value: x.id, label: `${x.id} ${x.baseline}` }))} onChange={value => { setRuleId(value || ''); load(value || '') }} /></div>
    {loading ? <Spin /> : items.length ? <List bordered dataSource={items} renderItem={item => <List.Item><List.Item.Meta avatar={<Tag color="blue">{item.rule_id}</Tag>} title={<Space><Text strong>{item.source_ref || '历史条款'}</Text><Tag color="green">{item.outcome}</Tag></Space>} description={<><Text>证据：{item.evidence || '—'}</Text><br /><Text>推荐改写：{item.suggested_text || '—'}</Text><br /><Text type="secondary">{item.business_type || '一般'} · {fmtTime(item.created_at)}</Text></>} /></List.Item>} /> : <Empty image={<BookOutlined style={{fontSize:48}} />} description="尚无已人工采纳的脱敏风险案例" />}
  </>
}
