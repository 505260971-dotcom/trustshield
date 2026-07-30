import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Empty, Input, List, Space, Spin, Tag, Typography, message } from 'antd'
import { FileAddOutlined, FolderOpenOutlined, ReloadOutlined, SafetyCertificateOutlined, TeamOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { CustomerWorkspace } from '../types'
import { fmtTime } from '../components/common'

const { Text, Title } = Typography

const creditStatus:Record<string,[string,string]>={
  draft:['processing','待信用审核'],returned_to_reviewer:['warning','退回审核专员'],returned_to_business:['warning','待业务补充'],
  pending_director:['purple','待主管复核'],pending_final:['magenta','待最终审批'],approved:['success','已生效'],
  rejected:['error','已拒绝'],superseded:['default','已被新版本替代'],
}
const contractStage:Record<string,[string,string]>={
  draft:['default','待上传合同'],awaiting_credit:['warning','等待有效信审'],ai_review:['processing','系统审查中'],
  legal_review:['blue','审核员复核'],awaiting_business:['warning','待业务补件'],approval:['purple','待主管审批'],
  final_approval:['magenta','待最终审批'],ready_to_sign:['success','可签约'],archived:['default','已归档'],cancelled:['error','已取消'],
}
const roleName:Record<string,string>={business:'业务申请人',reviewer:'信用审核专员',director:'财务审批主管',admin:'集团财务总监',system:'系统'}

function nextAction(stage:string, kind:'credit'|'contract'){
  if(kind==='credit') return ({draft:'完成材料核验与信审评估',returned_to_reviewer:'按退回意见修订信审条件',returned_to_business:'补齐信审材料后重新提交',pending_director:'复核信审条件并作出决定',pending_final:'进行最终信审批核',approved:'可作为合同审查前置条件'} as Record<string,string>)[stage]||'查看信审状态'
  return ({draft:'上传合同文件包',awaiting_credit:'绑定该客户已生效信审',ai_review:'等待系统完成审查',legal_review:'确认风险处置路径',awaiting_business:'补充材料或上传修订合同',approval:'作出合同例外审批决定',final_approval:'作出最终审批决定',ready_to_sign:'推进签约与归档',archived:'已完成'} as Record<string,string>)[stage]||'查看案件详情'
}

type Props={onOpenCustomer:(key:string)=>void;onOpenCase:(id:string)=>void;onOpenCredit:(id:string)=>void;onCreateContract:()=>void;onOpenCreditList:()=>void;canCreateContract:boolean}

export default function CustomerWorkspacePage({onOpenCustomer,onOpenCase,onOpenCredit,onCreateContract,onOpenCreditList,canCreateContract}:Props){
  const [items,setItems]=useState<CustomerWorkspace[]>([])
  const [loading,setLoading]=useState(true)
  const [keyword,setKeyword]=useState('')
  const load=async()=>{setLoading(true);try{setItems((await api.customerWorkspaces()).items||[])}catch(e:any){message.error(e.message||'客户工作台加载失败')}finally{setLoading(false)}}
  useEffect(()=>{load()},[])
  const shown=useMemo(()=>{const q=keyword.trim().toLowerCase();return q?items.filter(item=>item.customer_name.toLowerCase().includes(q)||item.contracts.some(c=>(c.filename||'').toLowerCase().includes(q))):items},[items,keyword])
  return <div className="customer-workspace-page">
    <section className="page-hero page-hero-light customer-workspace-hero">
      <div><Title level={2}>客户工作台</Title></div>
      <div className="page-hero-actions"><Space wrap><Button icon={<ReloadOutlined/>} onClick={load}>刷新</Button><Button icon={<SafetyCertificateOutlined/>} onClick={onOpenCreditList}>信审清单</Button>{canCreateContract&&<Button type="primary" icon={<FileAddOutlined/>} onClick={onCreateContract}>发起合同申请</Button>}</Space></div>
    </section>
    <Card className="page-data-card" title={<Space><TeamOutlined/><span>客户与业务流</span><Text type="secondary">共 {shown.length} 位客户</Text></Space>} extra={<Input.Search allowClear placeholder="搜索客户或合同文件" value={keyword} onChange={e=>setKeyword(e.target.value)} style={{width:260}}/>}>
      {loading?<div className="page-loading"><Spin/><Text type="secondary">正在汇总客户信审和合同…</Text></div>:shown.length?<div className="customer-workspace-list">{shown.map(customer=>{
        const latest=customer.latest_credit
        return <Card key={customer.customer_key} className="customer-journey-card" size="small" title={<div className="customer-card-title"><div><Text strong>{customer.customer_name}</Text><Text type="secondary">最近更新：{fmtTime(customer.updated_at)}</Text></div><Tag color={customer.open_contract_tasks?'blue':'default'}>{customer.open_contract_tasks?`${customer.open_contract_tasks} 项合同待办`:'当前无合同待办'}</Tag></div>} extra={<Button type="link" onClick={()=>onOpenCustomer(customer.customer_key)}>进入客户档案</Button>}>
          <div className="customer-journey-grid">
            <section className="customer-credit-lane"><div className="customer-lane-title"><SafetyCertificateOutlined/><Text strong>客户信审</Text></div>{latest?<><div className="journey-status-row"><Tag color={creditStatus[latest.status]?.[0]||'default'}>{creditStatus[latest.status]?.[1]||latest.status}</Tag><Text>V{latest.version} · {latest.business_type||'一般'}</Text></div><div className="journey-owner"><span>当前责任</span><b>{roleName[latest.responsible_role]||latest.responsible_role} · {latest.responsible_name}</b></div><Text type="secondary">下一步：{nextAction(latest.status,'credit')}</Text><Button type="link" onClick={()=>onOpenCredit(latest.case_id)}>打开该信审</Button>{customer.credit_cases.length>1&&<Text type="secondary">另有 {customer.credit_cases.length-1} 个历史版本</Text>}</>:<div className="journey-empty"><Text type="secondary">尚未建立信审，合同不能进入正式审查。</Text><Button type="link" onClick={onOpenCreditList}>去发起信审</Button></div>}</section>
            <section className="customer-contract-lane"><div className="customer-lane-title"><FolderOpenOutlined/><Text strong>合同案件（{customer.contracts.length}）</Text></div>{customer.contracts.length ? <List size="small" dataSource={customer.contracts} renderItem={contract=>(<List.Item actions={[<Button key="open" type="link" onClick={()=>onOpenCase(contract.case_id)}>处理</Button>]}><List.Item.Meta title={<Space wrap><Tag color={contractStage[contract.current_stage]?.[0]||'default'}>{contractStage[contract.current_stage]?.[1]||contract.current_stage}</Tag><Text strong>{contract.filename||'待上传合同文件'}</Text></Space>} description={<div className="contract-lane-detail"><span>{contract.case_id}</span><span>当前责任：{roleName[contract.responsible_role]||contract.responsible_role} · {contract.responsible_name}</span><span>下一步：{nextAction(contract.current_stage,'contract')}</span></div>}/></List.Item>)} /> : <div className="journey-empty"><Text type="secondary">该客户还没有合同案件。</Text>{canCreateContract&&<Button type="link" onClick={onCreateContract}>发起合同申请</Button>}</div>}</section>
          </div>
        </Card>})}</div>:<Empty description={keyword?'未找到匹配的客户或合同':'暂时没有可查看的客户工作流'}/>} 
    </Card>
  </div>
}
