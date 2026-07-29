import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Empty, Segmented, Space, Table, Tag, Typography, message } from 'antd'
import { FileAddOutlined, ReloadOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { CaseCenterItem } from '../types'
import { fmtTime } from '../components/common'

const stageText:Record<string,string>={draft:'待上传',awaiting_credit:'等待信审',ai_review:'AI 审查中',legal_review:'信用审核专员复核',awaiting_business:'待业务补件',approval:'分级审批',ready_to_sign:'可签约',archived:'已归档',cancelled:'已取消'}
const stageColor:Record<string,string>={draft:'default',awaiting_credit:'orange',ai_review:'processing',legal_review:'blue',awaiting_business:'gold',approval:'purple',ready_to_sign:'green',archived:'default',cancelled:'red'}

export default function CaseCenterPage({onCreate,onOpen,canCreateContract}:{onCreate:()=>void;onOpen:(id:string)=>void;canCreateContract:boolean}){
  const [items,setItems]=useState<CaseCenterItem[]>([]); const [scope,setScope]=useState<'all'|'mine'|'inbox'>('all'); const [loading,setLoading]=useState(true)
  const load=async()=>{setLoading(true);try{setItems((await api.caseCenter(scope)).items)}catch(e:any){message.error(e.message||'案件加载失败')}finally{setLoading(false)}}
  useEffect(()=>{load()},[scope])
  const columns=useMemo(()=>[
    {title:'客户 / 合同',key:'case',render:(_:unknown,r:CaseCenterItem)=><Button type="link" style={{padding:0,textAlign:'left'}} onClick={()=>onOpen(r.case_id)}><b>{r.customer_name}</b><br/><span className="case-id">{r.filename||'待上传合同'} · {r.case_id}</span></Button>},
    {title:'阶段',dataIndex:'current_stage',width:130,render:(v:string)=><Tag color={stageColor[v]||'default'}>{stageText[v]||v}</Tag>},
    {title:'AI 结论',dataIndex:'overall_level',width:170,render:(v:string)=><Tag color={v?.startsWith('阻断')?'red':v?.startsWith('需')?'orange':'green'}>{v||'尚未审查'}</Tag>},
    {title:'待办',dataIndex:'open_tasks',width:80,render:(v:number)=><Tag color={v?'blue':'default'}>{v}</Tag>},
    {title:'负责人',dataIndex:'assignee_name',width:120,render:(v:string)=>v||'待领取'},
    {title:'优先级',dataIndex:'priority',width:90,render:(v:string)=><Tag color={v==='urgent'?'red':v==='high'?'orange':'blue'}>{({low:'低',normal:'普通',high:'高',urgent:'紧急'} as any)[v]||v}</Tag>},
    {title:'更新时间',dataIndex:'updated_at',width:160,render:fmtTime},
  ],[onOpen])
  return <Card title="合同案件中心" extra={<Space><Segmented value={scope} onChange={v=>setScope(v as any)} options={[{label:'全部案件',value:'all'},{label:'与我相关',value:'mine'},{label:'我的待办',value:'inbox'}]}/><Button icon={<ReloadOutlined/>} onClick={load}>刷新</Button>{canCreateContract&&<Button type="primary" icon={<FileAddOutlined/>} onClick={onCreate}>发起申请</Button>}</Space>}>
    <Typography.Paragraph type="secondary">一个案件贯穿合同文件包、AI 审查、补件、例外审批、修订版本与交付归档。阶段只能由业务动作推进，不能被任意修改。</Typography.Paragraph>
    {items.length?<Table rowKey="case_id" loading={loading} columns={columns} dataSource={items} pagination={{pageSize:12}} scroll={{x:1050}}/>:<Empty description="暂无合同案件"/>}
  </Card>
}
