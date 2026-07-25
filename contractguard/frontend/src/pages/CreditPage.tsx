import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography, message } from 'antd'
import { ApiOutlined, CheckCircleOutlined, PlusOutlined, SafetyCertificateOutlined, SendOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api } from '../services/api'
import { useAuth } from '../context/AuthContext'
import type { CreditCase } from '../types'

const { Text } = Typography
const statusColor:Record<string,string>={draft:'default',pending_approval:'orange',approved:'green',rejected:'red',superseded:'purple'}
const statusText:Record<string,string>={draft:'草稿',pending_approval:'待审批',approved:'已生效',rejected:'已拒绝',superseded:'已被新版本替代'}

const toPayload=(v:any)=>({customer_name:v.customer_name,request_note:v.request_note||'',conditions:{max_credit_amount:v.max_credit_amount||0,currency:v.currency||'CNY',max_payment_days:v.max_payment_days||0,min_prepayment_ratio:v.min_prepayment_ratio||0,allowed_payment_methods:v.allowed_payment_methods||['bank_transfer'],allow_vmi_jit:!!v.allow_vmi_jit,valid_from:v.valid_from?dayjs(v.valid_from).valueOf()/1000:0,valid_to:v.valid_to?dayjs(v.valid_to).valueOf()/1000:0}})

