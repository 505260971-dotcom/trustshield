import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Badge, Button, Card, Empty, Input, List, Space, Spin, Tag, Typography, message } from 'antd'
import { CheckCircleOutlined, ClockCircleOutlined, EditOutlined, FileAddOutlined, FolderOpenOutlined, RightOutlined, SafetyCertificateOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { WorkboxItem } from '../types'
import { fmtTime } from '../components/common'

const { Text, Title } = Typography
type Bucket='todo'|'in_progress'|'draft'|'done'
const copy:Record<Bucket,{eyebrow:string;title:string;description:string;empty:string;action:string;icon:ReactNode}>={
  todo:{eyebrow:'MY ACTIONS',title:'待办',description:'只显示已经轮到你、需要你立即作出处理的信审与合同事项。',empty:'当前没有待办，流程正在由其他岗位或系统推进。',action:'处理',icon:<UnorderedListOutlined/>},
  in_progress:{eyebrow:'FLOW TRACKING',title:'进行中',description:'查看我发起或参与、但当前正在由其他岗位或系统推进的业务。',empty:'当前没有进行中的业务。',action:'查看进度',icon:<ClockCircleOutlined/>},
  draft:{eyebrow:'UNSUBMITTED',title:'草稿',description:'尚未进入正式流转的信审申请和合同申请；在这里补齐信息后再提交。',empty:'没有草稿。',action:'继续编辑',icon:<EditOutlined/>},
  done:{eyebrow:'MY RECORDS',title:'已办',description:'我已完成的审核、补件、审批与确认，保留为可追溯记录。',empty:'暂无已办记录。',action:'查看记录',icon:<CheckCircleOutlined/>},
}
const stageText:Record<string,string>={draft:'草稿',awaiting_credit:'等待有效信审',ai_review:'系统审查中',legal_review:'审核员复核',awaiting_business:'待业务补件',approval:'待主管审批',final_approval:'待最终审批',ready_to_sign:'可签约',archived:'已归档',returned_to_reviewer:'退回审核专员',returned_to_business:'待业务补充',pending_director:'待主管复核',pending_final:'待最终审批',approved:'已生效',rejected:'已拒绝',superseded:'历史版本'}
const stageTone=(stage:string)=>['approved','ready_to_sign','archived'].includes(stage)?'green':['awaiting_business','awaiting_credit','returned_to_business','returned_to_reviewer'].includes(stage)?'orange':['rejected','cancelled'].includes(stage)?'red':'blue'

type Props={bucket:Bucket;onOpenCase:(id:string)=>void;onOpenCredit:(id:string)=>void;onCreateContract:()=>void;onCreateCredit:()=>void;canCreateContract:boolean;canCreateCredit:boolean}
export default function WorkboxPage({bucket,onOpenCase,onOpenCredit,onCreateContract,onCreateCredit,canCreateContract,canCreateCredit}:Props){
  const [items,setItems]=useState<WorkboxItem[]>([]);const [loading,setLoading]=useState(true);const [keyword,setKeyword]=useState('')
  const config=copy[bucket]
  const load=async()=>{setLoading(true);try{setItems((await api.workbox(bucket)).items||[])}catch(e:any){message.error(e.message||'工作箱加载失败')}finally{setLoading(false)}}
  useEffect(()=>{load()},[bucket])
  const shown=useMemo(()=>{const q=keyword.trim().toLowerCase();return q?items.filter(item=>`${item.customer_name} ${item.filename||''} ${item.title}`.toLowerCase().includes(q)):items},[items,keyword])
  const open=(item:WorkboxItem)=>item.source_type==='credit'?onOpenCredit(item.target_id):onOpenCase(item.target_id)
  return <div className={'workbox-page workbox-'+bucket}>
    <section className="workbox-hero"><div><span className="section-kicker">{config.eyebrow}</span><Title level={2}>{config.icon} {config.title}</Title><Typography.Paragraph>{config.description}</Typography.Paragraph></div><Space wrap>{canCreateCredit&&bucket==='draft'&&<Button icon={<SafetyCertificateOutlined/>} onClick={onCreateCredit}>新建信审申请</Button>}{canCreateContract&&bucket==='draft'&&<Button type="primary" icon={<FileAddOutlined/>} onClick={onCreateContract}>新建合同申请</Button>}<Button onClick={load}>刷新</Button></Space></section>
    <Card className="workbox-list-card" title={<Space><FolderOpenOutlined/><span>{config.title}事项</span><Badge count={shown.length} showZero color="#1677ff"/></Space>} extra={<Input.Search allowClear placeholder="搜索客户或文件" value={keyword} onChange={event=>setKeyword(event.target.value)} style={{width:250}}/>}>
      {loading?<div className="page-loading"><Spin/><Text type="secondary">正在整理{config.title}事项…</Text></div>:shown.length?<List className="workbox-list" dataSource={shown} renderItem={item=><List.Item actions={[<Button key="open" type={bucket==='todo'?'primary':'link'} onClick={()=>open(item)}>{config.action} {bucket==='todo'&&<RightOutlined/>}</Button>]}><List.Item.Meta avatar={<span className={'workbox-kind kind-'+item.source_type}>{item.source_type==='credit'?<SafetyCertificateOutlined/>:<FolderOpenOutlined/>}</span>} title={<Space wrap><Text strong>{item.customer_name}</Text><Tag color={item.source_type==='credit'?'cyan':'blue'}>{item.kind_label}</Tag><Tag color={stageTone(item.current_stage)}>{stageText[item.current_stage]||item.current_stage}</Tag></Space>} description={<div className="workbox-item-copy"><Text strong>{item.title}</Text><Text>{item.filename||item.detail||'—'}</Text><Text type="secondary">{item.action_hint}</Text><Text type="secondary">{bucket==='done'?'完成时间':'最近更新'}：{fmtTime(item.completed_at||item.updated_at||item.created_at||0)}</Text></div>}/></List.Item>}/>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={config.empty}/>} 
    </Card>
  </div>
}
