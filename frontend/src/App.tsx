import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Badge, Button, Drawer, Layout, List, Menu, Space, Spin, Tag, Typography } from 'antd'
import { BookOutlined, ControlOutlined, DashboardOutlined, FileAddOutlined, FolderOpenOutlined, ReloadOutlined, SafetyCertificateOutlined, SettingOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { api } from './services/api'
import type { HealthInfo, RuleItem } from './types'
import { AuthProvider, useAuth } from './context/AuthContext'
import { RoleProvider, useRole } from './context/RoleContext'
import LoginPage from './pages/LoginPage'
import ReviewPage from './pages/ReviewPage'
import AdminPage from './pages/AdminPage'
import SettingsPage from './pages/SettingsPage'
import KnowledgePage from './pages/KnowledgePage'
import BatchMatrixPage from './pages/BatchMatrixPage'
import CreditPage from './pages/CreditPage'
import WorkbenchPage from './pages/WorkbenchPage'
import CaseCenterPage from './pages/CaseCenterPage'
import CaseDetailPage from './pages/CaseDetailPage'
import { approvalRoleLabel } from './components/common'

const {Sider,Header,Content}=Layout; const {Title,Text}=Typography
type Route={page:string;caseId?:string}
const parseRoute=():Route=>{const value=window.location.hash.replace(/^#/,'')||'/workbench';const parts=value.split('/').filter(Boolean);return parts[0]==='cases'&&parts[1]?{page:'case',caseId:parts[1]}:{page:parts[0]||'workbench'}}
const routeTitle:Record<string,string>={workbench:'我的工作台',cases:'合同案件中心',new:'发起合同申请',case:'合同案件',credit:'客户信审',matrix:'风险矩阵',knowledge:'条款知识库',admin:'组织与规则',settings:'系统设置'}

function AppInner(){
 const {user,loading,logout}=useAuth(); const {role}=useRole(); const [route,setRoute]=useState<Route>(parseRoute()); const [health,setHealth]=useState<HealthInfo|null>(null);const [rules,setRules]=useState<RuleItem[]>([]);const [rulesOpen,setRulesOpen]=useState(false)
 const go=(path:string)=>{window.location.hash=path}
 useEffect(()=>{const handler=()=>setRoute(parseRoute());window.addEventListener('hashchange',handler);return()=>window.removeEventListener('hashchange',handler)},[])
 const ping=async()=>{try{setHealth(await api.health())}catch{setHealth({ollama:false,llm:false} as HealthInfo)}}
 useEffect(()=>{if(user){ping();api.rules().then(r=>setRules(r.rules)).catch(()=>{})}},[user])
 const menu=useMemo(()=>{if(!user)return[];const base=[{key:'workbench',icon:<DashboardOutlined/>,label:'我的工作台'},{key:'cases',icon:<FolderOpenOutlined/>,label:'合同案件'},{key:'credit',icon:<SafetyCertificateOutlined/>,label:user.role==='business'?'我的信审申请':'客户信审'}];if(['business','reviewer','admin'].includes(user.role))base.push({key:'new',icon:<FileAddOutlined/>,label:'发起合同申请'});if(['reviewer','director','admin'].includes(user.role))base.push({key:'matrix',icon:<UnorderedListOutlined/>,label:'风险矩阵'});if(['reviewer','director','admin'].includes(user.role))base.push({key:'knowledge',icon:<BookOutlined/>,label:'条款知识库'});if(user.role==='admin')base.push({key:'admin',icon:<SettingOutlined/>,label:'组织与规则'},{key:'settings',icon:<ControlOutlined/>,label:'系统设置'});return base},[user])
 if(loading)return <div className="boot"><Spin size="large"/></div>; if(!user)return <LoginPage/>
 const current=route.page==='case'?'cases':route.page
 const openCase=(id:string)=>go(`/cases/${id}`)
 let page:ReactNode
 if(route.page==='workbench')page=<WorkbenchPage onCreate={()=>go('/new')} onOpenCase={openCase}/>
 else if(route.page==='cases')page=<CaseCenterPage onCreate={()=>go('/new')} onOpen={openCase}/>
 else if(route.page==='case'&&route.caseId)page=<CaseDetailPage caseId={route.caseId} onBack={()=>go('/cases')}/>
 else if(route.page==='new')page=<ReviewPage onCreated={openCase}/>
 else if(route.page==='credit')page=<CreditPage/>
 else if(route.page==='matrix')page=<BatchMatrixPage/>
 else if(route.page==='knowledge')page=<KnowledgePage/>
 else if(route.page==='admin'&&user.role==='admin')page=<AdminPage/>
 else if(route.page==='settings'&&user.role==='admin')page=<SettingsPage onSaved={ping}/>
 else page=<WorkbenchPage onCreate={()=>go('/new')} onOpenCase={openCase}/>
  return <Layout style={{minHeight:'100vh'}}>
    <Sider collapsible theme="dark" width={224}>
      <div className="brand"><SafetyCertificateOutlined/><span>ContractGuard</span></div>
      <Menu theme="dark" mode="inline" selectedKeys={[current]} items={menu} onSelect={e=>go(`/${e.key}`)}/>
      <div className="sider-foot"><Text>合同协同与风险控制</Text></div>
    </Sider>
    <Layout>
      <Header className="workspace-header"><Title level={4} style={{margin:0}}>{routeTitle[route.page]||'ContractGuard'}</Title><Space><Tag color="blue">{role}</Tag><Text>{user.display_name}</Text><Badge status={health?.llm?'success':'warning'} text={health?.llm?'模型在线':'模型未配置'}/><Button size="small" icon={<ReloadOutlined/>} onClick={ping}>检测</Button><Button size="small" icon={<BookOutlined/>} onClick={()=>setRulesOpen(true)}>规则库</Button><Button size="small" onClick={logout}>退出</Button></Space></Header>
      <Content className="workspace-content">{page}</Content>
    </Layout>
    <Drawer title="合同规则库" open={rulesOpen} onClose={()=>setRulesOpen(false)} width={620}><List dataSource={rules} renderItem={r=><List.Item><List.Item.Meta avatar={<Tag color={r.severity==='high'?'red':'orange'}>{r.id}</Tag>} title={<Text strong>{r.baseline}</Text>} description={<><Text type="secondary">适用：{r.applies_to?.join('、')||'全部'}　{r.approval_role?`例外审批：${approvalRoleLabel(r.approval_role)}`:'无需例外审批'}</Text><br/><Text type="secondary">判定：{r.check}</Text></>}/></List.Item>}/></Drawer>
  </Layout>
}
export default function App(){return <AuthProvider><RoleProvider><AppInner/></RoleProvider></AuthProvider>}
