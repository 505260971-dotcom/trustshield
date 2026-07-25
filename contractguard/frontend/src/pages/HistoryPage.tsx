import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Space, Popconfirm, message, Typography, Empty, Spin } from 'antd'
import { DeleteOutlined, EyeOutlined, ReloadOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { HistoryItem } from '../types'
import { sevColor } from '../types'
import { fmtTime } from '../components/common'

const { Text } = Typography

export default function HistoryPage ({ openId, refreshKey }: {
  openId: (id: string)=>void; refreshKey: number
}) {
  const [items, setItems] = useState<HistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const load = async () => {
    setLoading(true)
    try { setItems((await api.history(100, 0)).items) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [refreshKey])

  const del = async (id: string) => {
    await api.deleteHistory(id); message.success('已删除'); load()
  }

  const sev = (it: HistoryItem) => (it.high>0?'high':it.mid>0?'mid':'low')
  const cols = [
    { title: '文件名', dataIndex: 'filename', render:(v:string, r:HistoryItem)=>
      <a onClick={()=>openId(r.id)}><b>{v||'-'}</b></a> },
    { title: '总体结论', dataIndex: 'overall_level', width: 170, render:(v:string, r:HistoryItem)=>
      <Tag color={sevColor[sev(r)]} style={{margin:0}}>{v||'审查中…'}</Tag> },
    { title: '我方', dataIndex:'our_party', width: 80 },
    { title: '业务', dataIndex:'business_type', width: 90 },
    { title: '条款', dataIndex:'n_clauses', width: 70, align:'center' as const },
    { title: '风险', dataIndex:'n_risks', width: 70, align:'center' as const,
      render:(v:number)=> <Text type={v>0?'danger':undefined}>{v}</Text> },
    { title: '高', dataIndex:'high', width: 60, align:'center' as const,
      render:(v:number)=> v ? <Tag color="red" style={{margin:0}}>{v}</Tag> : <Text type="secondary">0</Text> },
    { title: '中', dataIndex:'mid', width: 60, align:'center' as const,
      render:(v:number)=> v ? <Tag color="orange" style={{margin:0}}>{v}</Tag> : <Text type="secondary">0</Text> },
    { title: '脱敏', dataIndex:'masked_entities', width: 70, align:'center' as const },
    { title: '时间', dataIndex:'created_at', width: 150, render:(v:number)=> fmtTime(v) },
    { title: '操作', width: 130, render:(_:any, r:HistoryItem)=>
      <Space>
        <Button size="small" type="link" icon={<EyeOutlined/>} onClick={()=>openId(r.id)} disabled={r.status!=='done'}>查看</Button>
        <Popconfirm title="确认删除此记录？" onConfirm={()=>del(r.id)}>
          <Button size="small" type="link" danger icon={<DeleteOutlined/>}>删除</Button>
        </Popconfirm>
      </Space> }
  ]
  return (
    <Card title={<Space><ReloadOutlined/> 审查历史 · {items.length} 条</Space>} extra={<Button onClick={load} icon={<ReloadOutlined/>}>刷新</Button>}>
      {loading ? <div style={{textAlign:'center',padding:40}}><Spin/></div> :
       items.length ? <Table size="small" rowKey="id" columns={cols} dataSource={items} pagination={{pageSize:12}}/>
       : <Empty description="暂无历史记录，去「合同审查」上传第一份合同"/>}
    </Card>
  )
}
