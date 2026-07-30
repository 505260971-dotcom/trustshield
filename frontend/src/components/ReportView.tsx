import { useMemo, useRef, useState } from 'react'
import { Card, Row, Col, Statistic, Result, Tabs, Table, Descriptions, Empty, List, Button, Dropdown, Space, Typography, Alert, Tag, message, Modal, Input, Select } from 'antd'
import { DownloadOutlined, SafetyCertificateOutlined, ReloadOutlined, FileWordOutlined, TranslationOutlined, SwapOutlined, FileTextOutlined } from '@ant-design/icons'
import type { KnowledgeItem, Report, Risk, RuleItem } from '../types'
import { riskTableCols, clauseTableCols, overallColor, downloadText, roleRiskVisible, roleRiskHighlight } from './common'
import { useRole, ROLE_DESC } from '../context/RoleContext'
import { api } from '../services/api'
import TranslateModal from './TranslateModal'
import CaseWorkflowPanel from './CaseWorkflowPanel'

const { Text } = Typography

function highlightEvidence(text: string, evidence?: string) {
  const needle = (evidence || '').trim()
  if (!needle || needle.length < 3 || !text.includes(needle)) {
    return <Text style={{ whiteSpace: 'pre-wrap' }}>{text}</Text>
  }
  const parts = text.split(needle)
  return <Text style={{ whiteSpace: 'pre-wrap' }}>
    {parts.map((part, index) => (
      <span key={index}>
        {part}
        {index < parts.length - 1 && <mark style={{ background: '#fff1b8', padding: '0 2px' }}>{needle}</mark>}
      </span>
    ))}
  </Text>
}

