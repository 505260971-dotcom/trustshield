import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Alert, Button, Empty, List, Space, Tag, Typography, message } from 'antd'
import {
  ArrowRightOutlined, AuditOutlined, ClockCircleOutlined, FileAddOutlined, FolderOpenOutlined,
  SafetyCertificateOutlined, TeamOutlined, UnorderedListOutlined, WarningOutlined,
} from '@ant-design/icons'
import { api } from '../services/api'
import type { CaseCenterItem, WorkItem } from '../types'
import { fmtTime } from '../components/common'
import { useAuth } from '../context/AuthContext'

const { Text } = Typography
type RoleKey = 'business'|'reviewer'|'director'|'admin'
type WorkbenchProps = { onCreate:()=>void; onOpenCase:(id:string)=>void; onNavigate:(path:string)=>void; canCreateContract:boolean }

const taskLabel:Record<string,string> = {credit_required:'信审前置',document_required:'材料待补',legal_review:'合同初审',material:'补件处理',approval:'分级审批',final_approval:'最终审批',credit_assessment:'信审评估',credit_returned:'信审退回修改',credit_material:'信审补材料',credit_director_review:'主管复核',credit_final_approval:'最终审批'}
const stageLabel:Record<string,string> = {draft:'待上传',awaiting_credit:'等待信审',ai_review:'AI 审查中',legal_review:'待初审',awaiting_business:'待业务补件',approval:'分级审批',ready_to_sign:'可签约',archived:'已归档'}
const priorityLabel:Record<string,string> = {urgent:'紧急',high:'高优先级',normal:'普通',low:'低'}

type RoleConfig = { eyebrow:string; title:string; description:string; action:string; actionPath:string; secondary:string; icon:ReactNode; metricLabel:string; guide:{title:string;detail:string}[]; empty:string }
const roles:Record<RoleKey,RoleConfig> = {
  business:{
    eyebrow:'业务申请工作台',title:'把交易需求推进到可签约',description:'从客户信审、合同申请到补件处理，所有需要你补充和确认的信息都集中在这里。',
    action:'发起合同申请',actionPath:'new',secondary:'查看我的案件',icon:<FileAddOutlined/>,metricLabel:'待我补充',
    guide:[{title:'先确认信审',detail:'合同申请必须绑定当前有效的客户信审版本。'},{title:'一次提交完整材料',detail:'主合同、订单、补充协议请放入同一案件。'},{title:'及时处理补件',detail:'补件完成后，案件将自动回到审查链路。'}],empty:'暂时没有需要补充的事项，可以发起新的合同申请。',
  },
  reviewer:{
    eyebrow:'信用审核工作台',title:'今天优先完成评估与初审',description:'先处理证据不足、Agent 建议待确认和高风险合同，把可解释的结论报送给主管。',
    action:'进入客户信审',actionPath:'credit',secondary:'查看风险矩阵',icon:<SafetyCertificateOutlined/>,metricLabel:'待评估 / 初审',
    guide:[{title:'核验证据与敞口',detail:'先确认财报、客户主体和 CRM/ERP 敞口快照是否可用。'},{title:'确认或修订建议',detail:'Agent 建议不适用时，修改条件并写明审核依据。'},{title:'处理合同初审',detail:'高风险合同先退补件或提交分级审批，避免带病流转。'}],empty:'当前没有待评估或待初审事项，可前往客户信审查看草稿。',
  },
  director:{
    eyebrow:'主管复核工作台',title:'聚焦需要你决策的风险',description:'优先复核审核专员已报送的信审条件、人工修订依据和主管级合同例外。',
    action:'查看风险矩阵',actionPath:'matrix',secondary:'查看合同案件',icon:<AuditOutlined/>,metricLabel:'待主管复核',
    guide:[{title:'看建议与最终条件的差异',detail:'重点关注人工放宽额度、账期或预付款时的证据和理由。'},{title:'确认风险处置路径',detail:'明确通过、拒绝或需要进一步补充的商业判断。'},{title:'上报最终审批',detail:'复核通过的信审将进入集团财务总监终审。'}],empty:'当前没有待主管复核事项，风险矩阵会持续汇总新进入的案件。',
  },
  admin:{
    eyebrow:'最终审批与治理工作台',title:'守住最终商业边界',description:'处理最终信审批核和重大合同事项，同时关注规则、组织和全量审计治理。',
    action:'打开组织与规则',actionPath:'admin',secondary:'查看风险矩阵',icon:<TeamOutlined/>,metricLabel:'待最终决策',
    guide:[{title:'确认最终商业边界',detail:'最终批核前关注主管意见、人工兜底依据与客户风险暴露。'},{title:'处理重大合同事项',detail:'仅处理进入最终审批层级的重大商业例外。'},{title:'治理组织与规则',detail:'维护成员角色、规则版本和审计可追溯性。'}],empty:'当前没有待最终决策事项，可进入组织与规则进行治理检查。',
  },
}

