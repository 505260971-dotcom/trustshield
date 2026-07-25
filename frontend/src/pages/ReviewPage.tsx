import { useEffect, useRef, useState } from 'react'
import { Alert, Card, Upload, Button, Space, Typography, Spin, message, Steps, Progress, List, Empty, Tabs, Tag, Popconfirm, DatePicker, Form, Input, Select } from 'antd'
import { UploadOutlined, AuditOutlined, BookOutlined, FileTextOutlined, DeleteOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { CreditCase, Report, ReviewRequest, TeamMember } from '../types'
import ReportView from '../components/ReportView'

const { Text } = Typography

type JobState = {
  job_id: string; filename: string; steps: string[]; report: Report | null
  running: boolean; error?: string
}

const stepItems = [
  {title:'文档解析'}, {title:'脱敏'}, {title:'字段抽取'},
  {title:'规则候选'}, {title:'LLM研判'}, {title:'规则引擎'}, {title:'汇总结论'}
]

export default function ReviewPage ({ setRulesOpen, onSubmitted }: { setRulesOpen:(v:boolean)=>void; onSubmitted:()=>void }) {
  const [pending, setPending] = useState<File[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [jobs, setJobs] = useState<JobState[]>([])
  const [activeKey, setActiveKey] = useState<string>('')
  const [reviewers,setReviewers]=useState<TeamMember[]>([])
  const [creditDecisions,setCreditDecisions]=useState<CreditCase[]>([])
  const [form]=Form.useForm()
  const esMap = useRef<Record<string, EventSource | null>>({})

  useEffect(()=>{api.reviewers().then(r=>setReviewers(r.items)).catch(()=>{});api.creditDecisions().then(r=>setCreditDecisions(r.items)).catch(()=>message.warning('未能加载已生效信审版本，暂不能提交合同'))},[])

  const addFiles = (files: File[]) => {
    setPending(prev => {
      const next = [...prev]
      for (const f of files) {
        if (!next.some(x => x.name === f.name && x.size === f.size)) next.push(f)
      }
      return next
    })
  }

  const onBeforeUpload = (file: File): boolean => { addFiles([file]); return false }

  const startJob = (jobId: string, filename: string) => {
    setJobs(prev => [...prev, { job_id: jobId, filename, steps: [], report: null, running: true }])
    setActiveKey(jobId)
    const es = new EventSource(api.streamUrl(`/api/stream/${jobId}`))
    esMap.current[jobId] = es
    es.addEventListener('step', (e: MessageEvent) => {
      setJobs(prev => prev.map(j => j.job_id === jobId && j.steps.length < 400 ? { ...j, steps: [...j.steps, e.data] } : j))
    })
    es.addEventListener('done', (e: MessageEvent) => {
      const rep = JSON.parse(e.data) as Report
      rep._job_id = jobId
      setJobs(prev => prev.map(j => j.job_id === jobId ? { ...j, report: rep, running: false } : j))
      es.close(); esMap.current[jobId] = null
      message.success(`${filename} 审查完成：${rep.summary?.overall_level}`)
    })
    es.addEventListener('error', (e: any) => {
      try { if (e.data) { message.error(`${filename} 审查失败：`+String(e.data).slice(0,200)) } } catch {}
      setJobs(prev => prev.map(j => j.job_id === jobId ? { ...j, running: false, error: 'stream-error' } : j))
      es.close(); esMap.current[jobId] = null
    })
  }

  const startBatch = async () => {
    if (!pending.length) return
    setSubmitting(true)
    try {
      const values=await form.validateFields()
      const request:ReviewRequest={business_type:values.business_type,credit_case_id:values.credit_case_id,parent_job_id:values.parent_job_id,assignee_id:values.assignee_id,priority:values.priority,due_at:values.due_at?.valueOf()/1000,request_note:values.request_note}
      if (pending.length === 1) {
        const { job_id } = await api.upload(pending[0],request)
        message.success(`已提交：${pending[0].name}`)
        startJob(job_id, pending[0].name)
      } else {
        const { jobs: js } = await api.reviewBatch(pending,request)
        message.success(`已批量提交 ${js.length} 个文件`)
        for (const j of js) startJob(j.job_id, j.filename)
      }
      setPending([])
      onSubmitted()
    } catch (e:any) { message.error('提交失败：'+(e?.message||String(e))) }
    finally { setSubmitting(false) }
  }

  const removePending = (idx: number) => setPending(prev => prev.filter((_, i) => i !== idx))
  const clearAll = () => { setPending([]); setJobs([]); setActiveKey('') }

  const busy = submitting || jobs.some(j => j.running)

  const tabItems = jobs.map(j => ({
    key: j.job_id,
    label: <Space size={4}>
      <FileTextOutlined/>
      <span style={{maxWidth:180, display:'inline-block', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', verticalAlign:'bottom'}}>{j.filename}</span>
      {j.running ? <Tag color="processing" style={{margin:0}}>审查中</Tag>
       : j.report ? <Tag color={j.report.summary?.overall_level?.startsWith('阻断')?'red':'green'} style={{margin:0}}>完成</Tag>
       : <Tag color="error" style={{margin:0}}>失败</Tag>}
    </Space>,
    children: <>
      {j.running && (
        <Card title="审查链路（多 Agent 协同）" size="small" style={{marginBottom:16}}>
          <Steps current={Math.min(j.steps.length-1, 6)} items={stepItems} />
          <Progress percent={Math.min(95, Math.round((j.steps.length/14)*100))} status="active" style={{marginTop:14}}/>
          <List size="small" dataSource={j.steps.slice(-8)} renderItem={(s:string)=>
            <List.Item><Text type="secondary">{s}</Text></List.Item>} style={{marginTop:10}}/>
        </Card>
      )}
      {j.report ? <ReportView report={j.report} jobId={j.job_id} />
        : j.running ? null
        : <Card><Empty description="审查失败，请重试该文件"/></Card>}
    </>
  }))

  return (
    <>
      <Card style={{marginBottom:16}} title={<Space><AuditOutlined/> 发起合同评审</Space>}
        extra={<Button icon={<BookOutlined/>} onClick={()=>setRulesOpen(true)}>查看底限条款库</Button>}>
        <Form form={form} layout="vertical" initialValues={{priority:'normal',business_type:'一般'}} className="review-request-form">
          <Alert type="warning" showIcon style={{marginBottom:12}} message="信审前置：必须选择一个已生效的客户信审版本。合同条款一旦超过其账期、额度、预付款、付款方式或交付模式边界，将被阻断，不能在合同端忽略或审批。"/>
          <div className="review-meta-grid">
            <Form.Item name="business_type" label="合同业务类型" rules={[{required:true}]}><Select options={[{value:'一般',label:'一般销售合同'},{value:'模塑一体',label:'模塑一体'},{value:'TKM',label:'TKM'},{value:'TKP',label:'TKP'},{value:'采购订单',label:'采购订单'}]}/></Form.Item>
            <Form.Item name="credit_case_id" label="已生效信审版本" rules={[{required:true,message:'请先选择已生效信审版本'}]}><Select placeholder={creditDecisions.length?'选择客户信审条件':'暂无已生效信审版本，请先在信审工作台完成审批'} options={creditDecisions.map(x=>({value:x.case_id,label:`${x.customer_name} · V${x.version} · 账期≤${x.conditions.max_payment_days}天 / 预付≥${x.conditions.min_prepayment_ratio}%`}))}/></Form.Item>
            <Form.Item name="parent_job_id" label="上一版本任务 ID"><Input placeholder="可选：上传客户修订版时填写" /></Form.Item>
            <Form.Item name="assignee_id" label="指定法务负责人"><Select allowClear placeholder="暂不指定，进入待领取队列" options={reviewers.map(x=>({value:x.id,label:x.display_name}))}/></Form.Item>
            <Form.Item name="priority" label="处理优先级" rules={[{required:true}]}><Select options={[{value:'low',label:'低：常规检查'},{value:'normal',label:'普通：常规合同'},{value:'high',label:'高：重点业务'},{value:'urgent',label:'紧急：优先处理'}]}/></Form.Item>
            <Form.Item name="due_at" label="期望完成时间"><DatePicker showTime format="YYYY-MM-DD HH:mm" placeholder="可选" style={{width:'100%'}}/></Form.Item>
            <Form.Item name="request_note" label="提交说明"><Input.TextArea rows={1} maxLength={1000} placeholder="例如：本周签约，需重点核对违约与交付条款"/></Form.Item>
          </div>
        </Form>
        <Upload.Dragger accept=".docx,.pdf,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.bmp" multiple showUploadList={false}
          beforeUpload={(f:any)=>{ onBeforeUpload(f as File); return false }} disabled={busy}>
          <p className="ant-upload-drag-icon"><UploadOutlined style={{fontSize:48, color: busy?'#aaa':'#1677ff'}}/></p>
          <p className="ant-upload-text">{busy ? '正在审查，请稍候…' : '点击或拖拽上传合同（支持批量 · docx / pdf / xlsx / txt / png）'}</p>
          <p className="ant-upload-hint">合同先在本地脱敏，再进行规则候选、语义研判与确定性校验。图片需本机 OCR。</p>
        </Upload.Dragger>

        {(pending.length > 0) && (
          <Card type="inner" size="small" title={`待审查文件（${pending.length}）`} style={{marginTop:12}}
            extra={<Space>
              <Button size="small" type="primary" icon={<ThunderboltOutlined/>} loading={submitting} disabled={busy} onClick={startBatch}>
                开始{pending.length>1?'批量':''}审查
              </Button>
              <Button size="small" onClick={()=>setPending([])}>清空待审</Button>
            </Space>}>
            <List size="small" dataSource={pending} renderItem={(f:File, i:number)=>
              <List.Item actions={[<Button size="small" type="link" danger icon={<DeleteOutlined/>} onClick={()=>removePending(i)}>移除</Button>]}>
                <List.Item.Meta avatar={<FileTextOutlined style={{fontSize:20, color:'#1677ff'}}/>}
                  title={<Text strong>{f.name}</Text>}
                  description={<Text type="secondary">{(f.size/1024).toFixed(1)} KB</Text>} />
              </List.Item>}/>
          </Card>
        )}
        {submitting && <div style={{textAlign:'center', marginTop:12}}><Spin tip="提交中…"/></div>}
      </Card>

      {jobs.length > 0 ? (
        <Card title={`审查结果 · ${jobs.length} 个文件`} extra={busy ? null : <Popconfirm title="清空全部审查记录？" onConfirm={clearAll}><Button icon={<DeleteOutlined/>}>清空</Button></Popconfirm>}>
          <Tabs activeKey={activeKey} onChange={setActiveKey} items={tabItems} type="card" />
        </Card>
      ) : !pending.length ? (
        <Card><Empty description="上传合同开始审查；历史审查可在「历史记录」中回看" /></Card>
      ) : null}
    </>
  )
}

