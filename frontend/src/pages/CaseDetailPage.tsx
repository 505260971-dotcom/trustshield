import { useEffect, useMemo, useState } from 'react'
import { Alert, Badge, Button, Card, Descriptions, Empty, List, Modal, Select, Space, Spin, Steps, Tabs, Tag, Typography, Upload, message } from 'antd'
import { ArrowLeftOutlined, CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined, FileTextOutlined, SafetyCertificateOutlined, SendOutlined, UploadOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import { useAuth } from '../context/AuthContext'
import type { CaseCenterDetail, CaseDocument, Report } from '../types'
import { fmtTime } from '../components/common'
import CaseWorkflowPanel from '../components/CaseWorkflowPanel'
import ReportView from '../components/ReportView'

const { Text, Title } = Typography
const stageOrder=['draft','awaiting_credit','ai_review','legal_review','awaiting_business','approval','final_approval','ready_to_sign','archived']
const stageLabel:Record<string,string>={draft:'待上传合同',awaiting_credit:'等待有效信审',ai_review:'系统审查中',legal_review:'审核员人工复核',awaiting_business:'待业务补件',approval:'待主管审批',final_approval:'待最终审批',ready_to_sign:'审查完成，可进入签约',archived:'已签约归档'}
type ReviewGate={report:Report;findings:any[];approvals:any[];material_requests:any[]}

function roleLabel(role?:string){return ({business:'业务申请人',reviewer:'信用审核专员',director:'财务审批主管',admin:'集团财务总监 / 最终审批人'} as Record<string,string>)[role||'']||'当前角色'}

export default function CaseDetailPage({caseId,onBack}:{caseId:string;onBack:()=>void}){
  const {user}=useAuth()
  const [item,setItem]=useState<CaseCenterDetail|null>(null)
  const [loading,setLoading]=useState(true)
  const [report,setReport]=useState<Report|null>(null)
  const [reportJob,setReportJob]=useState('')
  const [selectedJob,setSelectedJob]=useState('')
  const [gate,setGate]=useState<ReviewGate|null>(null)
  const [gateLoading,setGateLoading]=useState(false)
  const [actionBusy,setActionBusy]=useState(false)
  const [baseJob,setBaseJob]=useState('')
  const [currentJob,setCurrentJob]=useState('')
  const [comparison,setComparison]=useState<any>(null)

  const load=async()=>{setLoading(true);try{setItem(await api.caseCenterDetail(caseId))}catch(e:any){message.error(e.message||'案件加载失败')}finally{setLoading(false)}}
  useEffect(()=>{load();setReport(null);setReportJob('');setSelectedJob('');setGate(null)},[caseId])

  const currentDocument=useMemo<CaseDocument|undefined>(()=>{
    if(!item)return undefined
    return item.documents.find(doc=>doc.is_current_version)||item.documents.find(doc=>doc.document_role==='revision'||doc.document_role==='main')
  },[item])
  const activeJob=selectedJob||currentDocument?.job_id||''

  useEffect(()=>{
    if(!activeJob)return
    let cancelled=false
    setGateLoading(true)
    api.reviewDetail(activeJob).then(value=>{if(!cancelled)setGate(value as ReviewGate)}).catch(()=>{if(!cancelled)setGate(null)}).finally(()=>{if(!cancelled)setGateLoading(false)})
    return()=>{cancelled=true}
  },[activeJob])

  const act=async(action:string,note='')=>{setActionBusy(true);try{await api.caseAction(caseId,action,{note});message.success('案件流程已更新');await load()}catch(e:any){message.error(e.message)}finally{setActionBusy(false)}}
  const uploadRevision=async(file:File)=>{
    if(!item?.credit_case_id){message.error('案件缺少有效信审版本，不能上传复审');return false}
    try{
      if(item.current_stage==='awaiting_business'||item.current_stage==='legal_review')await api.caseAction(caseId,'submit_revision')
      const result=await api.upload(file,{case_id:caseId,credit_case_id:item.credit_case_id,business_type:item.business_type,document_role:item.documents.length?'revision':'main'})
      message.success('修订文件已提交系统审查；审查完成后会自动交给信用审核专员复核。')
      setSelectedJob(result.job_id);await load()
    }catch(e:any){message.error(e.message||'上传失败')}
    return false
  }
  const openReport=async(jobId?:string)=>{if(!jobId)return;try{const r=await api.reviewDetail(jobId);setReport(r.report);setReportJob(jobId);setSelectedJob(jobId);setGate(r as ReviewGate)}catch(e:any){message.error(e.message)}}
  const compare=async()=>{const target=currentJob||activeJob;if(!target||!baseJob)return message.info('请选择一个历史版本和当前版本');try{setComparison(await api.compareVersions(target,baseJob))}catch(e:any){message.error(e.message)}}

  if(loading)return <div style={{textAlign:'center',padding:80}}><Spin size="large"/></div>
  if(!item)return <Empty description="案件不存在"/>

  const stageIndex=Math.max(0,stageOrder.indexOf(item.current_stage))
  const canReviewer=user?.role==='reviewer'; const canDirector=user?.role==='director'; const canFinal=user?.role==='admin'; const canBusiness=user?.role==='business'
  const findings=gate?.findings||[]
  const creditBlockers=findings.filter(f=>String(f.rule_id||'').startsWith('CREDIT_'))
  const pendingFindings=findings.filter(f=>!String(f.rule_id||'').startsWith('CREDIT_')&&f.action_status==='pending').length
  const pendingApprovals=(gate?.approvals||[]).filter(x=>x.status==='pending')
  const pendingMaterials=(gate?.material_requests||[]).filter(x=>x.status==='open')
  const gateCount=creditBlockers.length+pendingFindings+pendingApprovals.length+pendingMaterials.length
  const isCurrentVersion=currentDocument?.job_id===activeJob
  const actionHint=creditBlockers.length
    ? '当前版本存在信审边界阻断。请先确认合同文本是否真的超出已生效信审；信审阻断不能通过合同端审批或忽略。'
    : item.current_stage==='ai_review'
      ? '系统正在解析合同、校验底线条款与已绑定的信审边界。审查完成后会自动交给信用审核专员。'
    : item.current_stage==='awaiting_business'
        ? '请根据退回意见上传修订合同或补充附件；上传后系统会重新审查当前版本。'
        : item.current_stage==='draft'&&item.credit_case_id
          ? '已绑定生效信审版本，请上传主合同以启动系统审查。'
          : item.current_stage==='awaiting_credit'
            ? '该案件尚未绑定已生效信审版本，暂不能上传合同。'
        : canReviewer&&item.current_stage==='legal_review'
          ? '请先处理下方的风险处置、补件和例外审批门禁，再决定是否可签约或提交主管审批。'
          : item.current_stage==='legal_review'
            ? `当前由信用审核专员处理。你以${roleLabel(user?.role)}登录，可查看进度${canBusiness?'并上传修订文件':''}。`
            : `当前等待${item.current_stage==='approval'?'财务审批主管':item.current_stage==='final_approval'?'集团财务总监 / 最终审批人':'相关责任人'}处理。`

  const primaryAction = canBusiness && ['draft','awaiting_business'].includes(item.current_stage) && item.credit_case_id
    ? <Upload showUploadList={false} beforeUpload={file => uploadRevision(file as File)} accept=".docx,.pdf,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.bmp"><Button type="primary" icon={<UploadOutlined/>}>{item.documents.length?'上传修订合同':'上传主合同'}</Button></Upload>
    : canReviewer && item.current_stage === 'legal_review'
      ? gateCount ? <Button type="primary" onClick={() => openReport(activeJob)}>处理风险与门禁（{gateCount}）</Button> : <Button type="primary" loading={actionBusy} icon={<CheckCircleOutlined/>} onClick={() => act('ready_for_signing','信用审核专员复核完成，可进入签约交付。')}>确认可签约</Button>
      : canDirector && item.current_stage === 'approval'
        ? <Button type="primary" loading={actionBusy} icon={<CheckCircleOutlined/>} onClick={() => act('approve_for_signing','主管审批通过，可进入签约交付。')}>主管批准可签约</Button>
        : canFinal && item.current_stage === 'approval'
          ? <Button type="primary" loading={actionBusy} icon={<CheckCircleOutlined/>} onClick={() => act('approve_for_signing','最终审批通过，可进入签约交付。')}>批准可签约</Button>
          : canFinal && item.current_stage === 'final_approval'
            ? <Button type="primary" loading={actionBusy} icon={<CheckCircleOutlined/>} onClick={() => act('final_approve_for_signing','集团财务总监最终审批通过，可进入签约交付。')}>最终批准可签约</Button>
            : canReviewer && item.current_stage === 'ready_to_sign'
              ? <Button type="primary" loading={actionBusy} icon={<CheckCircleOutlined/>} onClick={() => act('archive','合同已签署，归档案件。')}>确认已签署并归档</Button>
              : activeJob ? <Button type="primary" onClick={() => openReport(activeJob)}>查看当前审查结果</Button> : null
  const secondaryActions = <Space wrap>
    {canReviewer && item.current_stage === 'legal_review' && <Button loading={actionBusy} onClick={() => act('request_material','请补充合同背景、报价或对方修改说明。')}>退回业务补件</Button>}
    {canReviewer && item.current_stage === 'legal_review' && <Button loading={actionBusy} icon={<SendOutlined/>} onClick={() => act('submit_approval','合同风险需要分级审批。')}>提交主管审批</Button>}
    {canDirector && item.current_stage === 'approval' && <><Button loading={actionBusy} onClick={() => act('return_to_reviewer','请根据主管意见修改审查结论。')}>退回审核员</Button><Button loading={actionBusy} onClick={() => act('return_to_business','请补充材料或上传修订合同。')}>退回业务补件</Button><Button loading={actionBusy} onClick={() => act('escalate_final','主管复核后上报集团财务总监最终审批。')}>上报最终审批</Button></>}
    {canFinal && ['approval','final_approval'].includes(item.current_stage) && <><Button loading={actionBusy} onClick={() => act('return_to_reviewer','请根据审批意见修改审查结论。')}>退回审核员</Button><Button loading={actionBusy} onClick={() => act('return_to_business','请补充材料或上传修订合同。')}>退回业务补件</Button></>}
    {canBusiness && item.credit_case_id && item.documents.length>0 && item.current_stage !== 'archived' && item.current_stage !== 'cancelled' && item.current_stage !== 'awaiting_business' && <Upload showUploadList={false} beforeUpload={file => uploadRevision(file as File)} accept=".docx,.pdf,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.bmp"><Button icon={<UploadOutlined/>}>上传修订合同</Button></Upload>}
  </Space>

  const documentTab=<>
    <Card className="case-gate-card" size="small" title={<Space><SafetyCertificateOutlined/>当前版本通关检查 {currentDocument&&<Tag color="blue">{currentDocument.version_label}</Tag>}</Space>} extra={gateLoading?<Spin size="small"/>:<Badge status={gateCount?'warning':'success'} text={gateCount?`尚有 ${gateCount} 项待处理`:'当前版本已无待处理门禁'}/>}>
      <Alert showIcon type={creditBlockers.length?'error':gateCount?'warning':'success'} message={actionHint} style={{marginBottom:14}}/>
      <div className="case-gate-grid">
        <div className={creditBlockers.length?'gate-item is-blocked':'gate-item'}><SafetyCertificateOutlined/><div><Text strong>信审边界</Text><Text type="secondary">{creditBlockers.length?`${creditBlockers.length} 项阻断，需修订合同或更新信审`:'已通过当前信审边界校验'}</Text></div></div>
        <div className={pendingFindings?'gate-item is-pending':'gate-item'}><ExclamationCircleOutlined/><div><Text strong>合同风险处置</Text><Text type="secondary">{pendingFindings?`${pendingFindings} 项需审核员留痕处理`:'当前版本的风险均已处置'}</Text></div></div>
        <div className={pendingMaterials.length?'gate-item is-pending':'gate-item'}><FileTextOutlined/><div><Text strong>待补材料</Text><Text type="secondary">{pendingMaterials.length?`${pendingMaterials.length} 项待补充或确认`:'无待补材料'}</Text></div></div>
        <div className={pendingApprovals.length?'gate-item is-pending':'gate-item'}><ClockCircleOutlined/><div><Text strong>条款例外审批</Text><Text type="secondary">{pendingApprovals.length?`${pendingApprovals.length} 项等待对应审批人`:'无待审批条款例外'}</Text></div></div>
      </div>
      {creditBlockers.length>0&&<div className="credit-blocker-list">{creditBlockers.map(blocker=><Alert key={blocker.finding_id} type="error" showIcon message={`${blocker.rule_id} · ${blocker.baseline||'超出已生效信审边界'}`} description={<><span>识别证据：{blocker.evidence||'—'}。 </span><b>不能采纳、忽略或走合同例外审批。</b>{canBusiness&&<span> 请修订合同后上传新版本；若业务确需放宽条件，请先发起新的客户信审。</span>}</>} />)}</div>}
      {activeJob&&<div className="case-gate-actions"><Button type="primary" onClick={()=>openReport(activeJob)}>打开当前版本审查报告</Button>{canBusiness&&item.current_stage!=='archived'&&item.current_stage!=='cancelled'&&<Upload showUploadList={false} beforeUpload={file=>uploadRevision(file as File)} accept=".docx,.pdf,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.bmp"><Button icon={<UploadOutlined/>}>上传新的修订版本</Button></Upload>}</div>}
    </Card>

    <Card className="case-documents-card" size="small" title="文件与版本">
      <Alert type="info" showIcon style={{marginBottom:12}} message="新修订版通过审查后会成为当前版本；历史版本仅用于对比和审计，不再阻塞当前版本的签约门禁。"/>
      <List dataSource={item.documents} locale={{emptyText:'尚未上传合同文件'}} renderItem={doc=><List.Item actions={[doc.job_id?<Button key="report" size="small" type="link" onClick={()=>openReport(doc.job_id)}>查看审查</Button>:null].filter(Boolean)}><List.Item.Meta avatar={<FileTextOutlined style={{fontSize:20,color:'#1677ff'}}/>} title={<Space wrap><Text strong>{doc.original_name}</Text><Tag>{doc.version_label}</Tag>{doc.is_current_version?<Tag color="blue">当前版本</Tag>:<Tag>历史版本</Tag>}<Tag>{doc.document_role}</Tag></Space>} description={<>{doc.review_status==='done'?<Tag color="green">审查完成</Tag>:doc.review_status?<Tag color="processing">{doc.review_status}</Tag>:<Tag>待审查</Tag>}　{doc.overall_level||'等待审查结果'}<br/><Text type="secondary">{fmtTime(doc.created_at)}</Text></>}/></List.Item>}/>
    </Card>

    {activeJob && isCurrentVersion && (
      <CaseWorkflowPanel jobId={activeJob}/>
    )}
  </>

  return <div className="case-detail-page">
    <div className="page-intro case-detail-intro"><div><Button type="link" icon={<ArrowLeftOutlined/>} onClick={onBack} style={{paddingLeft:0}}>返回合同案件</Button><Title level={3}>{item.customer_name} · 合同审查案件</Title><Text type="secondary">{item.case_id}　{item.request_note||'未填写申请说明'}</Text></div></div>
    <section className="case-context-strip" aria-label="案件处理摘要">
      <div><span>当前处理</span><strong>{stageLabel[item.current_stage]||item.current_stage}</strong><Text type="secondary">{roleLabel(item.responsible_role)} · {item.responsible_name||'系统分派中'}</Text></div>
      <div><span>当前版本</span><strong>{currentDocument?.version_label||'待上传'}</strong><Text type="secondary">{currentDocument?.original_name||'尚未上传主合同'}</Text></div>
      <div><span>通关状态</span><strong className={gateCount?'is-warning':'is-success'}>{gateCount?`待处理 ${gateCount} 项`:'门禁已完成'}</strong><Text type="secondary">{creditBlockers.length?'存在信审边界阻断':pendingFindings?'仍有风险待处置':pendingMaterials.length?'仍有材料待补齐':'可继续按流程推进'}</Text></div>
      <div><span>信审边界</span><strong>{item.credit_case_id?'已绑定':'未绑定'}</strong><Text type="secondary">{item.credit_case_id?'合同不得超出已生效条件':'需先完成客户信审'}</Text></div>
    </section>
    <Card className="case-next-action-card" title="当前最需要推进什么？"><div className="case-next-action"><div><Text type="secondary">当前卡点</Text><Title level={4}>{stageLabel[item.current_stage]||item.current_stage} · {item.responsible_name||roleLabel(item.responsible_role)}</Title><Text>{actionHint}</Text><div className="case-next-action-meta"><span>当前责任：{roleLabel(item.responsible_role)} · {item.responsible_name||'系统分派中'}</span><span>{gateCount?`尚有 ${gateCount} 项门禁待完成`:'当前版本门禁已完成'}</span></div></div><div className="case-next-action-buttons">{primaryAction}{secondaryActions}</div></div></Card>

    <Card className="case-stage-card"><Steps current={stageIndex} items={stageOrder.map(key=>({title:stageLabel[key]}))}/><Descriptions size="small" column={{xs:1,md:3}} style={{marginTop:20}}><Descriptions.Item label="当前阶段"><Tag color={item.current_stage==='ready_to_sign'?'green':item.current_stage==='awaiting_business'?'orange':'blue'}>{stageLabel[item.current_stage]||item.current_stage}</Tag></Descriptions.Item><Descriptions.Item label="当前责任"><Text strong>{roleLabel(item.responsible_role)} · {item.responsible_name||'系统自动分派中'}</Text></Descriptions.Item><Descriptions.Item label="已绑定信审版本">{item.credit_case_id?<Space><SafetyCertificateOutlined/>已绑定且作为审查边界</Space>:'未绑定'}</Descriptions.Item></Descriptions><Alert className="case-handoff-alert" showIcon type="info" message={`当前登录：${roleLabel(user?.role)}。${actionHint}`}/></Card>

    <Tabs items={[{key:'documents',label:`文件、门禁与协同 (${item.documents.length})`,children:documentTab},{key:'versions',label:'版本对比',children:<Card size="small" title="比较当前版本与历史版本"><Text type="secondary">版本对比只用于查看修订效果；签约门禁始终以标记为“当前版本”的最近审查结果为准。</Text><Space wrap style={{display:'flex',marginTop:16}}><Select placeholder="历史版本" style={{width:260}} value={baseJob||undefined} onChange={setBaseJob} options={item.documents.filter(d=>d.job_id&&d.review_status==='done'&&!d.is_current_version).map(d=>({value:d.job_id,label:`${d.version_label} · ${d.original_name}`}))}/><Select placeholder="当前版本" style={{width:260}} value={currentJob||activeJob||undefined} onChange={setCurrentJob} options={item.documents.filter(d=>d.job_id&&d.review_status==='done').map(d=>({value:d.job_id,label:`${d.version_label}${d.is_current_version?'（当前）':''} · ${d.original_name}`}))}/><Button onClick={compare}>开始对比</Button></Space>{comparison&&<Descriptions bordered size="small" column={1} style={{marginTop:16}}><Descriptions.Item label="新增风险">{comparison.new_risks?.join('、')||'无'}</Descriptions.Item><Descriptions.Item label="已消除风险">{comparison.resolved_risks?.join('、')||'无'}</Descriptions.Item><Descriptions.Item label="持续风险">{comparison.persisting_risks?.join('、')||'无'}</Descriptions.Item><Descriptions.Item label="变更条款">{comparison.changed_clauses?.join('、')||'无'}</Descriptions.Item></Descriptions>}</Card>},{key:'tasks',label:`案件待办 (${item.tasks.filter(task=>task.status==='open').length})`,children:<List bordered dataSource={item.tasks} locale={{emptyText:'当前没有案件级待办'}} renderItem={task=><List.Item><List.Item.Meta title={<Space><Tag color={task.status==='open'?'blue':'default'}>{task.status==='open'?'待处理':'已完成'}</Tag><Text strong>{task.title}</Text></Space>} description={<>{task.detail||'—'}<br/><Text type="secondary">{task.due_at?`截止 ${fmtTime(task.due_at)}`:`创建于 ${fmtTime(task.created_at)}`}</Text></>}/></List.Item>}/>} ,{key:'activity',label:'流程记录',children:<List dataSource={item.events} locale={{emptyText:'暂无流程记录'}} renderItem={event=><List.Item><List.Item.Meta title={event.message} description={<Text type="secondary">{fmtTime(event.created_at)} · {event.event_type}</Text>}/></List.Item>}/>}]} />
    <Modal open={!!report} onCancel={()=>setReport(null)} footer={null} width="96vw" style={{top:20}} destroyOnClose title={`审查报告 · ${item.documents.find(doc=>doc.job_id===reportJob)?.version_label||''}`}><>{report&&<ReportView report={report} jobId={reportJob} showLegacyWorkflow={false} showVersionCompare={false}/>}</></Modal>
  </div>
}
