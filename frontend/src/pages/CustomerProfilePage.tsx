import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Descriptions, Empty, List, Space, Spin, Tag, Typography, message } from 'antd'
import { ArrowLeftOutlined, FileAddOutlined, FolderOpenOutlined, RightOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { CustomerAction, CustomerHeadroom, CustomerWorkspace } from '../types'
import { fmtTime } from '../components/common'
import CustomerExposureGuard from '../components/CustomerExposureGuard'

const { Title, Text } = Typography
const roleText:Record<string,string>={business:'业务申请人',reviewer:'信用审核专员',director:'财务审批主管',final_approver:'集团财务总监',admin:'系统管理员',system:'系统'}
const creditText:Record<string,string>={draft:'待信用审核',returned_to_reviewer:'退回审核专员',returned_to_business:'待业务补充材料',pending_director:'待主管复核',pending_final:'待最终审批',approved:'已生效',rejected:'已拒绝',superseded:'历史版本'}
const stageText:Record<string,string>={draft:'待上传合同',awaiting_credit:'等待有效信用审核',ai_review:'系统审查中',legal_review:'信用审核专员复核',awaiting_business:'待业务补充材料',approval:'待主管审批',final_approval:'待最终审批',ready_to_sign:'可签约',archived:'已归档',cancelled:'已取消'}
const tone=(stage:string)=>stage==='approved'||stage==='ready_to_sign'?'green':stage.includes('return')||stage==='awaiting_business'||stage==='awaiting_credit'?'orange':stage==='rejected'||stage==='cancelled'?'red':'blue'
const actionText=(action:CustomerAction)=>action.source_type==='credit'?(creditText[action.stage]||action.stage):(stageText[action.stage]||action.stage)

type Props={customerKey:string;onBack:()=>void;onOpenCase:(id:string)=>void;onOpenCredit:(id:string)=>void;onCreateCredit:(customer:CustomerWorkspace)=>void;canCreateCredit:boolean;onCreateContract:(customer:CustomerWorkspace)=>void;canCreateContract:boolean}

export default function CustomerProfilePage({customerKey,onBack,onOpenCase,onOpenCredit,onCreateCredit,canCreateCredit,onCreateContract,canCreateContract}:Props){
  const [customer,setCustomer]=useState<CustomerWorkspace|null>(null)
  const [loading,setLoading]=useState(true)
  const [headroom,setHeadroom]=useState<CustomerHeadroom|null>(null)
  const [headroomLoading,setHeadroomLoading]=useState(true)
  const loadHeadroom=async()=>{setHeadroomLoading(true);try{setHeadroom(await api.customerHeadroom(customerKey))}catch{setHeadroom(null)}finally{setHeadroomLoading(false)}}
  const load=async()=>{setLoading(true);try{setCustomer(await api.customerWorkspace(customerKey));await loadHeadroom()}catch(e:any){message.error(e.message||'客户档案加载失败')}finally{setLoading(false)}}
  useEffect(()=>{load()},[customerKey])
  const activeActions=useMemo(()=>customer?.current_actions||[],[customer])
  if(loading)return <div className="page-loading"><Spin/><Text type="secondary">正在打开客户档案…</Text></div>
  if(!customer)return <Empty description="客户档案不存在"/>
  const latest=customer.latest_credit
  const openAction=(action:CustomerAction)=>action.source_type==='credit'?onOpenCredit(action.target_id):onOpenCase(action.target_id)
  const simulateHeadroom=async(amount:number)=>{try{setHeadroom(await api.simulateCustomerHeadroom(customerKey,amount));message.success('已完成新增订单额度占用模拟')}catch(e:any){message.error(e.message||'额度占用模拟失败')}}
  return <div className="customer-profile-page">
    <section className="customer-profile-head"><div><Button type="link" icon={<ArrowLeftOutlined/>} onClick={onBack} style={{paddingLeft:0}}>返回客户</Button><Title level={2}>{customer.customer_name}</Title></div><Space wrap>{canCreateContract&&<Button type="primary" icon={<FileAddOutlined/>} onClick={()=>onCreateContract(customer)}>发起合同</Button>}<Button onClick={load}>刷新</Button></Space></section>
    <Card className="customer-primary-action" title="当前事项"><div className="customer-primary-grid"><div><Title level={4}>{activeActions.length?`${actionText(activeActions[0])} · ${roleText[activeActions[0].responsible_role]||activeActions[0].responsible_role}`:'当前没有在途事项'}</Title>{activeActions.length&&<Text>负责人：{activeActions[0].responsible_name}</Text>}</div>{activeActions.length?<Button type="primary" icon={<RightOutlined/>} onClick={()=>openAction(activeActions[0])}>进入</Button>:latest?.status==='approved'&&canCreateContract?<Button type="primary" icon={<FileAddOutlined/>} onClick={()=>onCreateContract(customer)}>发起合同</Button>:null}</div></Card>
    <CustomerExposureGuard headroom={headroom} loading={headroomLoading} onRefresh={loadHeadroom} onSimulate={simulateHeadroom} />
    <section className="customer-profile-grid">
      <Card title={<Space><UserOutlined/>责任与待办</Space>} className="customer-actions-card">{activeActions.length?<List dataSource={activeActions} renderItem={(action,index)=><List.Item actions={[<Button key="open" type="link" onClick={()=>openAction(action)}>查看</Button>]}><List.Item.Meta avatar={<Tag color={tone(action.stage)}>{index===0?'当前':'待办'}</Tag>} title={<Space wrap><Text strong>{actionText(action)}</Text><Tag>{action.source_type==='credit'?'信用审核':'合同'}</Tag></Space>} description={<><Text>当前负责人：{roleText[action.responsible_role]||action.responsible_role} · {action.responsible_name}</Text><br/><Text type="secondary">最近更新：{fmtTime(action.updated_at)}</Text></>}/></List.Item>}/>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有需要处理的事项"/>}</Card>
      <Card title={<Space><SafetyCertificateOutlined/>信用审核状态</Space>} className="customer-credit-card">{latest?<><Descriptions column={1} size="small"><Descriptions.Item label="当前版本">V{latest.version}</Descriptions.Item><Descriptions.Item label="状态"><Tag color={tone(latest.status)}>{creditText[latest.status]||latest.status}</Tag></Descriptions.Item><Descriptions.Item label="当前责任">{roleText[latest.responsible_role]||latest.responsible_role} · {latest.responsible_name}</Descriptions.Item><Descriptions.Item label="最近更新">{fmtTime(latest.updated_at)}</Descriptions.Item></Descriptions><Button style={{marginTop:12}} onClick={()=>onOpenCredit(latest.case_id)}>查看信用审核与材料</Button></>:<Alert showIcon type="warning" message="尚未建立信用审核" description={<Space direction="vertical">必须先完成客户信用审核，才能将合同正式送审。{canCreateCredit&&<Button size="small" type="primary" onClick={()=>onCreateCredit(customer)}>为该客户发起信用审核</Button>}</Space>}/>}</Card>
    </section>
    <Card className="customer-contract-records" title={<Space><FolderOpenOutlined/>合同记录（{customer.contracts.length}）</Space>}>{customer.contracts.length?<List dataSource={customer.contracts} renderItem={contract=><List.Item actions={[<Button key="case" type="link" onClick={()=>onOpenCase(contract.case_id)}>进入案件</Button>]}><List.Item.Meta title={<Space wrap><Tag color={tone(contract.current_stage)}>{stageText[contract.current_stage]||contract.current_stage}</Tag><Text strong>{contract.filename||'待上传合同文件'}</Text></Space>} description={<div className="customer-contract-record"><span>当前责任：{roleText[contract.responsible_role]||contract.responsible_role} · {contract.responsible_name}</span><span>最近更新：{fmtTime(contract.updated_at)}</span><span>{contract.case_id}</span></div>}/></List.Item>}/>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该客户尚无合同记录"/>}</Card>
  </div>
}
