import { useEffect, useMemo, useState } from 'react'
import { Button, Card, DatePicker, Empty, message, Select, Space, Table, Tag, Tooltip } from 'antd'
import { EyeOutlined, ReloadOutlined, UserAddOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api } from '../services/api'
import { useAuth } from '../context/AuthContext'
import type { CaseItem, TeamMember } from '../types'
import { fmtTime } from '../components/common'

const statusLabels:Record<string,string>={running:'AI 审查中',pending_review:'待信用审核专员复核',in_review:'信用审核处理中',returned:'待补充材料',approved:'已确认',closed:'已关闭',failed:'审查失败'}
const statusColor:Record<string,string>={running:'processing',pending_review:'gold',in_review:'blue',returned:'orange',approved:'green',closed:'default',failed:'red'}
const priorityColor:Record<string,string>={low:'default',normal:'blue',high:'orange',urgent:'red'}
const priorityLabel:Record<string,string>={low:'低',normal:'普通',high:'高',urgent:'紧急'}
const workflowOptions=Object.entries(statusLabels).filter(([value])=>!['running','failed'].includes(value)).map(([value,label])=>({value,label}))

export default function CaseBoardPage({openId,refreshKey}:{openId:(id:string)=>void;refreshKey:number}){
 const {user}=useAuth(); const [items,setItems]=useState<CaseItem[]>([]);const [members,setMembers]=useState<TeamMember[]>([]);const [loading,setLoading]=useState(true);const [filter,setFilter]=useState('open')
 const canManage=['admin','reviewer','director'].includes(user?.role||'')
 const load=async()=>{setLoading(true);try{const [cases,reviewers]=await Promise.all([api.cases(),api.reviewers().catch(()=>({items:[]}))]);setItems(cases.items);setMembers(reviewers.items)}catch(e:any){message.error(`加载案件失败：${e.message||e}`)}finally{setLoading(false)}}
 useEffect(()=>{load()},[refreshKey])
 const update=async(jobId:string,body:any)=>{try{await api.updateCase(jobId,body);message.success('案件已更新');load()}catch(e:any){message.error(`更新失败：${e.message||e}`)}}
 const visible=useMemo(()=>filter==='all'?items:filter==='mine'?items.filter(x=>x.assigned_to===user?.id||x.requester_name===user?.display_name):items.filter(x=>!['approved','closed','failed'].includes(x.workflow_status)),[items,filter,user])
 const columns=[
  {title:'合同 / 案件',dataIndex:'filename',render:(v:string,r:CaseItem)=><Button type="link" onClick={()=>openId(r.job_id)} style={{padding:0,textAlign:'left'}}><b>{v}</b><br/><span className="case-id">{r.case_id}</span></Button>},
  {title:'优先级',dataIndex:'priority',width:84,render:(v:string)=><Tag color={priorityColor[v]}>{priorityLabel[v]}</Tag>},
  {title:'流程',dataIndex:'workflow_status',width:128,render:(v:string)=><Tag color={statusColor[v]}>{statusLabels[v]||v}</Tag>},
  {title:'AI 结论',dataIndex:'overall_level',width:130,render:(v:string,r:CaseItem)=><Tag color={r.high?'red':r.mid?'orange':'green'}>{v||'处理中'}</Tag>},
  {title:'负责人',width:180,render:(_:any,r:CaseItem)=>canManage?<Select size="small" value={r.assigned_to||undefined} placeholder="待领取" allowClear style={{width:155}} options={members.map(m=>({value:m.id,label:m.display_name}))} onChange={v=>update(r.job_id,{assigned_to:v||''})}/>:r.assignee_name||'待领取'},
  {title:'截止时间',dataIndex:'due_at',width:155,render:(v:number,r:CaseItem)=>canManage?<DatePicker size="small" value={v?dayjs(v*1000):null} showTime format="MM-DD HH:mm" style={{width:145}} onChange={d=>update(r.job_id,{due_at:d?d.valueOf()/1000:null})}/>:fmtTime(v)},
  {title:'更新',dataIndex:'updated_at',width:135,render:fmtTime},
  {title:'操作',width:116,render:(_:any,r:CaseItem)=><Space size={2}><Tooltip title="查看审查报告"><Button size="small" icon={<EyeOutlined/>} onClick={()=>openId(r.job_id)}/></Tooltip>{canManage&&!r.assigned_to&&<Tooltip title="领取案件"><Button size="small" icon={<UserAddOutlined/>} onClick={()=>update(r.job_id,{assigned_to:user?.id,status:'in_review'})}/></Tooltip>}</Space>}
 ]
 return <Card title="团队案件" extra={<Space><Select value={filter} style={{width:120}} onChange={setFilter} options={[{value:'open',label:'进行中'},{value:'mine',label:'与我相关'},{value:'all',label:'全部案件'}]}/><Button icon={<ReloadOutlined/>} onClick={load}>刷新</Button></Space>}>
  {items.length?<Table rowKey="job_id" size="middle" loading={loading} columns={columns} dataSource={visible} pagination={{pageSize:10}} expandable={{expandedRowRender:r=><div className="case-note"><b>提交说明：</b>{r.request_note||'未填写'} {canManage&&<Select size="small" value={r.workflow_status} style={{marginLeft:18,width:130}} options={workflowOptions} onChange={status=>update(r.job_id,{status})}/>}</div>}}/>:<Empty description="还没有合同案件，先发起第一份合同评审。"/>}
 </Card>
}
