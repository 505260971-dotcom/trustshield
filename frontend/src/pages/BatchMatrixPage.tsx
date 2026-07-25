import { useEffect, useState } from 'react'
import { Card, Empty, Table, Tag, Typography } from 'antd'
import { api } from '../services/api'
import { fmtTime } from '../components/common'

export default function BatchMatrixPage() {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => { api.batchMatrix().then(x => setItems(x.items)).finally(() => setLoading(false)) }, [])
  const columns = [
    { title: '合同', dataIndex: 'filename', width: 260 },
    { title: '总体结论', dataIndex: 'overall_level', width: 150, render: (value:string) => <Tag color={value?.startsWith('阻断') ? 'red' : value?.startsWith('需') ? 'orange' : 'green'}>{value || '处理中'}</Tag> },
    { title: '高风险', dataIndex: 'high', width: 90, render:(value:number) => <Tag color={value ? 'red' : 'default'}>{value || 0}</Tag> },
    { title: '中风险', dataIndex: 'mid', width: 90 },
    { title: '优先级', dataIndex: 'priority', width: 90 },
    { title: '截止时间', dataIndex: 'due_at', width: 150, render: fmtTime },
    ...Array.from({ length: 16 }, (_, index) => {
      const ruleId = `R${String(index + 1).padStart(2, '0')}`
      return { title: ruleId, key: ruleId, width: 68, align: 'center' as const, render: (_:unknown, row:any) => row.rule_ids?.includes(ruleId) ? <Tag color="red">命中</Tag> : <span style={{color:'#bfbfbf'}}>—</span> }
    }),
  ]
  return <Card title="批量审查风险矩阵"><Typography.Paragraph type="secondary">每行是一份合同，R01-R16 分别对应销售合同底线；可横向比较规则命中、阻断风险、优先级和截止时间。</Typography.Paragraph>{items.length ? <Table rowKey="id" loading={loading} columns={columns} dataSource={items} pagination={{pageSize:12}} scroll={{x:2200}} /> : <Empty description="尚无已审查合同" />}</Card>
}
