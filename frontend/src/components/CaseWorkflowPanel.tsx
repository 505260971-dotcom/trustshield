import { useEffect, useState } from 'react'
import { Alert, Button, Card, Input, List, Modal, Select, Space, Tag, Typography, Upload, message } from 'antd'
import { CheckOutlined, CloudUploadOutlined, PaperClipOutlined, SendOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import { useAuth } from '../context/AuthContext'
import type { ApprovalItem, MaterialRequest } from '../types'
import { fmtTime } from './common'

const { Text } = Typography

export default function CaseWorkflowPanel({ jobId }: { jobId?: string }) {
  const { user } = useAuth()
  const [approvals, setApprovals] = useState<ApprovalItem[]>([])
  const [materials, setMaterials] = useState<MaterialRequest[]>([])
  const [selectedApproval, setSelectedApproval] = useState<ApprovalItem | null>(null)
  const [selectedMaterial, setSelectedMaterial] = useState<MaterialRequest | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [oaFlowId, setOaFlowId] = useState('')
  const [oaFlow, setOaFlow] = useState<any>(null)
  const [oaRole, setOaRole] = useState('法务')
  const [oaDecision, setOaDecision] = useState('采纳')
  const [oaNote, setOaNote] = useState('')
  const [attachments, setAttachments] = useState<any[]>([])
  const [activeAtt, setActiveAtt] = useState<any>(null)

  const load = async () => {
    if (!jobId) return
    try {
      const [approvalResult, materialResult, attResult] = await Promise.all([
        api.approvals(jobId), api.materials(jobId), api.listAttachments(jobId).catch(()=>({items:[]}))
      ])
      setApprovals(approvalResult.items)
      setMaterials(materialResult.items)
      setAttachments(attResult.items || [])
    } catch (error: any) {
      message.error(`流程状态加载失败：${error?.message || error}`)
    }
  }

  useEffect(() => { load() }, [jobId])

  const canDecide = (item: ApprovalItem) => user?.role === 'admin' || user?.role === item.required_role
  const decide = async (decision: string) => {
    if (!jobId || !selectedApproval || !note.trim()) return message.warning('请填写审批意见')
    setBusy(true)
    try {
      await api.decideApproval(jobId, selectedApproval.approval_id, { decision, note })
      message.success('审批决定已记录')
      setSelectedApproval(null); setNote(''); load()
    } catch (error: any) { message.error(error?.message || '审批提交失败') } finally { setBusy(false) }
  }
  const resolve = async () => {
    if (!jobId || !selectedMaterial || !note.trim()) return message.warning('请填写材料说明')
    setBusy(true)
    try {
      await api.resolveMaterial(jobId, selectedMaterial.request_id, note)
      message.success('待补材料已标记为完成')
      setSelectedMaterial(null); setNote(''); load()
    } catch (error: any) { message.error(error?.message || '提交失败') } finally { setBusy(false) }
  }
  const upload = async (item: MaterialRequest, file: File) => {
    if (!jobId) return false
    setBusy(true)
    try { await api.uploadMaterial(jobId, item.request_id, file); message.success('附件已关联到待补材料'); load() }
    catch (error: any) { message.error(error?.message || '附件上传失败') }
    finally { setBusy(false) }
    return false
  }

  const pushOa = async () => {
    if (!jobId) return
    setBusy(true)
    try {
      const result = await api.oaCreateFlow({ job_id: jobId })
      setOaFlowId(result.flow_id)
      const flow = await api.oaGetFlow(result.flow_id)
      setOaFlow(flow)
      message.success(`已创建泛微 OA 演示流程 ${result.flow_id}`)
    } catch (e: any) { message.error(e?.message || '推送 OA 失败') }
    finally { setBusy(false) }
  }
  const submitOaDecision = async () => {
    if (!oaFlowId) return message.warning('请先创建 OA 流程')
    setBusy(true)
    try {
      const result = await api.oaDecision(oaFlowId, { role: oaRole, decision: oaDecision, note: oaNote })
      setOaFlow(await api.oaGetFlow(oaFlowId))
      message.success(`角色 ${oaRole} 已提交：${result.status}`)
    } catch (e: any) { message.error(e?.message || '提交决策失败') }
    finally { setBusy(false) }
  }
  const batchUpdateOa = async () => {
    if (!oaFlowId) return
    setBusy(true)
    try {
      const accepted = (oaFlow?.findings_preview || []).map((x: any) => ({
        finding_id: x.finding_id, rule_id: x.rule_id, suggestion: x.suggestion
      }))
      const result = await api.oaBatchUpdate(oaFlowId, accepted)
      setOaFlow(await api.oaGetFlow(oaFlowId))
      message.success(result.export_hint || '已批量挂载采纳建议')
    } catch (e: any) { message.error(e?.message || '批量更新失败') }
    finally { setBusy(false) }
  }
  const uploadAnnex = async (file: File) => {
    if (!jobId) return false
    setBusy(true)
    try {
      const item = await api.uploadAttachment(jobId, file, 'annex')
      message.success(`附件已上传：${item.original_name}`)
      load()
    } catch (e: any) { message.error(e?.message || '附件上传失败') }
    finally { setBusy(false) }
    return false
  }

  if (!jobId) return null
  const showWorkflow = approvals.length > 0 || materials.length > 0

  return <>
    {showWorkflow && <Card title="审批与待补材料" style={{ marginTop: 16 }}>
      {approvals.length > 0 && <>
        <Alert type={approvals.some(x => x.status === 'pending') ? 'warning' : 'success'} showIcon
          message={approvals.some(x => x.status === 'pending') ? '存在待审批的合同例外，未完成前不可导出可签约修订稿。' : '所有必需的合同例外审批均已有决定。'} />
        <List size="small" style={{ marginTop: 12 }} dataSource={approvals} renderItem={item => <List.Item actions={canDecide(item) && item.status === 'pending' ? [<Button size="small" icon={<SendOutlined />} onClick={() => { setSelectedApproval(item); setNote('') }}>处理审批</Button>] : []}>
          <List.Item.Meta title={<Space><Tag color={item.status === 'approved' ? 'green' : item.status === 'pending' ? 'orange' : 'red'}>{item.status}</Tag><Text strong>需 {item.required_role.toUpperCase()} 审批</Text></Space>}
            description={item.decision_note || `创建于 ${fmtTime(item.created_at)}`} />
        </List.Item>} />
      </>}
      {materials.length > 0 && <List size="small" style={{ marginTop: 12 }} header="待补材料" dataSource={materials} renderItem={item => <List.Item actions={item.status === 'open' ? [<Upload key="upload" showUploadList={false} beforeUpload={(file) => upload(item, file as File)}><Button size="small" icon={<PaperClipOutlined />} loading={busy}>补充附件</Button></Upload>, ...(user?.role !== 'business' ? [<Button key="resolve" size="small" icon={<CheckOutlined />} onClick={() => { setSelectedMaterial(item); setNote('') }}>确认材料</Button>] : [])] : []}>
        <List.Item.Meta title={<Space><Tag color={item.status === 'resolved' ? 'green' : 'blue'}>{item.status === 'resolved' ? '已完成' : '待补充'}</Tag>{item.title}</Space>} description={<><div>{item.detail}</div>{item.files?.map(file=><a key={file.file_id} href={api.materialFileUrl(jobId!, item.request_id, file.file_id)} target="_blank" rel="noreferrer"><PaperClipOutlined/> {file.original_name}</a>)}</>} />
      </List.Item>} />}
    </Card>}

    <Card title="案件附件（在线切换查阅）" style={{ marginTop: 16 }}
      extra={<Upload showUploadList={false} beforeUpload={(f)=>uploadAnnex(f as File)} accept=".docx,.pdf,.txt,.xlsx,.xls,.png,.jpg,.jpeg">
        <Button size="small" icon={<PaperClipOutlined/>} loading={busy}>上传附件</Button>
      </Upload>}>
      <Alert type="info" showIcon style={{marginBottom:12}} message="主合同走审查链路；附件仅做同案存档与条款预览，可在演示中切换查阅。" />
      {attachments.length ? <List size="small" dataSource={attachments}
        renderItem={item => <List.Item actions={[
          <Button key="v" size="small" type="link" onClick={()=>setActiveAtt(item)}>预览</Button>,
          <a key="d" href={api.attachmentDownloadUrl(jobId, item.file_id)} target="_blank" rel="noreferrer">下载</a>
        ]}>
          <List.Item.Meta title={<Space><Tag>{item.role||'annex'}</Tag>{item.original_name}</Space>}
            description={`${(item.preview||[]).length} 条预览条款 · ${fmtTime(item.created_at)}`} />
        </List.Item>} /> : <Text type="secondary">暂无附件</Text>}
      {activeAtt && <Card size="small" type="inner" title={`预览 · ${activeAtt.original_name}`} style={{marginTop:12}}
        extra={<Button size="small" type="link" onClick={()=>setActiveAtt(null)}>关闭</Button>}>
        <List size="small" dataSource={activeAtt.preview||[]} locale={{emptyText:'无预览'}}
          renderItem={(c:any)=><List.Item><Text type="secondary">{c.id} · {c.source_ref||''}</Text><div style={{whiteSpace:'pre-wrap'}}>{c.text}</div></List.Item>} />
      </Card>}
    </Card>

    <Card title="泛微 OA 集成（演示 Mock）" style={{ marginTop: 16 }}
      extra={<Button type="primary" icon={<CloudUploadOutlined/>} loading={busy} onClick={pushOa} disabled={!jobId}>推送到 OA</Button>}>
      <Alert type="info" showIcon style={{marginBottom:12}}
        message="黑客松 Mock：创建流程 → 角色决策 → 批量挂载已采纳建议。生产替换为泛微流程 API。" />
      {oaFlowId && <Space direction="vertical" style={{width:'100%'}}>
        <Text>流程号：<Text code>{oaFlowId}</Text> · 状态 <Tag color="blue">{oaFlow?.status||'—'}</Tag></Text>
        <Space wrap>
          <Select value={oaRole} style={{width:120}} onChange={setOaRole} options={['法务','总监','CEO'].map(x=>({value:x,label:x}))}/>
          <Select value={oaDecision} style={{width:120}} onChange={setOaDecision} options={['采纳','驳回','要求修改'].map(x=>({value:x,label:x}))}/>
          <Input style={{width:220}} placeholder="决策意见" value={oaNote} onChange={e=>setOaNote(e.target.value)}/>
          <Button loading={busy} onClick={submitOaDecision}>提交角色决策</Button>
          <Button loading={busy} onClick={batchUpdateOa}>批量更新原文建议</Button>
        </Space>
        {oaFlow?.role_decisions && Object.keys(oaFlow.role_decisions).length>0 &&
          <List size="small" header="角色决策" dataSource={Object.entries(oaFlow.role_decisions)}
            renderItem={([role, val]: any) => <List.Item><Tag>{role}</Tag>{(val as any).decision} · {(val as any).note||'无备注'}</List.Item>} />}
        {!!oaFlow?.findings_preview?.length &&
          <List size="small" header={`风险预览（${oaFlow.findings_preview.length}）`} dataSource={oaFlow.findings_preview}
            renderItem={(item:any)=><List.Item><Tag color="red">{item.rule_id}</Tag>{item.level} · {item.suggestion}</List.Item>} />}
      </Space>}
    </Card>

    <Modal title={`处理 ${selectedApproval?.required_role?.toUpperCase() || ''} 审批`} open={!!selectedApproval} onCancel={() => setSelectedApproval(null)} footer={<Space><Button onClick={() => setSelectedApproval(null)}>取消</Button><Button danger loading={busy} onClick={() => decide('rejected')}>驳回</Button><Button loading={busy} onClick={() => decide('changes_requested')}>要求改稿</Button><Button type="primary" loading={busy} onClick={() => decide('approved')}>批准例外</Button></Space>}>
      <Input.TextArea rows={4} value={note} onChange={event => setNote(event.target.value)} placeholder="必填：审批依据、边界或改稿要求" />
    </Modal>
    <Modal title="确认待补材料" open={!!selectedMaterial} onCancel={() => setSelectedMaterial(null)} onOk={resolve} confirmLoading={busy} okText="确认完成"><Input.TextArea rows={4} value={note} onChange={event => setNote(event.target.value)} placeholder="必填：已补充的材料、附件或核验结论" /></Modal>
  </>
}
