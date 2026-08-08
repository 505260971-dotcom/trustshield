import { useEffect, useMemo, useState } from 'react'
import { Alert, Badge, Button, Card, Collapse, Descriptions, Empty, Input, List, Modal, Select, Space, Spin, Steps, Statistic, Tabs, Tag, Typography, Upload, message } from 'antd'
import { ArrowLeftOutlined, CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined, FileTextOutlined, SafetyCertificateOutlined, SendOutlined, UploadOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import { useAuth } from '../context/AuthContext'
import type { CaseCenterDetail, CaseDocument, Report, VersionComparison } from '../types'
import { fmtTime } from '../components/common'
import CaseWorkflowPanel from '../components/CaseWorkflowPanel'
import ReportView from '../components/ReportView'
import TaskContextBanner from '../components/TaskContextBanner'
import { gateStateInfo } from '../components/workflow'
import ContractReviewWorkspace from '../components/ContractReviewWorkspace'
import { VersionEffectSummary } from '../components/ContractDecisionSummary'

const { Text, Title } = Typography
const stageOrder=['draft','awaiting_credit','ai_review','legal_review','awaiting_business','approval','final_approval','ready_to_sign','archived']
const stageLabel:Record<string,string>={draft:'待上传合同',awaiting_credit:'等待有效信用审核',ai_review:'系统审查中',legal_review:'信用审核专员复核',awaiting_business:'待业务补充材料',approval:'待主管审批',final_approval:'待最终审批',ready_to_sign:'审查完成，可进入签约',archived:'已签约归档'}
type ReviewGate={report:Report;findings:any[];approvals:any[];material_requests:any[]}

function roleLabel(role?:string){return ({business:'业务申请人',reviewer:'信用审核专员',director:'财务审批主管',final_approver:'集团财务总监（最终审批人）',admin:'系统管理员'} as Record<string,string>)[role||'']||'当前角色'}

export default function CaseDetailPage({caseId,onBack,onCreateCredit}:{caseId:string;onBack:()=>void;onCreateCredit?:(customerName:string)=>void}){
  const {user}=useAuth()
  const [item,setItem]=useState<CaseCenterDetail|null>(null)
  const [loading,setLoading]=useState(true)
  const [report,setReport]=useState<Report|null>(null)
  const [reportJob,setReportJob]=useState('')
  const [selectedJob,setSelectedJob]=useState('')
  const [gate,setGate]=useState<ReviewGate|null>(null)
  const [gateLoading,setGateLoading]=useState(false)
  const [gateError,setGateError]=useState(false)
  const [actionBusy,setActionBusy]=useState(false)
  const [baseJob,setBaseJob]=useState('')
  const [currentJob,setCurrentJob]=useState('')
  const [comparison,setComparison]=useState<VersionComparison|null>(null)

  const load=async()=>{setLoading(true);try{setItem(await api.caseCenterDetail(caseId))}catch(e:any){message.error(e.message||'案件加载失败')}finally{setLoading(false)}}
  useEffect(()=>{load();setReport(null);setReportJob('');setSelectedJob('');setGate(null)},[caseId])

  const currentDocument=useMemo<CaseDocument|undefined>(()=>{
    if(!item)return undefined
    return item.documents.find(doc=>doc.is_current_version)||item.documents.find(doc=>doc.document_role==='revision'||doc.document_role==='main')
  },[item])
  const activeJob=selectedJob||currentDocument?.job_id||''

  useEffect(()=>{
    if(!activeJob){setGateError(false);return}
    let cancelled=false
    setGateLoading(true);setGateError(false)
    api.reviewDetail(activeJob).then(value=>{if(!cancelled)setGate(value as ReviewGate)}).catch(()=>{if(!cancelled){setGate(null);setGateError(true)}}).finally(()=>{if(!cancelled)setGateLoading(false)})
    return()=>{cancelled=true}
  },[activeJob])

  const act=async(action:string,note='')=>{setActionBusy(true);try{await api.caseAction(caseId,action,{note});message.success('案件状态已更新');await load()}catch(e:any){message.error(e.message)}finally{setActionBusy(false)}}
  const rejectContract=()=>{let note='';Modal.confirm({title:'驳回本合同及当前放行申请？',content:<Input.TextArea autoFocus rows={4} placeholder="必填：说明驳回原因，信用审核专员和业务人员将据此处理。" onChange={event=>{note=event.target.value}}/>,okText:'确认驳回',okButtonProps:{danger:true},cancelText:'取消',onOk:async()=>{if(!note.trim())throw new Error('请填写驳回原因');await act('reject',note)}})}
  const uploadRevision=async(file:File)=>{
    if(!item?.credit_case_id){message.error('案件缺少有效的信用审核版本，不能上传复审');return false}
    try{
      if(item.current_stage==='awaiting_business'||item.current_stage==='legal_review')await api.caseAction(caseId,'submit_revision')
      const result=await api.upload(file,{case_id:caseId,credit_case_id:item.credit_case_id,business_type:item.business_type,document_role:item.documents.length?'revision':'main'})
      message.success('修订文件已提交系统审查；完成后会交给信用审核专员复核。')
      setSelectedJob(result.job_id);await load()
    }catch(e:any){message.error(e.message||'上传失败')}
    return false
  }
  const openReport=async(jobId?:string)=>{if(!jobId)return;try{const r=await api.reviewDetail(jobId);setReport(r.report);setReportJob(jobId);setSelectedJob(jobId);setGate(r as ReviewGate)}catch(e:any){message.error(e.message)}}
  const compare=async()=>{const target=currentJob||activeJob;if(!target||!baseJob)return message.info('请选择一个历史版本和当前版本');try{setComparison(await api.compareVersions(target,baseJob))}catch(e:any){message.error(e.message)}}

  if(loading)return <div style={{textAlign:'center',padding:80}}><Spin size="large"/></div>
  if(!item)return <Empty description="案件不存在"/>

  const stageIndex=Math.max(0,stageOrder.indexOf(item.current_stage))
  const canReviewer=user?.role==='reviewer'; const canDirector=user?.role==='director'; const canFinal=user?.role==='final_approver'; const canBusiness=user?.role==='business'
  const findings=gate?.findings||[]
  const creditBlockers=findings.filter(f=>String(f.rule_id||'').startsWith('CREDIT_'))
  const pendingFindings=findings.filter(f=>!String(f.rule_id||'').startsWith('CREDIT_')&&f.action_status==='pending').length
  const pendingApprovals=(gate?.approvals||[]).filter(x=>x.status==='pending')
  const pendingMaterials=(gate?.material_requests||[]).filter(x=>x.status==='open')
  const gateCount=creditBlockers.length+pendingFindings+pendingApprovals.length+pendingMaterials.length
  const gateInfo=gateError
    ? {state:'pending' as const,label:'放行条件暂不可用',color:'orange' as const,action:'刷新或重新打开案件',description:'当前版本的审查结果暂时无法读取，请刷新页面后再决定是否推进流程。'}
    : gateStateInfo({hasCredit:Boolean(item.credit_case_id),hasDocument:Boolean(currentDocument),gateCount,stage:item.current_stage,loading:gateLoading||Boolean(activeJob&&!gate)})
  const gateCountWithPrerequisite=gateCount+(!item.credit_case_id||(!currentDocument&&item.current_stage!=='archived')?1:0)
  // 差异化审批路径：由后端按“合同金额 + 已有敞口 vs 信审额度、风险处置
  // 与例外审批状态”自动判定，主管/审核员的放行按钮按档位唯一渲染。
  const routeSnapshot = item.route_snapshot || null
  const routeTier = routeSnapshot?.tier || ''
  const routeMeta = !routeSnapshot
    ? null
    : routeTier === 'fast'
      ? { tag: <Tag color="green">快速审批路径</Tag>, title: '本版本满足快速放行条件，主管批准后即可签约', alert: 'success' as const }
      : routeTier === 'standard'
        ? { tag: <Tag color="orange">需总监终审</Tag>, title: '本版本需集团财务总监最终审批', alert: 'warning' as const }
        : { tag: <Tag color="red">暂不能放行</Tag>, title: '本版本存在阻断事项，先修订合同或更新信用审核', alert: 'error' as const }
  const isCurrentVersion=currentDocument?.job_id===activeJob
  const actionHint=!item.credit_case_id
    ? '该案件尚未绑定已生效的信用审核版本，暂不能上传合同。请先完成客户信用审核，再回到本案件继续推进。'
    : creditBlockers.length
    ? '当前版本存在不符合信用审核条件的问题。请先确认合同文本是否确实超出已生效条件；这类问题不能在合同端审批或忽略。'
    : item.current_stage==='ai_review'
      ? '系统正在解析合同，并校验底线条款和已绑定的信用审核条件。完成后会交给信用审核专员复核。'
    : item.current_stage==='awaiting_business'
        ? '请根据退回意见上传修订合同或补充附件；上传后系统会重新审查当前版本。'
    : item.current_stage==='draft'&&item.credit_case_id
          ? '已绑定有效的信用审核版本，请上传主合同以启动系统审查。'
          : item.current_stage==='awaiting_credit'
            ? '该案件尚未绑定已生效的信用审核版本，暂不能上传合同。'
        : canReviewer&&item.current_stage==='legal_review'
          ? '请先处理下方的风险、补充材料和例外审批，再决定是否可以签约或提交主管审批。'
          : item.current_stage==='legal_review'
            ? `当前由信用审核专员处理。你以${roleLabel(user?.role)}登录，可查看进度${canBusiness?'并上传修订文件':''}。`
        : `当前等待${item.current_stage==='approval'?'财务审批主管':item.current_stage==='final_approval'?'集团财务总监（最终审批人）':'相关责任人'}处理。`

  const primaryAction = !item.credit_case_id && (canBusiness || canReviewer) && onCreateCredit
    ? <Button type="primary" icon={<SafetyCertificateOutlined/>} onClick={() => onCreateCredit(item.customer_name)}>先发起客户信用审核</Button>
    : canBusiness && ['draft','awaiting_business'].includes(item.current_stage) && item.credit_case_id
    ? <Upload showUploadList={false} beforeUpload={file => uploadRevision(file as File)} accept=".docx,.pdf,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.bmp"><Button type="primary" icon={<UploadOutlined/>}>{item.documents.length?'上传修订合同':'上传主合同'}</Button></Upload>
    : canReviewer && item.current_stage === 'legal_review'
      ? gateCount ? <Button type="primary" onClick={() => openReport(activeJob)}>处理风险与放行条件（{gateCount}）</Button> : routeTier === 'fast'
        ? <Button type="primary" loading={actionBusy} icon={<CheckCircleOutlined/>} onClick={() => act('ready_for_signing','快速路径：合同金额与既有敞口均在已生效信用边界内，风险、材料和例外均已闭环。')}>确认可签约（快速路径）</Button>
        : <Button type="primary" loading={actionBusy} icon={<CheckCircleOutlined/>} onClick={() => act('submit_approval','信用审核专员复核完成，提交财务审批主管复核。')}>提交主管复核</Button>
      : canDirector && item.current_stage === 'approval'
        ? routeTier === 'blocked'
          ? <Button type="primary" icon={<ExclamationCircleOutlined/>} onClick={() => openReport(activeJob)}>处理阻断事项</Button>
          : routeSnapshot?.requires_final
            ? <Button type="primary" loading={actionBusy} icon={<SendOutlined/>} onClick={() => act('escalate_final','主管复核后提交集团财务总监最终审批。')}>提交最终审批</Button>
            : <Button type="primary" loading={actionBusy} icon={<CheckCircleOutlined/>} onClick={() => act('approve_for_signing','主管审批通过，可进入签约交付。')}>主管批准可签约</Button>
        : canFinal && item.current_stage === 'final_approval'
            ? <Button type="primary" loading={actionBusy} icon={<CheckCircleOutlined/>} onClick={() => act('final_approve_for_signing','集团财务总监最终审批通过，可进入签约交付。')}>最终批准可签约</Button>
            : canBusiness && item.current_stage === 'ready_to_sign'
              ? <Button type="primary" loading={actionBusy} icon={<CheckCircleOutlined/>} onClick={() => act('archive','业务申请人确认合同已完成签署，归档案件。')}>确认已签署并归档</Button>
              : activeJob ? <Button type="primary" onClick={() => openReport(activeJob)}>查看当前审查结果</Button> : null
  const secondaryActions = <Space wrap>
    {canReviewer && item.current_stage === 'legal_review' && <Button loading={actionBusy} onClick={() => act('request_material','请补充合同背景、报价或对方修改说明。')}>退回业务补充材料</Button>}
    {canDirector && item.current_stage === 'approval' && <><Button loading={actionBusy} onClick={() => act('return_to_reviewer','请根据主管意见重新核对合同条款、授信条件和已纳入的外部公开信息。')}>退回审核专员</Button><Button loading={actionBusy} onClick={() => act('return_to_business','请补充材料或上传修订合同。')}>退回业务补充材料</Button><Button danger loading={actionBusy} onClick={rejectContract}>驳回合同</Button></>}
    {canFinal && item.current_stage === 'final_approval' && <><Button loading={actionBusy} onClick={() => act('return_to_reviewer','请根据最终审批意见重新核对合同条款、授信条件和已纳入的外部公开信息。')}>退回审核专员</Button><Button loading={actionBusy} onClick={() => act('return_to_business','请补充材料或上传修订合同。')}>退回业务补充材料</Button><Button danger loading={actionBusy} onClick={rejectContract}>驳回合同</Button></>}
    {canBusiness && item.credit_case_id && item.documents.length>0 && item.current_stage !== 'archived' && item.current_stage !== 'cancelled' && item.current_stage !== 'awaiting_business' && <Upload showUploadList={false} beforeUpload={file => uploadRevision(file as File)} accept=".docx,.pdf,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.bmp"><Button icon={<UploadOutlined/>}>上传修订合同</Button></Upload>}
  </Space>

  const documentTab=<>
    {activeJob&&item.current_stage==='ai_review'&&<ContractReviewWorkspace jobId={activeJob} onStatusChange={status=>{if(status.status!=='running')load()}}/>}
    <Card className={`case-gate-card gate-state-${gateInfo.state}`} size="small" title={<Space><SafetyCertificateOutlined/>当前版本放行条件检查 {currentDocument&&<Tag color="blue">{currentDocument.version_label}</Tag>}</Space>} extra={gateLoading?<Spin size="small"/>:<Badge status={gateInfo.state==='blocked'?'error':gateInfo.state==='passed'?'success':'warning'} text={gateInfo.state==='passed'?'当前版本已满足放行条件':gateInfo.label}/> }>
      {routeMeta && <Alert className="case-route-banner" showIcon type={routeMeta.alert} style={{marginBottom:14}}
        message={<Space wrap>{routeMeta.tag}<Text strong>{routeMeta.title}</Text></Space>}
        description={<div className="case-route-reasons">{(routeSnapshot?.reasons||[]).map((reason,index)=><div key={index}>{reason}</div>)}</div>} />}
      <Alert showIcon type={gateInfo.state==='blocked'?'error':gateInfo.state==='passed'?'success':'warning'} message={actionHint} style={{marginBottom:14}}/>
      {item.credit_binding?.stale&&<Alert showIcon type="warning" style={{marginBottom:14}} message={`绑定的信用审核版本 V${item.credit_binding.version} 已不是当前生效版本`} description={<><Text>本案件当时的审查依据仍保留该版本的快照，不会被新版本悄悄改写。</Text><br/><Text type="secondary">{item.credit_binding.reasons.join('；')}。请在签约/导出前上传修订合同，基于当前生效版本重新复审。</Text></>}/>}
      <div className="case-gate-grid">
        <div className={!item.credit_case_id||creditBlockers.length?'gate-item is-blocked':'gate-item is-passed'}><SafetyCertificateOutlined/><div><Text strong>信用审核条件</Text><Text type="secondary">{!item.credit_case_id?'未绑定已生效的信用审核版本':creditBlockers.length?`${creditBlockers.length} 项不符合条件，需修订合同或更新信用审核`:'已通过当前信用审核条件检查'}</Text></div></div>
        <div className={pendingFindings?'gate-item is-pending':'gate-item is-passed'}><ExclamationCircleOutlined/><div><Text strong>合同风险处理</Text><Text type="secondary">{pendingFindings?`${pendingFindings} 项需要审核员记录处理结果`:'当前版本的风险均已处理'}</Text></div></div>
        <div className={pendingMaterials.length?'gate-item is-pending':'gate-item is-passed'}><FileTextOutlined/><div><Text strong>待补材料</Text><Text type="secondary">{pendingMaterials.length?`${pendingMaterials.length} 项待补充或确认`:'无待补材料'}</Text></div></div>
        <div className={pendingApprovals.length?'gate-item is-pending':'gate-item is-passed'}><ClockCircleOutlined/><div><Text strong>条款例外审批</Text><Text type="secondary">{pendingApprovals.length?`${pendingApprovals.length} 项等待对应审批人`:'无待审批条款例外'}</Text></div></div>
      </div>
      {creditBlockers.length>0&&<div className="credit-blocker-list">{creditBlockers.map(blocker=><Alert key={blocker.finding_id} type="error" showIcon message={`${blocker.rule_id} · ${blocker.baseline||'不符合已生效的信用审核条件'}`} description={<><span>识别依据：{blocker.evidence||'—'}。 </span><b>不能采纳、忽略或通过合同例外审批绕过。</b>{canBusiness&&<span> 请修订合同后上传新版本；若业务确需放宽条件，请先发起新的客户信用审核。</span>}</>} />)}</div>}
    {activeJob&&<div className="case-gate-actions"><Button type="primary" onClick={()=>openReport(activeJob)}>打开当前版本审查报告</Button>{gateError&&<Button onClick={()=>window.location.reload()}>重新检查放行条件</Button>}{canBusiness&&item.current_stage!=='archived'&&item.current_stage!=='cancelled'&&<Upload showUploadList={false} beforeUpload={file=>uploadRevision(file as File)} accept=".docx,.pdf,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.bmp"><Button icon={<UploadOutlined/>}>上传新的修订版本</Button></Upload>}</div>}
    </Card>

    {gate?.report?.credit_decision&&<Card size="small" style={{marginBottom:12}} title="本合同引用的联网公开信息处理结果">
      <Alert type="info" showIcon style={{marginBottom:10}} message={`信用审核专员已确认 V${gate.report.credit_decision.version}`} description="这里只显示审核专员明确纳入本次信用判断的公开信息；合同审批人可据此作出通过、退回或驳回合同决定，无需重复审批信用审核版本。"/>
      {(gate.report.credit_decision.external_reviews||[]).length
        ? <List size="small" dataSource={gate.report.credit_decision.external_reviews||[]} renderItem={(review:any)=><List.Item><List.Item.Meta title={<Space wrap><Tag color={review.severity==='high'?'red':'orange'}>{review.code||'外部线索'}</Tag><Text strong>{review.title||'未命名公开线索'}</Text></Space>} description={<Space direction="vertical" size={2}><Text>{review.note||'审核专员已纳入本次信用判断。'}</Text>{review.source_url&&<a href={review.source_url} target="_blank" rel="noreferrer">打开公开来源</a>}</Space>}/></List.Item>}/>
        : <Text type="secondary">本信用审核未纳入联网公开风险线索。</Text>}
    </Card>}

    <Card className="case-documents-card" size="small" title="文件与版本">
      <Alert type="info" showIcon style={{marginBottom:12}} message="新修订版通过审查后会成为当前版本；历史版本仅用于对比和审计，不会影响当前版本的签约放行条件。"/>
      <List dataSource={item.documents} locale={{emptyText:'尚未上传合同文件'}} renderItem={doc=><List.Item actions={[doc.job_id?<Button key="report" size="small" type="link" onClick={()=>openReport(doc.job_id)}>查看审查</Button>:null].filter(Boolean)}><List.Item.Meta avatar={<FileTextOutlined style={{fontSize:20,color:'#1677ff'}}/>} title={<Space wrap><Text strong>{doc.original_name}</Text><Tag>{doc.version_label}</Tag>{doc.is_current_version?<Tag color="blue">当前版本</Tag>:<Tag>历史版本</Tag>}<Tag>{doc.document_role}</Tag></Space>} description={<>{doc.review_status==='done'?<Tag color="green">审查完成</Tag>:doc.review_status?<Tag color="processing">{doc.review_status}</Tag>:<Tag>待审查</Tag>}　{doc.overall_level||'等待审查结果'}<br/><Text type="secondary">{fmtTime(doc.created_at)}</Text></>}/></List.Item>}/>
    </Card>

    {(canReviewer||canFinal) && activeJob && isCurrentVersion && (
      <Collapse className="case-technical-collapse" items={[{key:'workflow',label:'Agent 运行记录与技术详情',children:<CaseWorkflowPanel jobId={activeJob}/>}]} />
    )}
  </>

  return <div className="case-detail-page">
    <div className="page-intro case-detail-intro"><div><Button type="link" icon={<ArrowLeftOutlined/>} onClick={onBack} style={{paddingLeft:0}}>返回合同案件</Button><Title level={3}>{item.customer_name} · 合同审查案件</Title><Text type="secondary">{item.case_id}　{item.request_note||'未填写申请说明'}</Text></div></div>
    <section className="case-context-strip" aria-label="案件处理摘要">
      <div><span>当前处理</span><strong>{stageLabel[item.current_stage]||item.current_stage}</strong><Text type="secondary">{roleLabel(item.responsible_role)} · {item.responsible_name||'系统分派中'}</Text></div>
      <div><span>当前版本</span><strong>{currentDocument?.version_label||'待上传'}</strong><Text type="secondary">{currentDocument?.original_name||'尚未上传主合同'}</Text></div>
      <div><span>放行状态</span><strong className={gateInfo.state==='blocked'?'is-danger':gateInfo.state==='passed'?'is-success':'is-warning'}>{gateInfo.label}</strong><Text type="secondary">{gateInfo.description}</Text></div>
      <div><span>信用审核条件</span><strong>{item.credit_binding?`已绑定 V${item.credit_binding.version}`:'未绑定'}</strong><Text type="secondary">{item.credit_binding?.stale?'历史审查依据保留原版本，签约前须重新复审':item.credit_case_id?'合同不得超出该版本已生效条件':'需先完成客户信用审核'}</Text></div>
    </section>
    <TaskContextBanner role={user?.role} title={gateInfo.label} description={actionHint} nextAction={gateInfo.action} />
    <Card className="case-next-action-card" title="当前最需要推进什么？"><div className="case-next-action"><div><Text type="secondary">当前问题</Text><Title level={4}>{stageLabel[item.current_stage]||item.current_stage} · {item.responsible_name||roleLabel(item.responsible_role)}</Title><Text>{actionHint}</Text><div className="case-next-action-meta"><span>当前责任：{roleLabel(item.responsible_role)} · {item.responsible_name||'系统分派中'}</span><span>{gateCountWithPrerequisite?`还有 ${gateCountWithPrerequisite} 项放行条件待完成`:gateInfo.label}</span></div></div><div className="case-next-action-buttons">{primaryAction}{secondaryActions}</div></div></Card>

    {gate?.report && <Card className="case-summary-card" title="合同审查摘要" extra={<Button type="link" onClick={()=>openReport(activeJob)}>打开完整审查报告</Button>}>
      <div className="case-summary-metrics"><Statistic title="风险总数" value={gate.report.summary?.n_risks||0}/><Statistic title="高风险 / 阻断" value={gate.report.summary?.high||0} valueStyle={{color:'#cf1322'}}/><Statistic title="中风险" value={gate.report.summary?.mid||0} valueStyle={{color:'#d48806'}}/><Statistic title="待人工确认" value={gate.report.summary?.n_needs_review||gate.report.review_hints?.length||0} valueStyle={{color:'#b47514'}}/></div>
      <div className="case-summary-basis"><Text type="secondary">审查依据：</Text><Tag color="blue">合同原文与附件</Tag>{gate.report.credit_decision&&<Tag color="cyan">已生效信用审核 V{gate.report.credit_decision.version}</Tag>}<Tag>合同底线规则</Tag><Tag>风险条款知识库</Tag></div>
      <Alert type={(gate.report.summary?.high||0)>0?'warning':'success'} showIcon message={(gate.report.summary?.high||0)>0?`当前仍有 ${gate.report.summary?.high||0} 条高风险或阻断事项需要处理`:'当前报告未发现高风险阻断'} description="进入完整报告后可以逐条查看原文、命中证据、规则依据和人工处置留痕。" />
    </Card>}

    <Card className="case-stage-card"><Steps current={stageIndex} items={stageOrder.map(key=>({title:stageLabel[key]}))}/><Descriptions size="small" column={{xs:1,md:3}} style={{marginTop:20}}><Descriptions.Item label="当前阶段"><Tag color={item.current_stage==='ready_to_sign'?'green':item.current_stage==='awaiting_business'?'orange':'blue'}>{stageLabel[item.current_stage]||item.current_stage}</Tag></Descriptions.Item><Descriptions.Item label="当前责任"><Text strong>{roleLabel(item.responsible_role)} · {item.responsible_name||'系统自动分派中'}</Text></Descriptions.Item><Descriptions.Item label="已绑定信用审核版本">{item.credit_case_id?<Space><SafetyCertificateOutlined/>已绑定并作为审查条件</Space>:'未绑定'}</Descriptions.Item></Descriptions><Alert className="case-handoff-alert" showIcon type="info" message={`当前登录：${roleLabel(user?.role)}。${actionHint}`}/></Card>

    <Tabs items={[{key:'documents',label:`文件、放行条件与协同 (${item.documents.length})`,children:documentTab},{key:'versions',label:'版本对比',children:<Card size="small" title="比较当前版本与历史版本"><Text type="secondary">版本对比只用于查看修订效果；签约放行条件始终以标记为“当前版本”的最近审查结果为准。</Text><Space wrap style={{display:'flex',marginTop:16}}><Select placeholder="历史版本" style={{width:260}} value={baseJob||undefined} onChange={setBaseJob} options={item.documents.filter(d=>d.job_id&&d.review_status==='done'&&!d.is_current_version).map(d=>({value:d.job_id,label:`${d.version_label} · ${d.original_name}`}))}/><Select placeholder="当前版本" style={{width:260}} value={currentJob||activeJob||undefined} onChange={setCurrentJob} options={item.documents.filter(d=>d.job_id&&d.review_status==='done').map(d=>({value:d.job_id,label:`${d.version_label}${d.is_current_version?'（当前）':''} · ${d.original_name}`}))}/><Button onClick={compare}>开始对比</Button></Space><VersionEffectSummary comparison={comparison}/></Card>},{key:'tasks',label:`案件待办 (${item.tasks.filter(task=>task.status==='open').length})`,children:<List bordered dataSource={item.tasks} locale={{emptyText:'当前没有案件级待办'}} renderItem={task=><List.Item><List.Item.Meta title={<Space><Tag color={task.status==='open'?'blue':'default'}>{task.status==='open'?'待处理':'已完成'}</Tag><Text strong>{task.title}</Text></Space>} description={<>{task.detail||'—'}<br/><Text type="secondary">{task.due_at?`截止 ${fmtTime(task.due_at)}`:`创建于 ${fmtTime(task.created_at)}`}</Text></>}/></List.Item>}/>} ,{key:'activity',label:'流程记录',children:<List dataSource={item.events} locale={{emptyText:'暂无流程记录'}} renderItem={event=><List.Item><List.Item.Meta title={event.message} description={<Text type="secondary">{fmtTime(event.created_at)} · {event.event_type}</Text>}/></List.Item>}/>}]} />
    <Modal open={!!report} onCancel={()=>setReport(null)} footer={null} width="96vw" style={{top:20}} destroyOnClose title={`审查报告 · ${item.documents.find(doc=>doc.job_id===reportJob)?.version_label||''}`}><>{report&&<ReportView report={report} jobId={reportJob} showLegacyWorkflow={false} showVersionCompare={false}/>}</></Modal>
  </div>
}
