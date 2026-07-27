import { useEffect, useState } from 'react'
import { Badge, Button, Card, Col, Empty, List, Row, Space, Statistic, Tag, Typography, message } from 'antd'
import { ClockCircleOutlined, FileAddOutlined, InboxOutlined, RightOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { CaseCenterItem, WorkItem } from '../types'
import { fmtTime } from '../components/common'

const { Text } = Typography
const taskLabel:Record<string,string>={credit_required:'信审前置',document_required:'上传文件',legal_review:'信用审核专员复核',material:'待补材料',approval:'分级审批'}

export default function WorkbenchPage({onCreate,onOpenCase}:{onCreate:()=>void;onOpenCase:(id:string)=>void}){
  const [tasks,setTasks]=useState<WorkItem[]>([]); const [cases,setCases]=useState<CaseCenterItem[]>([]); const [loading,setLoading]=useState(true)
  const load=async()=>{setLoading(true);try{const [t,c]=await Promise.all([api.workItems(),api.caseCenter('mine')]);setTasks(t.items);setCases(c.items)}catch(e:any){message.error(e.message||'工作台加载失败')}finally{setLoading(false)}}
  useEffect(()=>{load()},[])
  const urgent=tasks.filter(t=>t.priority==='urgent'||t.priority==='high').length
  return <>
    <div className="page-intro"><div><Typography.Title level={3}>我的工作台</Typography.Title><Text type="secondary">所有需要你处理的合同、信审前置事项、补件与审批，集中在这里。</Text></div><Button type="primary" icon={<FileAddOutlined/>} onClick={onCreate}>发起合同申请</Button></div>
    <Row gutter={[16,16]}>
      <Col xs={24} md={8}><Card><Statistic title="待我处理" value={tasks.length} prefix={<InboxOutlined/>}/></Card></Col>
      <Col xs={24} md={8}><Card><Statistic title="高优先级" value={urgent} prefix={<Badge status="error"/>} valueStyle={{color:urgent?'#cf1322':undefined}}/></Card></Col>
      <Col xs={24} md={8}><Card><Statistic title="我发起的案件" value={cases.length} prefix={<ClockCircleOutlined/>}/></Card></Col>
    </Row>
    <Row gutter={[16,16]} style={{marginTop:16}}>
      <Col xs={24} xl={15}><Card title="待我处理" extra={<Button size="small" onClick={load}>刷新</Button>} loading={loading}>
        {tasks.length?<List dataSource={tasks} renderItem={task=><List.Item actions={[<Button key="open" type="link" onClick={()=>onOpenCase(task.case_id)}>查看案件 <RightOutlined/></Button>]}>
          <List.Item.Meta title={<Space><Tag color={task.priority==='urgent'?'red':task.priority==='high'?'orange':'blue'}>{taskLabel[task.task_type]||task.task_type}</Tag><Text strong>{task.title}</Text></Space>} description={<><Text>{task.customer_name} · {task.filename||'尚未上传合同'}</Text><br/><Text type="secondary">{task.detail||'—'}　{task.due_at?`截止 ${fmtTime(task.due_at)}`:'未设置截止时间'}</Text></>}/>
        </List.Item>}/>:<Empty description="暂时没有待办"/>}
      </Card></Col>
      <Col xs={24} xl={9}><Card title="我最近发起的案件" loading={loading}>
        {cases.length?<List size="small" dataSource={cases.slice(0,6)} renderItem={item=><List.Item actions={[<Button key="open" type="link" onClick={()=>onOpenCase(item.case_id)}>进入</Button>]}><List.Item.Meta title={<Text strong>{item.customer_name}</Text>} description={<>{item.filename||'待上传合同'}<br/><Tag color={item.current_stage==='ready_to_sign'?'green':item.current_stage==='awaiting_business'?'orange':'blue'}>{item.current_stage}</Tag> <Text type="secondary">{item.open_tasks} 项待办</Text></>}/></List.Item>}/>:<Empty description="还没有合同案件"/>}
      </Card></Col>
    </Row>
  </>
}