export default function ReportView ({ report, onReset, jobId, showLegacyWorkflow=true, showVersionCompare=true }: { report: Report; onReset?: ()=>void; jobId?: string; showLegacyWorkflow?:boolean; showVersionCompare?:boolean }) {
  const { role } = useRole()
  const [transOpen, setTransOpen] = useState(false)
  const [exporting, setExporting] = useState<string>('')
  const [actionRisk, setActionRisk] = useState<Risk|null>(null)
  const [actionType, setActionType] = useState('adopt')
  const [actionReason, setActionReason] = useState('')
  const [editedSuggestion, setEditedSuggestion] = useState('')
  const [rules, setRules] = useState<RuleItem[]>([])
  const [actionBusy, setActionBusy] = useState(false)
  const [compareOpen, setCompareOpen] = useState(false)
  const [baselineId, setBaselineId] = useState('')
  const [comparison, setComparison] = useState<any>(null)
  const [similarCases, setSimilarCases] = useState<KnowledgeItem[]>([])
  const [activeLang, setActiveLang] = useState('en')
  const [focusClauseId, setFocusClauseId] = useState<string>('')
  const [mainTab, setMainTab] = useState('annotate')
  const clauseRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const sm = report.summary || {}
  const oc = overallColor(sm.overall_level)
  const jid = jobId || report._job_id

  const allRisks = report.risks || []
  const reviewHints = report.review_hints || []
  const visibleRisks = allRisks.filter(r => roleRiskVisible(r, role))
  const hidden = allRisks.length - visibleRisks.length

  const riskByClause = useMemo(() => {
    const map: Record<string, Risk[]> = {}
    for (const risk of visibleRisks) {
      const key = risk.clause_id || ''
      if (!map[key]) map[key] = []
      map[key].push(risk)
    }
    return map
  }, [visibleRisks])

  const exportMarkdown = () => {
    const L: string[] = []
    L.push(`# ${report.filename} 合同评审报告\n`)
    L.push(`**总体结论：${sm.overall_level}**  |  条款数：${sm.n_clauses}  |  风险数：${sm.n_risks}（高${sm.high} 中${sm.mid} 低${sm.low}）\n`)
    L.push(`\n## 一、合同关键字段\n`)
    const f = report.contract_fields || {}
    L.push(`- 我方：${f.our_party || '—'}  业务类型：${f.business_type || '—'}  有效期：${f.validity_years ?? '—'} 年`)
    L.push(`- 甲方：${f.parties?.['甲方']||'—'}  乙方：${f.parties?.['乙方']||'—'}`)
    L.push(`- 付款节点：${f.payment_terms || '—'}`)
    L.push(`\n## 二、风险清单\n`)
    for (const x of report.risks) {
      L.push(`### [${x.rule_id}] ${x.level}  （条款 ${x.clause_id} · 第 ${x.page} 页）`)
      L.push(`- 违反底限：${x.rule_baseline}`)
      L.push(`- 风险证据：${x.evidence || '—'}`)
      if (x.numeric_note) L.push(`- 数值依据：${x.numeric_note}`)
      L.push(`- 修改建议：${x.suggestion || '—'}\n`)
    }
    if (reviewHints.length) {
      L.push(`\n## 三、待人工确认（${reviewHints.length} 条）\n`)
      for (const x of reviewHints) {
        L.push(`- [${x.rule_id}] 条款 ${x.clause_id} · ${x.suggestion || '请核对原文及审批记录'}`)
      }
    }
    L.push(`\n## 四、审查链路（Agent 步骤）\n`)
    report.steps.forEach((s,i) => L.push(`${i+1}. ${s}`))
    downloadText(`${(report.filename||'report').replace(/\.[^.]+$/,'')}_审查报告.md`, L.join('\n'))
  }

  const exportWord = async (mode: 'revised'|'plain'|'bilingual', lang?: string) => {
    if (!jid) { message.warning('缺少任务 ID，无法导出 Word'); return }
    setExporting(mode + (lang || ''))
    try {
      const base = (report.filename||'report').replace(/\.[^.]+$/,'')
      const names = { revised: `${base}_修订建议稿.docx`, plain: `${base}_原文版.docx`, bilingual: `${base}_双语对照.docx` }
      await api.exportWord(jid, mode, names[mode], lang)
      message.success('Word 已开始下载')
    } catch (e:any) { message.error('导出失败：'+(e?.message||String(e))) }
    finally { setExporting('') }
  }
  const compareVersions = async () => {
    if (!jid || !baselineId.trim()) return message.warning('请输入上一版本任务 ID')
    try { setComparison(await api.compareVersions(jid, baselineId.trim())) }
    catch (e:any) { message.error(`版本比较失败：${e?.message || e}`) }
  }

  const jumpToClause = (clauseId: string) => {
    setFocusClauseId(clauseId)
    setMainTab('annotate')
    requestAnimationFrame(() => {
      clauseRefs.current[clauseId]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }

  const rowClass = (r: Risk) => {
    if (roleRiskHighlight(r, role)) return 'row-role-hl'
    if (r.severity === 'high') return 'row-high'
    if (focusClauseId && r.clause_id === focusClauseId) return 'row-role-hl'
    return ''
  }
  const canAct = ['信用审核专员','财务审批主管','集团财务总监 / 最终审批人'].includes(role)
  const openAction = (risk: Risk) => {
    setActionRisk(risk); setActionType('adopt'); setActionReason(''); setEditedSuggestion(risk.suggestion || ''); setSimilarCases([])
    if (!rules.length) api.rules().then(result => setRules(result.rules)).catch(() => {})
    if (jid && risk.finding_id) api.findingKnowledge(jid, risk.finding_id).then(result => setSimilarCases(result.items)).catch(() => {})
  }
  const submitAction = async () => {
    if (!jid || !actionRisk?.finding_id) { message.warning('当前风险项尚未同步到案件库'); return }
    if (!actionReason.trim()) { message.warning('请填写处置理由'); return }
    setActionBusy(true)
    try { await api.action(jid,actionRisk.finding_id,{action:actionType,reason:actionReason,edited_suggestion:actionType==='edit'?editedSuggestion:''}); actionRisk.action_status=actionType==='adopt'?'adopted':actionType==='ignore'?'ignored':'edited'; message.success('人工处置已记录并写入审计日志');setActionRisk(null);setActionReason('');setEditedSuggestion('') }
    catch(e:any){message.error('保存失败：'+e.message)} finally{setActionBusy(false)}
  }
  const columns = [...riskTableCols,
    {title:'定位',width:90,fixed:'right' as const,render:(_:any,r:Risk)=> <Button size="small" type="link" onClick={()=>jumpToClause(r.clause_id)}>原文</Button>},
    {title:'处置',width:160,fixed:'right' as const,render:(_:any,r:Risk)=>{const creditBlocked=r.rule_id?.startsWith('CREDIT_');return <Space direction="vertical" size={2}>{r.action_status&&<Tag color={r.action_status==='ignored'?'default':'green'}>{r.action_status==='ignored'?'已确认不适用':r.action_status}</Tag>}{creditBlocked?<Tag color="red">仅可更新信审后复审</Tag>:canAct&&<Button size="small" onClick={()=>openAction(r)}>处理风险</Button>}</Space>}}
  ]

  return (
    <>
      <Card style={{marginBottom:16}}>
        <Row gutter={16} align="middle">
          <Col flex="300px">
            <Result status={oc==='error'?'error':oc==='warning'?'warning':'success'}
              title={sm.overall_level} subTitle={report.filename} style={{padding:0}} />
          </Col>
          <Col flex="auto">
            <Row gutter={16}>
              <Col span={6}><Statistic title="条款数" value={sm.n_clauses}/></Col>
              <Col span={6}><Statistic title="风险条数" value={sm.n_risks} valueStyle={{color:'#cf1322'}}/></Col>
              <Col span={6}><Statistic title="高风险·阻断" value={sm.high} valueStyle={{color:'#cf1322'}}/></Col>
              <Col span={6}><Statistic title="脱敏实体数" value={report.masked_entities} prefix={<SafetyCertificateOutlined/>}/></Col>
            </Row>
          </Col>
        </Row>
      </Card>

      <Card title={`风险清单（${visibleRisks.length} 条${hidden>0?` · 当前视角已过滤 ${hidden} 条`:''}）`} extra={
        <Space wrap>
          <Dropdown menu={{items:[{key:'revised',label:'导出修订建议稿',icon:<FileWordOutlined/>,disabled:!jid},{key:'plain',label:'导出原文留档',icon:<FileTextOutlined/>,disabled:!jid},{key:'bilingual',label:`导出双语对照稿（${activeLang.toUpperCase()}）`,icon:<FileWordOutlined/>,disabled:!jid},{type:'divider'},{key:'markdown',label:'导出 Markdown',icon:<DownloadOutlined/>},{key:'json',label:'导出 JSON'}],onClick:({key})=>{if(key==='revised')exportWord('revised');else if(key==='plain')exportWord('plain');else if(key==='bilingual')exportWord('bilingual',activeLang);else if(key==='markdown')exportMarkdown();else if(key==='json')downloadText(`${report.filename}.json`, JSON.stringify(report,null,2),'application/json')}}}><Button icon={<DownloadOutlined/>} loading={!!exporting}>导出交付物</Button></Dropdown>
          <Select size="small" value={activeLang} style={{width:110}} onChange={setActiveLang}
            options={[{value:'en',label:'英语'},{value:'vi',label:'越南语'},{value:'ja',label:'日语'},{value:'es',label:'西语'}]} />
          {showVersionCompare&&<Button icon={<SwapOutlined/>} onClick={()=>{setCompareOpen(true);setComparison(null)}} disabled={!jid}>版本对比</Button>}
          <Button icon={<TranslationOutlined/>} onClick={()=>setTransOpen(true)} disabled={!jid}>翻译</Button>
          {onReset && <Button icon={<ReloadOutlined/>} onClick={onReset}>重新审查</Button>}
        </Space>
      }>
        <Alert type="info" showIcon style={{marginBottom:12}}
          message={<Space wrap>
            <Tag color="blue">{role}</Tag>
            <Text>{ROLE_DESC[role]}</Text>
            {jid ? <Text type="secondary">· 任务 {jid.slice(0,8)}</Text> : <Text type="warning">· 缺少 job_id（历史记录可能无法导出/翻译）</Text>}
          </Space>} />
        {report.credit_decision && <Alert type="success" showIcon style={{marginBottom:12}}
          message={`已绑定前置信审：${report.credit_decision.customer_name} · V${report.credit_decision.version}`}
          description={`最长账期 ${report.credit_decision.conditions?.max_payment_days||0} 天；交付前最低收款 ${report.credit_decision.conditions?.min_prepayment_ratio||0}%；额度上限 ${report.credit_decision.conditions?.max_credit_amount||0} ${report.credit_decision.conditions?.currency||'CNY'}。信审越界项不能在合同端处置或导出。`} />}
        {reviewHints.length > 0 && <Alert type="warning" showIcon style={{marginBottom:12}}
          message={`待人工确认 ${reviewHints.length} 条：模型未能确认主体、条件、否定或审批例外；该清单不计入已确认风险。`} />}

        <Tabs activeKey={mainTab} onChange={setMainTab} items={[
          { key:'annotate', label:'原文风险标注', children:
            <Row gutter={16}>
              <Col span={13} style={{maxHeight:520, overflow:'auto', paddingRight:8}}>
                {(report.clauses||[]).length ? report.clauses.map(clause => {
                  const risks = riskByClause[clause.id] || []
                  const focused = focusClauseId === clause.id
                  return <div key={clause.id} ref={el => { clauseRefs.current[clause.id] = el }}
                    style={{border: focused ? '1px solid #1677ff' : '1px solid #f0f0f0', borderRadius:8, padding:12, marginBottom:10, background: risks.length ? '#fff7e6' : '#fff'}}>
                    <Space style={{marginBottom:6}}><Tag color={risks.length?'orange':'default'}>{clause.id}</Tag><Text type="secondary">{clause.source_ref || `第 ${clause.start_page} 页`}</Text>{risks.map(r=><Tag key={r.rule_id+r.level} color="red">{r.rule_id}</Tag>)}</Space>
                    <div>{highlightEvidence(clause.text, risks[0]?.evidence)}</div>
                    {risks.map(r => <Alert key={(r.finding_id||'')+r.rule_id} style={{marginTop:8}} type={r.severity==='high'?'error':'warning'} showIcon
                      message={`${r.rule_id} · ${r.level}`} description={<><div>证据：{r.evidence||'—'}</div><div>建议：{r.suggestion||'—'}</div></>} />)}
                  </div>
                }) : <Empty description="无条款原文"/>}
              </Col>
              <Col span={11}>
                {visibleRisks.length ? <Table size="small" rowKey={(r:Risk)=>r.finding_id||r.clause_id+r.rule_id}
                  columns={columns} dataSource={visibleRisks} pagination={{pageSize:8}}
                  rowClassName={rowClass} scroll={{x:900}}
                  onRow={(r)=>({ onClick: ()=>jumpToClause(r.clause_id), style:{ cursor:'pointer' }})}/>
                  : <Empty description={hidden>0?'当前角色视角下无匹配风险':'未命中风险底线'}/>}
              </Col>
            </Row>
          },
          { key:'risks', label:`风险清单 (${visibleRisks.length})`, children:
            visibleRisks.length ? <Table size="small" rowKey={(r:Risk)=>r.finding_id||r.clause_id+r.rule_id}
              columns={columns} dataSource={visibleRisks} pagination={{pageSize:12}}
              rowClassName={rowClass} scroll={{x:1505}}/> : <Empty description={hidden>0?'当前角色视角下无匹配风险':'未命中风险底线'}/> },
          { key:'review', label:`待人工确认 (${reviewHints.length})`, children:
            reviewHints.length ? <Table size="small" rowKey={(r:Risk)=>`review-${r.clause_id}-${r.rule_id}`}
              columns={riskTableCols} dataSource={reviewHints} pagination={{pageSize:12}} scroll={{x:1365}}/>
              : <Empty description="强模型未发现需要人工补充确认的条款"/> },
          { key:'fields', label:'合同字段摘要', children:
            <Descriptions bordered column={2} size="small">
              <Descriptions.Item label="我方(立场)">{report.contract_fields?.our_party||'—'}</Descriptions.Item>
              <Descriptions.Item label="业务类型">{report.contract_fields?.business_type||'—'}</Descriptions.Item>
              <Descriptions.Item label="甲方">{report.contract_fields?.parties?.['甲方']||'—'}</Descriptions.Item>
              <Descriptions.Item label="乙方">{report.contract_fields?.parties?.['乙方']||'—'}</Descriptions.Item>
              <Descriptions.Item label="合同有效期(年)">{report.contract_fields?.validity_years ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="交易金额">{report.contract_fields?.total_amount ?? '—'} {report.contract_fields?.currency||''}</Descriptions.Item>
              <Descriptions.Item label="付款节点" span={2}>{report.contract_fields?.payment_terms||'—'}</Descriptions.Item>
            </Descriptions> },
          { key:'clauses', label:`条款列表 (${report.clauses.length})`, children:
            <Table size="small" rowKey="id" columns={clauseTableCols} dataSource={report.clauses} pagination={{pageSize:10}}/> },
          { key:'steps', label:`审查链路 (${report.steps.length})`, children:
            <List size="small" dataSource={report.steps} renderItem={(s:string, i:number)=>
              <List.Item><Text>{i+1}. {s}</Text></List.Item>}/> }
        ]}/>
      </Card>

      {showLegacyWorkflow && <CaseWorkflowPanel jobId={jid} />}

      <TranslateModal jobId={jid} open={transOpen} onClose={()=>setTransOpen(false)} onTranslated={(lang)=>setActiveLang(lang)} />
      <Modal title={`处置风险 ${actionRisk?.rule_id||''}`} open={!!actionRisk} onCancel={()=>setActionRisk(null)} onOk={submitAction} okText="确认提交" confirmLoading={actionBusy}>
        <Space direction="vertical" style={{width:'100%'}}><Button.Group><Button type={actionType==='adopt'?'primary':'default'} onClick={()=>setActionType('adopt')}>采用修改建议</Button><Button type={actionType==='ignore'?'primary':'default'} onClick={()=>setActionType('ignore')}>确认该风险不适用</Button><Button type={actionType==='edit'?'primary':'default'} onClick={()=>setActionType('edit')}>编辑后采用</Button></Button.Group>{actionType==='ignore'&&<Alert type="warning" showIcon message="此操作不会删除系统风险记录" description="请说明该规则不适用于当前合同的事实依据；处理结果将保留在案件审计记录中。"/>}{similarCases.length>0&&<Alert type="info" showIcon message={`相似已采纳案例（${similarCases.length}）`} description={<List size="small" dataSource={similarCases} renderItem={item=><List.Item><Text>{item.suggested_text || item.evidence || '历史案例'}</Text></List.Item>}/>}/>} {actionType==='edit'&&<><Select value={editedSuggestion || undefined} placeholder="选择该规则的红线改写模板" options={rules.filter(rule=>rule.id===actionRisk?.rule_id&&!!rule.template).map(rule=>({value:rule.template,label:rule.template}))} onChange={setEditedSuggestion}/><Input.TextArea value={editedSuggestion} onChange={e=>setEditedSuggestion(e.target.value)} placeholder="可在模板基础上编辑建议替换文本" rows={4}/></>}<Input.TextArea value={actionReason} onChange={e=>setActionReason(e.target.value)} placeholder="必填：说明处置依据、审批例外或业务原因" rows={4}/></Space>
      </Modal>
      {showVersionCompare&&<Modal title="合同版本对比" open={compareOpen} onCancel={()=>setCompareOpen(false)} onOk={compareVersions} okText="开始对比">
        <Input value={baselineId} onChange={event=>setBaselineId(event.target.value)} placeholder="输入上一版本的任务 ID" />
        {comparison && <div style={{marginTop:16}}><Text>新增风险：{comparison.new_risks?.join('、')||'无'}</Text><br/><Text>已消除风险：{comparison.resolved_risks?.join('、')||'无'}</Text><br/><Text>仍存在风险：{comparison.persisting_risks?.join('、')||'无'}</Text><br/><Text>变更条款：{comparison.changed_clauses?.join('、')||'无'}</Text>{comparison.review_scope?.mode==='incremental'&&<><br/><Tag color="blue">增量复审</Tag><Text> 实际复审变更条款 {comparison.review_scope.changed_clause_ids?.length||0} 条，附带上下文 {comparison.review_scope.context_clause_ids?.length||0} 条。</Text></>}</div>}
      </Modal>}
    </>
  )
}
