import { useEffect, useMemo, useState } from 'react'
import { Card, Row, Col, Statistic, Result, Tabs, Table, Descriptions, Empty, List, Button, Collapse, Dropdown, Space, Typography, Alert, Tag, message, Modal, Input, Select } from 'antd'
import { DownloadOutlined, SafetyCertificateOutlined, ReloadOutlined, FileWordOutlined, TranslationOutlined, SwapOutlined, FileTextOutlined, LeftOutlined, RightOutlined, DashboardOutlined, RobotOutlined, WarningOutlined, ProfileOutlined, AuditOutlined } from '@ant-design/icons'
import type { KnowledgeItem, Report, Risk, RuleItem, SignabilityPlan as SignabilityPlanData, VersionComparison } from '../types'
import { riskTableCols, clauseTableCols, overallColor, downloadText, roleRiskVisible, roleRiskHighlight } from './common'
import { useRole, ROLE_DESC } from '../context/RoleContext'
import { api } from '../services/api'
import TranslateModal from './TranslateModal'
import CaseWorkflowPanel from './CaseWorkflowPanel'
import TaskContextBanner from './TaskContextBanner'
import ContractReviewWorkspace from './ContractReviewWorkspace'
import CaseReviewAssistant from './CaseReviewAssistant'
import { ContractDecisionSummary, VersionEffectSummary } from './ContractDecisionSummary'
import SignabilityPlan from './SignabilityPlan'

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
  const [comparison, setComparison] = useState<VersionComparison|null>(null)
  const [signability, setSignability] = useState<SignabilityPlanData|null>(null)
  const [signabilityLoading, setSignabilityLoading] = useState(false)
  const [similarCases, setSimilarCases] = useState<KnowledgeItem[]>([])
  const [activeLang, setActiveLang] = useState('en')
  const [focusClauseId, setFocusClauseId] = useState<string>('')
  const [focusRiskKey, setFocusRiskKey] = useState<string>('')
  const [mainTab, setMainTab] = useState('annotate')
  const [workspaceTab, setWorkspaceTab] = useState('overview')
  const sm = report.summary || {}
  const oc = overallColor(sm.overall_level)
  const jid = jobId || report._job_id

  const allRisks = report.risks || []
  const reviewHints = report.review_hints || []
  const visibleRisks = allRisks.filter(r => roleRiskVisible(r, role))
  const visiblePlanItems = signability?.items.filter(item => item.category !== 'contract' || visibleRisks.some(risk => risk.rule_id === item.rule_id))
  const hidden = allRisks.length - visibleRisks.length
  const riskKey = (risk: Risk) => risk.finding_id || `${risk.clause_id}-${risk.rule_id}-${risk.level}`
  const severityWeight: Record<string, number> = { high: 0, mid: 1, low: 2 }
  const orderedRisks = useMemo(() => [...visibleRisks].sort((a, b) => {
    const actionWeight = (risk: Risk) => risk.action_status === 'pending' || !risk.action_status ? 0 : 1
    return actionWeight(a) - actionWeight(b) || (severityWeight[a.severity] ?? 3) - (severityWeight[b.severity] ?? 3)
  }), [visibleRisks])
  const activeRisk = orderedRisks.find(risk => riskKey(risk) === focusRiskKey) || orderedRisks[0]
  const activeRiskIndex = activeRisk ? orderedRisks.findIndex(risk => riskKey(risk) === riskKey(activeRisk)) : -1
  const activeClause = activeRisk ? (report.clauses || []).find(clause => clause.id === activeRisk.clause_id) : undefined
  const reportContext = visibleRisks.length > 0
    ? `当前有 ${visibleRisks.length} 条风险，其中 ${visibleRisks.filter(risk => risk.severity === 'high').length} 条高风险；未处理和高风险项目会优先显示。`
    : reviewHints.length > 0
      ? '当前没有可以直接处理的风险，但仍有条款事实、主体或审批例外需要人工确认。'
      : '当前报告未发现需要处理的风险，可以继续核对合同信息、审查依据并导出文件。'
  const reportNextAction = visibleRisks.length > 0 ? '从左侧问题条款导航开始，逐条查看原文、依据和底线规则。' : reviewHints.length > 0 ? '先处理待人工确认事项，再决定是否可以继续签署。' : '核对审查步骤和合同信息后导出文件留档。'

  useEffect(() => {
    let cancelled = false
    if (!jid) { setSignability(null); return () => { cancelled = true } }
    setSignabilityLoading(true)
    api.signability(jid).then(result => { if (!cancelled) setSignability(result) }).catch(() => { if (!cancelled) setSignability(null) }).finally(() => { if (!cancelled) setSignabilityLoading(false) })
    return () => { cancelled = true }
  }, [jid])

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
    L.push(`\n## 四、Agent 审查步骤\n`)
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
    if (!jid || !baselineId.trim()) return message.warning('请输入上一版本的任务 ID')
    try { setComparison(await api.compareVersions(jid, baselineId.trim())) }
    catch (e:any) { message.error(`版本比较失败：${e?.message || e}`) }
  }

  const selectRisk = (risk: Risk) => {
    setFocusRiskKey(riskKey(risk))
    setFocusClauseId(risk.clause_id)
    setWorkspaceTab('risks')
    setMainTab('annotate')
    window.setTimeout(() => document.getElementById('report-risk-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80)
  }
  const jumpToClause = (clauseId: string) => {
    const risk = orderedRisks.find(item => item.clause_id === clauseId)
    if (risk) selectRisk(risk)
    else { setFocusClauseId(clauseId); setMainTab('annotate') }
  }
  const moveRisk = (offset: number) => {
    if (!orderedRisks.length) return
    const next = Math.max(0, Math.min(orderedRisks.length - 1, (activeRiskIndex < 0 ? 0 : activeRiskIndex) + offset))
    selectRisk(orderedRisks[next])
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
    if (!jid || !actionRisk?.finding_id) { message.warning('当前风险项尚未同步到案件记录'); return }
    if (!actionReason.trim()) { message.warning('请填写处理理由'); return }
    setActionBusy(true)
    try { await api.action(jid,actionRisk.finding_id,{action:actionType,reason:actionReason,edited_suggestion:actionType==='edit'?editedSuggestion:''}); actionRisk.action_status=actionType==='adopt'?'adopted':actionType==='ignore'?'ignored':'edited'; message.success('人工处理结果已记录');setActionRisk(null);setActionReason('');setEditedSuggestion('') }
    catch(e:any){message.error('保存失败：'+e.message)} finally{setActionBusy(false)}
  }
  const columns = [...riskTableCols,
    {title:'定位',width:90,fixed:'right' as const,render:(_:any,r:Risk)=> <Button size="small" type="link" onClick={()=>jumpToClause(r.clause_id)}>原文</Button>},
    {title:'处理',width:160,fixed:'right' as const,render:(_:any,r:Risk)=>{const creditBlocked=r.rule_id?.startsWith('CREDIT_');return <Space direction="vertical" size={2}>{r.action_status&&<Tag color={r.action_status==='ignored'?'default':'green'}>{r.action_status==='ignored'?'已确认不适用':r.action_status}</Tag>}{creditBlocked?<Tag color="red">更新信用审核后再复审</Tag>:canAct&&<Button size="small" onClick={()=>openAction(r)}>处理风险</Button>}</Space>}}
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
              <Col span={6}><Statistic title="高风险/无法放行" value={sm.high} valueStyle={{color:'#cf1322'}}/></Col>
              <Col span={6}><Statistic title="已保护敏感信息" value={report.masked_entities} prefix={<SafetyCertificateOutlined/>}/></Col>
            </Row>
          </Col>
        </Row>
      </Card>

      <TaskContextBanner role={role} title="合同审查结果工作区" description={reportContext} nextAction={reportNextAction}/>

      <Tabs
        className="report-workspace-tabs"
        activeKey={workspaceTab}
        onChange={setWorkspaceTab}
        items={[
          {
            key: 'overview',
            label: <span className="report-workspace-tab-label"><DashboardOutlined />决策总览</span>,
            children: <div className="report-workspace-pane">
              <ContractDecisionSummary report={report} visibleRisks={visibleRisks} onSelectRisk={selectRisk} />
              <SignabilityPlan plan={signability} loading={signabilityLoading} items={visiblePlanItems} />
            </div>,
          },
          {
            key: 'ai',
            label: <span className="report-workspace-tab-label"><RobotOutlined />Agent 审查与依据</span>,
            children: <div className="report-workspace-pane report-ai-pane">
              {jid && (
                <ContractReviewWorkspace jobId={jid} report={report}/>
              )}
              <CaseReviewAssistant report={report} risks={visibleRisks} onSelectRisk={selectRisk} jobId={jid} />
            </div>,
          },
          {
            key: 'risks',
            label: <span className="report-workspace-tab-label"><WarningOutlined />风险处置 <em>{visibleRisks.length}</em></span>,
            children: <Card id="report-risk-card" title={`风险清单（${visibleRisks.length} 条${hidden>0?` · 当前角色未显示 ${hidden} 条`:''}）`} extra={
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
            message={`已绑定信用审核：${report.credit_decision.customer_name} · V${report.credit_decision.version}`}
          description={`最长账期 ${report.credit_decision.conditions?.max_payment_days||0} 天；交付前最低收款比例 ${report.credit_decision.conditions?.min_prepayment_ratio||0}%；额度上限 ${report.credit_decision.conditions?.max_credit_amount||0} ${report.credit_decision.conditions?.currency||'CNY'}。不符合信用审核条件的项目不能在合同端处理或导出。`} />}
        {reviewHints.length > 0 && <Alert type="warning" showIcon style={{marginBottom:12}}
          message={`待人工确认 ${reviewHints.length} 条：系统无法确认主体、条件、否定或审批例外；这些项目不计入已确认风险。`} />}

        <Tabs activeKey={mainTab} onChange={setMainTab} items={[
          { key:'annotate', label:'问题条款工作区', children:
            visibleRisks.length && activeRisk ? <section className="report-review-workspace">
              <aside className="report-issue-nav">
                <div className="report-issue-nav-head"><div><span className="card-kicker">问题列表</span><Text strong>问题条款导航</Text></div><Tag color="orange">{orderedRisks.length} 条</Tag></div>
                <Text type="secondary" className="report-issue-nav-tip">优先显示尚未处置的高风险；处理后可继续下一条。</Text>
                <div className="report-issue-nav-list">{orderedRisks.map((risk, index) => {
                  const selected = riskKey(risk) === riskKey(activeRisk)
                  const pending = risk.action_status === 'pending' || !risk.action_status
                  return <button type="button" key={riskKey(risk)} className={`report-issue-nav-item${selected ? ' active' : ''}`} onClick={() => selectRisk(risk)}>
                    <span className={`report-risk-dot ${risk.severity}`}></span><div><div><Text strong>#{index + 1} · {risk.clause_id || '未定位条款'}</Text><Tag color={risk.severity === 'high' ? 'red' : risk.severity === 'mid' ? 'orange' : 'blue'}>{risk.rule_id}</Tag></div><Text type="secondary">{risk.rule_baseline || risk.suggestion || '请核对条款内容'}</Text></div><em>{pending ? '待处理' : '已记录'}</em>
                  </button>
                })}</div>
              </aside>
              <div className="report-review-content">
                <section className="report-clause-focus">
                  <div className="report-clause-focus-head"><div><span className="card-kicker">当前条款</span><Space wrap><Tag color={activeRisk.severity === 'high' ? 'red' : activeRisk.severity === 'mid' ? 'orange' : 'blue'}>{activeRisk.level}</Tag><Text strong>{activeRisk.clause_id || '未定位条款'} · {activeRisk.rule_id}</Text><Text type="secondary">{activeClause?.source_ref || (activeClause ? `第 ${activeClause.start_page} 页` : '原文定位待确认')}</Text></Space></div><Space><Button size="small" icon={<LeftOutlined/>} disabled={activeRiskIndex <= 0} onClick={() => moveRisk(-1)}>上一条</Button><Button size="small" icon={<RightOutlined/>} iconPosition="end" disabled={activeRiskIndex >= orderedRisks.length - 1} onClick={() => moveRisk(1)}>下一条</Button></Space></div>
                  <div className="report-clause-original">{activeClause ? highlightEvidence(activeClause.text, activeRisk.evidence) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未找到对应的合同原文条款"/>}</div>
                </section>
                <section className="report-risk-resolution">
                  <div><span className="card-kicker">处理建议</span><Text strong>本条处理建议</Text></div>
                  <div className="report-risk-resolution-grid"><div><span>规则底线</span><p>{activeRisk.rule_baseline || '—'}</p></div><div><span>命中证据</span><p>{activeRisk.evidence || '—'}</p></div><div className="full"><span>建议修改</span><p>{activeRisk.suggestion || '系统未生成替换文本，请结合原文人工判断。'}</p></div>{activeRisk.numeric_note && <div className="full"><span>数值依据</span><p>{activeRisk.numeric_note}</p></div>}</div>
                  {activeRisk.rule_id?.startsWith('CREDIT_') ? <Alert type="error" showIcon message="该项不符合已生效的信用审核条件" description="不能在合同端采纳、忽略或通过例外审批放行；请更新客户信用审核后再复审合同。"/> : <div className="report-risk-resolution-action">{activeRisk.action_status ? <Tag color={activeRisk.action_status === 'ignored' ? 'default' : 'green'}>{activeRisk.action_status === 'ignored' ? '已确认不适用' : `已${activeRisk.action_status}`}</Tag> : <Tag color="orange">待人工处理</Tag>}<Text type="secondary">处理理由、编辑稿及相似案例会记录在当前案件中。</Text>{canAct && <Button type="primary" onClick={() => openAction(activeRisk)}>处理本条风险</Button>}</div>}
                </section>
              </div>
            </section> : <Empty description={hidden>0?'当前角色视角下无匹配风险':'未命中风险底线'}/>
          },
          { key:'risks', label:`风险清单 (${visibleRisks.length})`, children:
            visibleRisks.length ? <Table size="small" rowKey={(r:Risk)=>r.finding_id||r.clause_id+r.rule_id}
              columns={columns} dataSource={visibleRisks} pagination={{pageSize:12}}
              rowClassName={rowClass} scroll={{x:1505}}/> : <Empty description={hidden>0?'当前角色视角下无匹配风险':'未命中风险底线'}/> },
          { key:'review', label:`待人工确认 (${reviewHints.length})`, children:
            reviewHints.length ? <Table size="small" rowKey={(r:Risk)=>`review-${r.clause_id}-${r.rule_id}`}
              columns={riskTableCols} dataSource={reviewHints} pagination={{pageSize:12}} scroll={{x:1365}}/>
              : <Empty description="Agent 未发现需要人工补充确认的条款"/> },
        ]}/>
      </Card>,
          },
          {
            key: 'details',
            label: <span className="report-workspace-tab-label"><ProfileOutlined />合同明细</span>,
            children: <Card title="合同结构化明细" className="report-details-card">
              <Tabs items={[
                { key: 'fields', label: '合同信息', children: <Descriptions bordered column={2} size="small">
                  <Descriptions.Item label="我方(立场)">{report.contract_fields?.our_party||'—'}</Descriptions.Item>
                  <Descriptions.Item label="业务类型">{report.contract_fields?.business_type||'—'}</Descriptions.Item>
                  <Descriptions.Item label="甲方">{report.contract_fields?.parties?.['甲方']||'—'}</Descriptions.Item>
                  <Descriptions.Item label="乙方">{report.contract_fields?.parties?.['乙方']||'—'}</Descriptions.Item>
                  <Descriptions.Item label="合同有效期(年)">{report.contract_fields?.validity_years ?? '—'}</Descriptions.Item>
                  <Descriptions.Item label="交易金额">{report.contract_fields?.total_amount ?? '—'} {report.contract_fields?.currency||''}</Descriptions.Item>
                  <Descriptions.Item label="付款节点" span={2}>{report.contract_fields?.payment_terms||'—'}</Descriptions.Item>
                </Descriptions> },
                { key: 'clauses', label: `条款列表 (${report.clauses.length})`, children: <Table size="small" rowKey="id" columns={clauseTableCols} dataSource={report.clauses} pagination={{pageSize:10}}/> },
                { key: 'steps', label: `Agent 审查步骤 (${report.steps.length})`, children: <List size="small" dataSource={report.steps} renderItem={(s:string, i:number)=><List.Item><Text>{i+1}. {s}</Text></List.Item>}/> },
              ]}/>
            </Card>,
          },
          {
            key: 'audit',
            label: <span className="report-workspace-tab-label"><AuditOutlined />流程记录与审计</span>,
            children: showLegacyWorkflow
              ? <Collapse className="case-technical-collapse" defaultActiveKey={[]} items={[{key:'workflow',label:'系统运行记录与技术详情',children:<CaseWorkflowPanel jobId={jid}/>}]} />
              : <Empty description="当前页面未加载流程审计详情" />,
          },
        ]}
      />

      <TranslateModal jobId={jid} open={transOpen} onClose={()=>setTransOpen(false)} onTranslated={(lang)=>setActiveLang(lang)} />
      <Modal title={`处理风险 ${actionRisk?.rule_id||''}`} open={!!actionRisk} onCancel={()=>setActionRisk(null)} onOk={submitAction} okText="确认提交" confirmLoading={actionBusy}>
        <Space direction="vertical" style={{width:'100%'}}><Button.Group><Button type={actionType==='adopt'?'primary':'default'} onClick={()=>setActionType('adopt')}>采用修改建议</Button><Button type={actionType==='ignore'?'primary':'default'} onClick={()=>setActionType('ignore')}>确认该风险不适用</Button><Button type={actionType==='edit'?'primary':'default'} onClick={()=>setActionType('edit')}>编辑后采用</Button></Button.Group>{actionType==='ignore'&&<Alert type="warning" showIcon message="此操作不会删除系统风险记录" description="请说明该规则不适用于当前合同的事实依据；处理结果将保留在案件审计记录中。"/>}{similarCases.length>0&&<Alert type="info" showIcon message={`相似已采纳案例（${similarCases.length}）`} description={<List size="small" dataSource={similarCases} renderItem={item=><List.Item><Text>{item.suggested_text || item.evidence || '历史案例'}</Text></List.Item>}/>}/>} {actionType==='edit'&&<><Select value={editedSuggestion || undefined} placeholder="选择该规则的红线改写模板" options={rules.filter(rule=>rule.id===actionRisk?.rule_id&&!!rule.template).map(rule=>({value:rule.template,label:rule.template}))} onChange={setEditedSuggestion}/><Input.TextArea value={editedSuggestion} onChange={e=>setEditedSuggestion(e.target.value)} placeholder="可在模板基础上编辑建议替换文本" rows={4}/></>}<Input.TextArea value={actionReason} onChange={e=>setActionReason(e.target.value)} placeholder="必填：说明处置依据、审批例外或业务原因" rows={4}/></Space>
      </Modal>
      {showVersionCompare&&<Modal title="合同版本对比" open={compareOpen} onCancel={()=>setCompareOpen(false)} onOk={compareVersions} okText="开始对比">
        <Input value={baselineId} onChange={event=>setBaselineId(event.target.value)} placeholder="输入上一版本的任务 ID" />
        <VersionEffectSummary comparison={comparison} />
      </Modal>}
    </>
  )
}
