import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Empty, Input, List, Space, Spin, Tag, Typography, message } from 'antd'
import { FileAddOutlined, FolderOpenOutlined, ReloadOutlined, SafetyCertificateOutlined, TeamOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { CustomerWorkspace } from '../types'
import { fmtTime } from '../components/common'
import { creditStatusInfo, customerContractAction, roleDisplayName, stageInfo } from '../components/workflow'

const { Text, Title } = Typography

function nextAction(stage:string, kind:'credit'|'contract'){
  return kind==='credit' ? creditStatusInfo(stage).action || '查看信用审核状态' : customerContractAction(stage)
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
      <div className="page-hero-actions"><Space wrap><Button icon={<ReloadOutlined/>} onClick={load}>刷新</Button><Button icon={<SafetyCertificateOutlined/>} onClick={onOpenCreditList}>信用审核清单</Button>{canCreateContract&&<Button type="primary" icon={<FileAddOutlined/>} onClick={onCreateContract}>发起合同申请</Button>}</Space></div>
    </section>
    <Card className="page-data-card" title={<Space><TeamOutlined/><span>客户业务进展</span><Text type="secondary">共 {shown.length} 位客户</Text></Space>} extra={<Input.Search allowClear placeholder="搜索客户或合同文件" value={keyword} onChange={e=>setKeyword(e.target.value)} style={{width:260}}/>}>
      {loading?<div className="page-loading"><Spin/><Text type="secondary">正在汇总客户信用审核和合同进展…</Text></div>:shown.length?<div className="customer-workspace-list">{shown.map(customer=>{
        const latest=customer.latest_credit
        return <Card key={customer.customer_key} className="customer-journey-card" size="small" title={<div className="customer-card-title"><div><Text strong>{customer.customer_name}</Text><Text type="secondary">最近更新：{fmtTime(customer.updated_at)}</Text></div><Tag color={customer.open_contract_tasks?'blue':'default'}>{customer.open_contract_tasks?`${customer.open_contract_tasks} 项合同待办`:'当前无合同待办'}</Tag></div>} extra={<Button type="link" onClick={()=>onOpenCustomer(customer.customer_key)}>进入客户档案</Button>}>
          <div className="customer-journey-grid">
            <section className="customer-credit-lane"><div className="customer-lane-title"><SafetyCertificateOutlined/><Text strong>客户信用审核</Text></div>{latest?<><div className="journey-status-row"><Tag color={creditStatusInfo(latest.status).color}>{creditStatusInfo(latest.status).label}</Tag><Text>V{latest.version} · {latest.business_type||'一般'}</Text></div><div className="journey-owner"><span>当前责任</span><b>{roleDisplayName[latest.responsible_role]||latest.responsible_role} · {latest.responsible_name}</b></div><Text type="secondary">下一步：{nextAction(latest.status,'credit')}</Text><Button type="link" onClick={()=>onOpenCredit(latest.case_id)}>{creditStatusInfo(latest.status).action || '打开信用审核'}</Button>{customer.credit_cases.length>1&&<Text type="secondary">另有 {customer.credit_cases.length-1} 个历史版本</Text>}</>:<div className="journey-empty"><Text type="secondary">尚未建立信用审核，合同不能进入正式审查。</Text><Button type="link" onClick={onOpenCreditList}>发起信用审核</Button></div>}</section>
            <section className="customer-contract-lane"><div className="customer-lane-title"><FolderOpenOutlined/><Text strong>合同案件（{customer.contracts.length}）</Text></div>{customer.contracts.length ? <List size="small" dataSource={customer.contracts} renderItem={contract=>{const meta=stageInfo(contract.current_stage);return <List.Item actions={[<Button key="open" type="link" onClick={()=>onOpenCase(contract.case_id)}>{meta.action || '查看案件详情'}</Button>]}><List.Item.Meta title={<Space wrap><Tag color={meta.color}>{meta.label}</Tag><Text strong>{contract.filename||'待上传合同文件'}</Text></Space>} description={<div className="contract-lane-detail"><span>{contract.case_id}</span><span>当前责任：{roleDisplayName[contract.responsible_role]||contract.responsible_role} · {contract.responsible_name}</span><span>下一步：{nextAction(contract.current_stage,'contract')}</span></div>}/></List.Item>}} /> : <div className="journey-empty"><Text type="secondary">该客户还没有合同案件。</Text>{canCreateContract&&<Button type="link" onClick={onCreateContract}>发起合同申请</Button>}</div>}</section>
          </div>
        </Card>})}</div>:<Empty description={keyword?'未找到匹配的客户或合同':'暂时没有可查看的客户工作流'}/>} 
    </Card>
  </div>
}