function priorityWeight(value:string){return ({urgent:0,high:1,normal:2,low:3} as Record<string,number>)[value] ?? 4}
function taskForRole(task:WorkItem,role:RoleKey){
  if(task.source_type==='credit'){
    if(role==='business')return ['draft','returned_to_business'].includes(task.current_stage)
    if(role==='reviewer')return ['draft','returned_to_reviewer'].includes(task.current_stage)
    if(role==='director')return task.current_stage==='pending_director'
    return task.current_stage==='pending_final'
  }
  if(role==='business')return ['material','document_required','credit_required'].includes(task.task_type)
  if(role==='reviewer')return ['legal_review','credit_required','material'].includes(task.task_type)
  return role==='admin'?['approval','final_approval'].includes(task.task_type):task.task_type==='approval'
}

export default function WorkbenchPage({onCreate,onOpenCase,onNavigate,canCreateContract}:WorkbenchProps){
  const {user}=useAuth()
  const role=(user?.role||'business') as RoleKey
  const config=roles[role]
  const [tasks,setTasks]=useState<WorkItem[]>([])
  const [cases,setCases]=useState<CaseCenterItem[]>([])
  const [loading,setLoading]=useState(true)
  const load=async()=>{setLoading(true);try{const [taskResult,caseResult]=await Promise.all([api.workItems(),api.caseCenter('mine')]);setTasks(taskResult.items||[]);setCases(caseResult.items||[])}catch(e:any){message.error(e.message||'工作台加载失败')}finally{setLoading(false)}}
  useEffect(()=>{load()},[])
  const queue=useMemo(()=>[...tasks].sort((a,b)=>priorityWeight(a.priority)-priorityWeight(b.priority)||Number(a.due_at||Infinity)-Number(b.due_at||Infinity)),[tasks])
  const keyTasks=queue.filter(task=>taskForRole(task,role))
  const highCount=keyTasks.filter(task=>['urgent','high'].includes(task.priority)).length
  const dueSoon=keyTasks.filter(task=>task.due_at&&task.due_at<Date.now()/1000+48*3600).length
  const primaryAction=()=>canCreateContract?onCreate():onNavigate(config.actionPath)
  const secondaryPath=role==='business'?'cases':role==='reviewer'?'matrix':role==='director'?'cases':'matrix'

  return <div className={'role-workbench role-'+role}>
    <section className="role-hero">
      <div className="role-hero-copy">
        <div className="role-eyebrow"><span className="role-eyebrow-icon">{config.icon}</span>{config.eyebrow}</div>
        <Typography.Title level={1}>你好，{user?.display_name||'同事'}<span>。</span></Typography.Title>
        <Typography.Paragraph>{config.title}</Typography.Paragraph>
        <Text>{config.description}</Text>
      </div>
      <div className="role-hero-actions">
        <div className="role-live"><span className={highCount?'live-dot is-alert':'live-dot'}/>{highCount?highCount+' 项高优先级待办':'当前没有高优先级待办'}</div>
        <Space wrap><Button type="primary" size="large" icon={canCreateContract?<FileAddOutlined/>:config.icon} onClick={primaryAction}>{config.action}</Button><Button size="large" icon={<FolderOpenOutlined/>} onClick={()=>onNavigate(secondaryPath)}>{config.secondary}</Button></Space>
      </div>
    </section>

    <section className="workbench-metrics" aria-label="工作台指标">
      <div className="metric-card metric-primary"><div className="metric-icon"><UnorderedListOutlined/></div><div><span>{config.metricLabel}</span><strong>{keyTasks.length}</strong><small>需要优先打开处理</small></div></div>
      <div className="metric-card"><div className="metric-icon"><WarningOutlined/></div><div><span>高优先级</span><strong>{highCount}</strong><small>{highCount?'请优先处理紧急与高风险事项':'当前队列状态平稳'}</small></div></div>
      <div className="metric-card"><div className="metric-icon"><ClockCircleOutlined/></div><div><span>48 小时内到期</span><strong>{dueSoon}</strong><small>请关注截止时间和补件节奏</small></div></div>
      <div className="metric-card"><div className="metric-icon"><FolderOpenOutlined/></div><div><span>{role==='business'?'进行中的申请':'我参与的案件'}</span><strong>{cases.length}</strong><small>进入案件可查看完整时间线</small></div></div>
    </section>

    <section className="workbench-main-grid">
      <div className="focus-queue">
        <div className="panel-heading"><div><span className="section-kicker">ACTION QUEUE</span><Typography.Title level={3}>优先处理</Typography.Title><Text>按照风险、时效和你的岗位职责排序。</Text></div><Button type="text" onClick={load}>刷新队列</Button></div>
        {loading?<div className="queue-skeleton"><i/><i/><i/></div>:keyTasks.length?<List className="task-queue" dataSource={keyTasks.slice(0,6)} renderItem={task=><List.Item>
          <div className="task-priority"><span className={'priority-dot priority-'+task.priority}/><span>{priorityLabel[task.priority]||'普通'}</span></div>
          <div className="task-copy"><div><Tag>{taskLabel[task.task_type]||task.task_type}</Tag><Text strong>{task.title}</Text></div><Text type="secondary">{task.customer_name} · {task.detail||'请进入案件查看处理要求'}</Text></div>
          <div className="task-meta"><Text type="secondary">{task.due_at?'截止 '+fmtTime(task.due_at):task.source_type==='credit'?'信审流程待处理':'暂无截止时间'}</Text><Button type="link" onClick={()=>task.source_type==='credit'?onNavigate('credit'):onOpenCase(task.case_id)}>处理 <ArrowRightOutlined/></Button></div>
        </List.Item>}/>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={config.empty}/>}
      </div>
      <aside className="role-guide">
        <div className="guide-head"><span className="section-kicker">ROLE PLAYBOOK</span><Typography.Title level={3}>本岗位处理顺序</Typography.Title></div>
        <div className="guide-steps">{config.guide.map((step,index)=><div className="guide-step" key={step.title}><span>{String(index+1).padStart(2,'0')}</span><div><Text strong>{step.title}</Text><Text type="secondary">{step.detail}</Text></div></div>)}</div>
        <Alert showIcon type={role==='business'?'info':'warning'} message={role==='business'?'信审是合同的前置条件':'只处理属于当前岗位的决策'} description={role==='business'?'合同必须绑定同一客户的当前已生效信审版本。':'所有审批和修订都将保留角色、意见与时间线，便于后续追溯。'}/>
      </aside>
    </section>

    <section className="case-overview">
      <div className="panel-heading compact"><div><span className="section-kicker">CASE PULSE</span><Typography.Title level={3}>{role==='business'?'我的申请进度':'我参与案件的动态'}</Typography.Title></div><Button type="link" onClick={()=>onNavigate('cases')}>进入合同案件 <ArrowRightOutlined/></Button></div>
      {loading?<div className="case-placeholder"/>:cases.length?<div className="case-pulse-grid">{cases.slice(0,4).map(item=><button className="case-pulse-item" key={item.case_id} onClick={()=>onOpenCase(item.case_id)}><div><span className={'stage-chip stage-'+item.current_stage}>{stageLabel[item.current_stage]||item.current_stage}</span><Text strong>{item.customer_name}</Text></div><Text type="secondary">{item.filename||'待上传合同文件'}</Text><footer><span>{item.open_tasks} 项待办</span><span>{item.overall_level||'等待审查'}</span></footer></button>)}</div>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={role==='business'?'还没有进行中的申请':'当前没有与你相关的进行中案件'}/>}
    </section>
  </div>
}
