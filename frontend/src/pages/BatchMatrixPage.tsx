import { useEffect, useState } from 'react'
import { Button, Card, Empty, Space, Table, Tag, Typography, message } from 'antd'
import { ReloadOutlined, SafetyCertificateOutlined, WarningOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import { fmtTime } from '../components/common'

export default function BatchMatrixPage() {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const load=async()=>{setLoading(true);try{setItems((await api.batchMatrix()).items)}catch(e:any){message.error(e.message||'风险矩阵加载失败')}finally{setLoading(false)}}
  useEffect(() => { load() }, [])
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
  const blocked=items.filter(item=>item.overall_level?.startsWith('阻断')).length
  const attention=items.filter(item=>(item.high||0)>0).length
  const rulesHit=items.reduce((sum,item)=>sum+(item.rule_ids?.length||0),0)
  return <div className="role-page matrix-page">
    <section className="page-hero page-hero-light">
      <div><span className="section-kicker">RISK OVERVIEW</span><Typography.Title level={2}>风险矩阵</Typography.Title><Typography.Paragraph>将已审查合同放在同一尺度下比较。先关注阻断风险与高风险合同，再沿 R01–R16 回看具体的底线规则命中。</Typography.Paragraph></div>
      <div className="page-hero-actions"><Tag color="blue">R01–R16 合同底线规则</Tag><Button icon={<ReloadOutlined/>} onClick={load}>刷新矩阵</Button></div>
    </section>
    <section className="compact-metrics" aria-label="风险矩阵概览">
      <div className="compact-metric"><span className="compact-metric-icon"><SafetyCertificateOutlined/></span><div><small>已审查合同</small><strong>{items.length}</strong><em>进入横向对比范围</em></div></div>
      <div className="compact-metric metric-danger"><span className="compact-metric-icon"><WarningOutlined/></span><div><small>阻断级合同</small><strong>{blocked}</strong><em>须优先处理或上报</em></div></div>
      <div className="compact-metric metric-warning"><span className="compact-metric-icon"><WarningOutlined/></span><div><small>含高风险合同</small><strong>{attention}</strong><em>需要逐条核验</em></div></div>
      <div className="compact-metric"><span className="compact-metric-icon"><SafetyCertificateOutlined/></span><div><small>规则命中数</small><strong>{rulesHit}</strong><em>同一合同可命中多条</em></div></div>
    </section>
    <Card className="page-data-card" title={<div><span className="card-kicker">CROSS-CASE VIEW</span><span>合同风险对比</span></div>} extra={<Space><Tag color="red">阻断</Tag><Tag color="orange">需关注</Tag><Typography.Text type="secondary">横向滚动可查看全部规则</Typography.Text></Space>}>
      {items.length ? <Table rowKey="id" loading={loading} columns={columns} dataSource={items} pagination={{pageSize:12,showSizeChanger:false}} scroll={{x:2200}} /> : <Empty description="尚无已审查合同" />}
    </Card>
  </div>
}
