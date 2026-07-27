import { useState } from 'react'
import { Alert, Button, Card, DatePicker, Form, Input, List, Select, Space, Upload, message } from 'antd'
import { DeleteOutlined, FileAddOutlined, FileTextOutlined, SafetyCertificateOutlined, UploadOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { CreditCase } from '../types'

export default function ReviewPage({onCreated}:{onCreated:(caseId:string)=>void}){
  const [form]=Form.useForm(); const [files,setFiles]=useState<File[]>([]); const [credits,setCredits]=useState<CreditCase[]>([]); const [busy,setBusy]=useState(false)
  const loadCredits=async()=>{const customer=String(form.getFieldValue('customer_name')||'').trim();if(!customer)return message.info('请先填写客户名称');try{const r=await api.creditDecisions(customer);setCredits(r.items);if(!r.items.length)message.warning('该客户没有可用的已生效信审版本，请先完成信审审批。')}catch(e:any){message.error(e.message)}}
  const add=(file:File)=>{setFiles(prev=>prev.some(x=>x.name===file.name&&x.size===file.size)?prev:[...prev,file]);return false}
  const submit=async()=>{try{const v=await form.validateFields();if(!files.length)return message.warning('请至少上传一份主合同或订单');setBusy(true);const root=await api.createCaseCenter({customer_name:v.customer_name,business_type:v.business_type,credit_case_id:v.credit_case_id,priority:v.priority,due_at:v.due_at?.valueOf()/1000,request_note:v.request_note});for(const [index,file] of files.entries())await api.upload(file,{case_id:root.case_id,credit_case_id:v.credit_case_id,business_type:v.business_type,document_role:index===0?'main':'annex'});message.success(`案件已创建，${files.length} 份文件正在进入 AI 审查`);onCreated(root.case_id)}catch(e:any){if(!e?.errorFields)message.error(e.message||'提交失败')}finally{setBusy(false)}}
  return <Card title={<Space><FileAddOutlined/>发起合同申请</Space>} extra={<Button type="primary" loading={busy} onClick={submit}>创建案件并提交审查</Button>}>
    <Alert type="info" showIcon style={{marginBottom:16}} message="先创建案件，再把合同主文件、订单和补充协议纳入同一个文件包。系统只允许绑定该客户已生效的信审版本，后续修订会自动保留版本链路。"/>
    <Form form={form} layout="vertical" initialValues={{business_type:'一般',priority:'normal'}} className="review-request-form">
      <div className="review-meta-grid case-create-grid">
        <Form.Item name="customer_name" label="客户名称" rules={[{required:true,message:'请填写客户名称'}]}><Input placeholder="与信审客户名称一致" onBlur={loadCredits}/></Form.Item>
        <Form.Item name="credit_case_id" label="已生效信审版本" rules={[{required:true,message:'必须绑定已生效信审版本'}]}><Select placeholder="先填写客户后加载" options={credits.map(x=>({value:x.case_id,label:`V${x.version} · 账期≤${x.conditions.max_payment_days}天 · 额度≤${x.conditions.max_credit_amount} ${x.conditions.currency}`}))} dropdownRender={menu=><><Button type="link" icon={<SafetyCertificateOutlined/>} onClick={loadCredits}>刷新该客户信审版本</Button>{menu}</>}/></Form.Item>
        <Form.Item name="business_type" label="业务类型" rules={[{required:true}]}><Select options={['一般','模塑一体','TKM','TKP','采购订单'].map(x=>({value:x,label:x}))}/></Form.Item>
        <Form.Item name="priority" label="业务紧急度" rules={[{required:true}]}><Select options={[{value:'low',label:'低'},{value:'normal',label:'普通'},{value:'high',label:'高'},{value:'urgent',label:'紧急'}]}/></Form.Item>
        <Form.Item name="due_at" label="期望完成时间"><DatePicker showTime format="YYYY-MM-DD HH:mm" style={{width:'100%'}}/></Form.Item>
        <Form.Item name="request_note" label="申请说明"><Input.TextArea rows={2} placeholder="例如签约背景、需重点确认的风险、交付要求"/></Form.Item>
      </div>
    </Form>
    <Upload.Dragger multiple showUploadList={false} disabled={busy} accept=".docx,.pdf,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.bmp" beforeUpload={f=>add(f as File)}>
      <p className="ant-upload-drag-icon"><UploadOutlined style={{fontSize:40,color:'#1677ff'}}/></p><p className="ant-upload-text">上传合同文件包</p><p className="ant-upload-hint">第一份文件作为主合同；其余文件会成为同一案件下的订单、补充协议或附件。</p>
    </Upload.Dragger>
    {!!files.length&&<List style={{marginTop:16}} bordered size="small" dataSource={files} renderItem={(file,index)=><List.Item actions={[<Button key="delete" danger type="link" icon={<DeleteOutlined/>} onClick={()=>setFiles(v=>v.filter((_,i)=>i!==index))}>移除</Button>]}><List.Item.Meta avatar={<FileTextOutlined/>} title={<>{file.name} {index===0?<span className="case-id">（主合同）</span>:<span className="case-id">（关联文件）</span>}</>} description={`${(file.size/1024).toFixed(1)} KB`}/></List.Item>}/>}
  </Card>
}