export default function CreditPage(){
  const { user }=useAuth(); const canManage=['admin','credit'].includes(user?.role||'')
  const [items,setItems]=useState<CreditCase[]>([]); const [drawer,setDrawer]=useState(false); const [detail,setDetail]=useState<CreditCase|null>(null); const [form]=Form.useForm()
  const [crmOpen,setCrmOpen]=useState(false); const [crmForm]=Form.useForm(); const [crmHooks,setCrmHooks]=useState<any[]>([])
  const load=()=>api.creditCases().then(r=>setItems(r.items)).catch(e=>message.error('加载信审案件失败：'+e.message))
  const loadCrm=()=>api.crmListHooks().then(r=>setCrmHooks(r.items||[])).catch(()=>{})
  useEffect(()=>{load()},[])
  const create=async()=>{try{const v=await form.validateFields(); await api.createCreditCase(toPayload(v)); message.success('已创建信审草稿；提交和批准后才能用于合同');setDrawer(false);form.resetFields();load()}catch(e:any){if(!e?.errorFields)message.error('创建失败：'+(e?.message||e))}}
  const submit=async(item:CreditCase)=>{try{await api.submitCreditCase(item.case_id);message.success('已提交信审审批');load()}catch(e:any){message.error(e.message)}}
  const decide=async(item:CreditCase,decision:'approved'|'rejected')=>{let note='';Modal.confirm({title:decision==='approved'?'确认生效该信审版本？':'拒绝该信审版本？',content:<Input.TextArea placeholder="必填：审批意见" onChange={e=>note=e.target.value}/>,onOk:async()=>{if(!note.trim())throw new Error('请填写审批意见');await api.decideCreditCase(item.case_id,{decision,note});message.success(decision==='approved'?'信审版本已生效':'信审版本已拒绝');load()}})}
  const createCrmHook=async()=>{
    try{
      const v=await crmForm.validateFields()
      const result=await api.crmCreateHook({customer_name:v.customer_name,crm_account_id:v.crm_account_id,request_note:v.request_note,create_draft:true})
      message.success(`CRM 端口已接收 ${result.hook?.hook_id}；${result.credit_case?'已创建信审草稿':''}`)
      setCrmOpen(false); crmForm.resetFields(); load(); loadCrm()
    }catch(e:any){if(!e?.errorFields)message.error(e?.message||'CRM 试调失败')}
  }
  return <>
    <Card title={<Space><SafetyCertificateOutlined/>客户信审 · 前置商业条件</Space>} extra={<Space>
      {canManage&&<Button icon={<ApiOutlined/>} onClick={()=>{setCrmOpen(true);loadCrm()}}>CRM 对接端口</Button>}
      {canManage?<Button type="primary" icon={<PlusOutlined/>} onClick={()=>{form.resetFields();setDrawer(true)}}>新建信审版本</Button>:null}
    </Space>}>
      <Alert type="info" showIcon style={{marginBottom:16}} message="合同只能绑定“已生效”的信审版本。需要放宽账期、额度、预付款、付款方式或 VMI/JIT 时，先新建并审批信审版本，再重新提交合同复审。授信测算模型由信审模块提供；本页的 CRM 端口仅预留接入形状。"/>
      <Table rowKey="case_id" dataSource={items} pagination={{pageSize:10}} columns={[
        {title:'客户',dataIndex:'customer_name',render:(v:string,r:CreditCase)=><Button type="link" onClick={()=>setDetail(r)}>{v}</Button>},
        {title:'版本',dataIndex:'version',render:(v:number)=>`V${v}`},{title:'状态',dataIndex:'status',render:(v:string)=><Tag color={statusColor[v]}>{statusText[v]||v}</Tag>},
        {title:'最长账期',render:(_:unknown,r:CreditCase)=>`${r.conditions.max_payment_days||0} 天`},{title:'最低预付款',render:(_:unknown,r:CreditCase)=>`${r.conditions.min_prepayment_ratio||0}%`},
        {title:'额度上限',render:(_:unknown,r:CreditCase)=>`${r.conditions.max_credit_amount||0} ${r.conditions.currency||'CNY'}`},
        {title:'操作',render:(_:unknown,r:CreditCase)=>canManage?<Space>{r.status==='draft'&&<Button size="small" icon={<SendOutlined/>} onClick={()=>submit(r)}>提交</Button>}{r.status==='pending_approval'&&<><Button size="small" type="primary" icon={<CheckCircleOutlined/>} onClick={()=>decide(r,'approved')}>批准生效</Button><Button size="small" danger onClick={()=>decide(r,'rejected')}>拒绝</Button></>}</Space>:null}
      ]}/>
    </Card>
    <Drawer title="新建客户信审版本" open={drawer} onClose={()=>setDrawer(false)} width={520} extra={<Button type="primary" onClick={create}>保存草稿</Button>}>
      <Form form={form} layout="vertical" initialValues={{currency:'CNY',allowed_payment_methods:['bank_transfer'],allow_vmi_jit:false,max_credit_amount:0,max_payment_days:0,min_prepayment_ratio:0}}>
        <Form.Item name="customer_name" label="客户名称" rules={[{required:true,message:'请填写客户名称'}]}><Input/></Form.Item><Form.Item name="request_note" label="申请说明"><Input.TextArea rows={3}/></Form.Item>
        <Form.Item name="max_credit_amount" label="最大单笔/敞口金额" rules={[{required:true}]}><InputNumber min={0} precision={2} style={{width:'100%'}}/></Form.Item><Form.Item name="currency" label="币种"><Select options={['CNY','HKD','USD'].map(x=>({value:x,label:x}))}/></Form.Item>
        <Form.Item name="max_payment_days" label="最长账期（天）" rules={[{required:true}]}><InputNumber min={0} max={3650} style={{width:'100%'}}/></Form.Item><Form.Item name="min_prepayment_ratio" label="交付前最低收款比例（%）" rules={[{required:true}]}><InputNumber min={0} max={100} style={{width:'100%'}}/></Form.Item>
        <Form.Item name="allowed_payment_methods" label="允许付款方式"><Select mode="multiple" options={[{value:'bank_transfer',label:'银行转账'},{value:'acceptance_bill',label:'承兑汇票'}]}/></Form.Item><Form.Item name="allow_vmi_jit" label="允许 VMI/JIT"><Select options={[{value:false,label:'不允许'},{value:true,label:'允许'}]}/></Form.Item>
      </Form>
    </Drawer>
    <Drawer title={`信审详情 · ${detail?.customer_name||''}`} open={!!detail} onClose={()=>setDetail(null)} width={520}>{detail&&<Descriptions bordered column={1} size="small"><Descriptions.Item label="版本 / 状态">V{detail.version} · <Tag color={statusColor[detail.status]}>{statusText[detail.status]}</Tag></Descriptions.Item><Descriptions.Item label="最长账期">{detail.conditions.max_payment_days} 天</Descriptions.Item><Descriptions.Item label="交付前最低收款">{detail.conditions.min_prepayment_ratio}%</Descriptions.Item><Descriptions.Item label="额度上限">{detail.conditions.max_credit_amount} {detail.conditions.currency}</Descriptions.Item><Descriptions.Item label="允许付款方式">{detail.conditions.allowed_payment_methods.join('、')}</Descriptions.Item><Descriptions.Item label="VMI/JIT">{detail.conditions.allow_vmi_jit?'允许':'不允许'}</Descriptions.Item><Descriptions.Item label="申请说明"><Text>{detail.request_note||'—'}</Text></Descriptions.Item><Descriptions.Item label="审批意见"><Text>{detail.decision_note||'—'}</Text></Descriptions.Item></Descriptions>}</Drawer>
    <Drawer title="CRM 预留端口（Mock）" open={crmOpen} onClose={()=>setCrmOpen(false)} width={560}
      extra={<Button type="primary" icon={<ApiOutlined/>} onClick={createCrmHook}>模拟 CRM 推送</Button>}>
      <Alert type="info" showIcon style={{marginBottom:12}}
        message="POST /api/integrations/crm/credit-hooks"
        description="供 CRM 推送客户主数据/信用申请占位。本端口不执行授信测算，只创建信审草稿；额度与账期由信审 Agent 填充后审批生效。" />
      <Form form={crmForm} layout="vertical" initialValues={{request_note:'来自 CRM 的信用申请占位'}}>
        <Form.Item name="customer_name" label="客户名称" rules={[{required:true}]}><Input placeholder="与 CRM 客户主数据一致"/></Form.Item>
        <Form.Item name="crm_account_id" label="CRM Account ID"><Input placeholder="可选"/></Form.Item>
        <Form.Item name="request_note" label="申请说明"><Input.TextArea rows={2}/></Form.Item>
      </Form>
      <Table size="small" rowKey="hook_id" pagination={false} dataSource={crmHooks}
        columns={[
          {title:'Hook',dataIndex:'hook_id',render:(v:string)=><Text code>{v}</Text>},
          {title:'客户',dataIndex:'customer_name'},
          {title:'状态',dataIndex:'status',render:(v:string)=><Tag>{v}</Tag>},
          {title:'信审草稿',dataIndex:'credit_case_id',render:(v:string)=>v||'—'},
        ]}/>
    </Drawer>
  </>
}
