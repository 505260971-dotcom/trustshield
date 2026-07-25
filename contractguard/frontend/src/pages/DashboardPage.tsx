import { useEffect, useState } from 'react'
import { Button, Card, Col, Empty, Progress, Row, Space, Spin, Statistic, Typography } from 'antd'
import { AuditOutlined, ClockCircleOutlined, FileAddOutlined, FileSearchOutlined, TeamOutlined, UnorderedListOutlined, WarningOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { Stats } from '../types'

const { Text } = Typography

export default function DashboardPage ({ refreshKey, onCreate, onCases }: { refreshKey: number; onCreate:()=>void; onCases:()=>void }) {
  const [s, setS] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const load = async () => { setLoading(true); try { setS(await api.stats()) } finally { setLoading(false) } }
  useEffect(() => { load() }, [refreshKey])

  if (loading) return <div style={{textAlign:'center',padding:60}}><Spin tip="加载中…"/></div>
  if (!s) return <Empty/>
  const topRules = Object.entries(s.rules_freq || {})
  const maxFreq = Math.max(1, ...topRules.map(([,v])=>v as number))
  return (
    <>
      <div className="page-intro"><div><Typography.Title level={3}>合同评审协作台</Typography.Title><Text type="secondary">提交合同、分配法务、处理风险并留存完整处置记录。</Text></div><Space><Button icon={<UnorderedListOutlined/>} onClick={onCases}>查看案件</Button><Button type="primary" icon={<FileAddOutlined/>} onClick={onCreate}>发起评审</Button></Space></div>
      <Row gutter={[16,16]}>
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="我的待办" value={s.my_open} prefix={<AuditOutlined/>}/></Card></Col>
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="待领取案件" value={s.unassigned} prefix={<TeamOutlined/>}/></Card></Col>
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="48 小时内到期" value={s.due_soon} prefix={<ClockCircleOutlined/>} valueStyle={{color:s.due_soon?'#d46b08':undefined}}/></Card></Col>
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="阻断级结论" value={s.blocked} prefix={<WarningOutlined/>} valueStyle={{color:'#cf1322'}}/></Card></Col>
      </Row>
      <Row gutter={16} style={{marginTop:16}}>
        <Col xs={24} xl={10}><Card title="团队审查概览">
          <Row><Col span={8}><Statistic title="已发起" value={s.total} prefix={<FileSearchOutlined/>}/></Col><Col span={8}><Statistic title="已完成 AI 审查" value={s.done} valueStyle={{color:'#389e0d'}}/></Col><Col span={8}><Statistic title="高风险条款" value={s.high} valueStyle={{color:'#cf1322'}}/></Col></Row>
          <div style={{height:18}}/><Text type="secondary">中风险条款累计 {s.mid} 条；所有风险处置、导出及审批操作会写入审计日志。</Text>
        </Card></Col>
        <Col xs={24} xl={14}><Card title="高频命中合同底限 Top 10">
          {topRules.length ? topRules.map(([rid, v])=> (
            <div key={rid} style={{marginBottom:8}}>
              <Text style={{width:60, display:'inline-block'}}>{rid}</Text>
              <Progress percent={Math.round((v as number)/maxFreq*100)} format={()=> `${v} 次`} style={{width:'calc(100% - 70px)', display:'inline-block'}}/>
            </div>)) : <Empty description="暂无数据"/>}
        </Card></Col>
      </Row>
    </>
  )
}
