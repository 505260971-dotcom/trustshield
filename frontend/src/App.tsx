import { useEffect, useState } from 'react'
import { Badge, Button, Drawer, Layout, List, Menu, Space, Spin, Tag, Typography } from 'antd'
import { BookOutlined, ControlOutlined, DashboardOutlined, FileAddOutlined, LogoutOutlined, ReloadOutlined, SafetyCertificateOutlined, SettingOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { api } from './services/api'
import type { HealthInfo, RuleItem } from './types'
import { AuthProvider, useAuth } from './context/AuthContext'
import { RoleProvider, useRole } from './context/RoleContext'
import LoginPage from './pages/LoginPage'
import ReviewPage from './pages/ReviewPage'
import DashboardPage from './pages/DashboardPage'
import AdminPage from './pages/AdminPage'
import HistoryDetail from './components/HistoryDetail'
import CaseBoardPage from './pages/CaseBoardPage'
import SettingsPage from './pages/SettingsPage'
import KnowledgePage from './pages/KnowledgePage'
import BatchMatrixPage from './pages/BatchMatrixPage'
import CreditPage from './pages/CreditPage'
const {Sider,Header,Content}=Layout;const {Title,Text}=Typography
type Tab='dashboard'|'credit'|'review'|'cases'|'matrix'|'knowledge'|'admin'|'settings'
function AppInner(){
 const {user,loading,logout}=useAuth(); const {role}=useRole();const [tab,setTab]=useState<Tab>('dashboard');const [health,setHealth]=useState<HealthInfo|null>(null);const [rules,setRules]=useState<RuleItem[]>([]);const [rulesOpen,setRulesOpen]=useState(false);const [refreshKey,setRefreshKey]=useState(0);const [openId,setOpenId]=useState<string|null>(null);const [collapsed,setCollapsed]=useState(false)
 const ping=async()=>{try{setHealth(await api.health())}catch{setHealth({ollama:false,llm:false} as HealthInfo)}}
 useEffect(()=>{if(user){ping();api.rules().then(r=>setRules(r.rules)).catch(()=>{})}},[user])
 if(loading)return <div className="boot"><Spin size="large"/></div>; if(!user)return <LoginPage/>
 const all=[{key:'dashboard',icon:<DashboardOutlined/>,label:'我的工作台'},{key:'credit',icon:<SafetyCertificateOutlined/>,label:'客户信审'},{key:'review',icon:<FileAddOutlined/>,label:'发起合同评审'},{key:'cases',icon:<UnorderedListOutlined/>,label:'团队案件'},{key:'matrix',icon:<UnorderedListOutlined/>,label:'批量风险矩阵'},{key:'knowledge',icon:<BookOutlined/>,label:'风险条款库'}]; const menu=user.role==='admin'?[...all,{key:'admin',icon:<SettingOutlined/>,label:'团队管理'},{key:'settings',icon:<ControlOutlined/>,label:'系统设置'}]:all
  return <Layout style={{minHeight:'100vh'}}>
    <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="dark" width={224}>
      <div className="brand"><SafetyCertificateOutlined/><span>{!collapsed&&'ContractGuard'}</span></div>
      <Menu theme="dark" mode="inline" selectedKeys={[tab]} items={menu} onSelect={e=>setTab(e.key as Tab)}/>
      <div className="sider-foot">{!collapsed&&<Text>合同评审协作中心</Text>}</div>
    </Sider>
    <Layout>
      <Header className="workspace-header"><Title level={4} style={{margin:0}}>{menu.find(x=>x.key===tab)?.label}</Title><Space><Tag color="blue">{role}</Tag><Text>{user.display_name}</Text><Badge status={health?.llm?'success':'warning'} text={health?.llm?'审查模型在线':'模型未配置'}/><Button size="small" icon={<ReloadOutlined/>} onClick={ping}>检测</Button><Button size="small" icon={<BookOutlined/>} onClick={()=>setRulesOpen(true)}>规则库</Button><Button size="small" icon={<LogoutOutlined/>} onClick={logout}>退出</Button></Space></Header>
      <Content className="workspace-content">{tab==='dashboard'&&<DashboardPage refreshKey={refreshKey} onCreate={()=>setTab('review')} onCases={()=>setTab('cases')}/>} {tab==='credit'&&<CreditPage/>} {tab==='review'&&<ReviewPage setRulesOpen={setRulesOpen} onSubmitted={()=>setRefreshKey(x=>x+1)}/>} {tab==='cases'&&<CaseBoardPage openId={setOpenId} refreshKey={refreshKey}/>} {tab==='matrix'&&<BatchMatrixPage/>} {tab==='knowledge'&&<KnowledgePage/>} {tab==='admin'&&user.role==='admin'&&<AdminPage/>} {tab==='settings'&&user.role==='admin'&&<SettingsPage onSaved={ping}/>}</Content>
    </Layout>
    <HistoryDetail id={openId} onClose={()=>{setOpenId(null);setRefreshKey(x=>x+1)}}/>
    <Drawer title="合同规则库 · contract-v1" open={rulesOpen} onClose={()=>setRulesOpen(false)} width={620}>
      <List dataSource={rules} renderItem={r => <List.Item><List.Item.Meta
        avatar={<Tag color={r.severity==='high'?'red':'orange'}>{r.id}</Tag>}
        title={<Text strong>{r.baseline}</Text>}
        description={<><Text type="secondary">适用：{r.applies_to?.join('、') || '全部'}　{r.approval_role ? `例外审批：${r.approval_role.toUpperCase()}` : '无需例外审批'}</Text><br/><Text type="secondary">判定：{r.check}</Text>{r.template&&<><br/><Text type="secondary">红线改写：{r.template}</Text></>}</>}
      /></List.Item>} />
    </Drawer>
  </Layout>
}
export default function App(){return <AuthProvider><RoleProvider><AppInner/></RoleProvider></AuthProvider>}
