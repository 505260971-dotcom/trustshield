import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react'
import { AutoComplete, Badge, Button, Dropdown, Drawer, Layout, List, Menu, Modal, Space, Spin, Tag, Typography, type MenuProps } from 'antd'
import {
  ApartmentOutlined, BookOutlined, CheckCircleOutlined, DashboardOutlined,
  FileAddOutlined, FolderOpenOutlined, ReloadOutlined, SafetyCertificateOutlined, SearchOutlined, SettingOutlined,
  TeamOutlined, UnorderedListOutlined,
} from '@ant-design/icons'
import { api } from './services/api'
import type { CustomerWorkspace, HealthInfo, RuleItem } from './types'
import { AuthProvider, useAuth } from './context/AuthContext'
import { RoleProvider } from './context/RoleContext'
import { approvalRoleLabel } from './components/common'

const LoginPage = lazy(() => import('./pages/LoginPage'))
const ReviewPage = lazy(() => import('./pages/ReviewPage'))
const AdminPage = lazy(() => import('./pages/AdminPage'))
const CreditPage = lazy(() => import('./pages/CreditPage'))
const CaseDetailPage = lazy(() => import('./pages/CaseDetailPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const WorkboxPage = lazy(() => import('./pages/WorkboxPage'))
const WorkbenchPage = lazy(() => import('./pages/WorkbenchPage'))
const CaseCenterPage = lazy(() => import('./pages/CaseCenterPage'))
const CustomerWorkspacePage = lazy(() => import('./pages/CustomerWorkspacePage'))
const CustomerProfilePage = lazy(() => import('./pages/CustomerProfilePage'))
const ApprovalCenterPage = lazy(() => import('./pages/ApprovalCenterPage'))

const { Sider, Header, Content } = Layout
const { Title, Text } = Typography
type RoleKey = 'business' | 'reviewer' | 'director' | 'admin'
type Page = 'home' | 'customers' | 'customer' | 'credits' | 'credit' | 'contracts' | 'case' | 'new' | 'records' | 'approvals' | 'admin' | 'settings'
type Route = { page: Page; customerKey?: string; caseId?: string; creditId?: string; creditCreate?: boolean; creditNewCustomerKey?: string }

function parseRoute(): Route {
  const parts = (window.location.hash.replace(/^#/, '') || '/home').split('/').filter(Boolean)
  if (parts[0] === 'customers' && parts[1]) return { page: 'customer', customerKey: decodeURIComponent(parts[1]) }
  if (parts[0] === 'customers') return { page: 'customers' }
  if (parts[0] === 'cases' && parts[1]) return { page: 'case', caseId: parts[1] }
  if (parts[0] === 'credit' && parts[1] === 'new') return { page: 'credit', creditCreate: true, creditNewCustomerKey: parts[2] ? decodeURIComponent(parts[2]) : undefined }
  if (parts[0] === 'credit' && parts[1]) return { page: 'credit', creditId: parts[1] }
  if (parts[0] === 'credits') return { page: 'credits' }
  if (parts[0] === 'new') return { page: 'new', customerKey: parts[1] ? decodeURIComponent(parts[1]) : undefined }
  if (parts[0] === 'contracts') return { page: 'contracts' }
  if (parts[0] === 'records') return { page: 'records' }
  if (parts[0] === 'approvals') return { page: 'approvals' }
  if (parts[0] === 'admin') return { page: 'admin' }
  if (parts[0] === 'settings') return { page: 'settings' }
  return { page: 'home' }
}

const routeTitle: Record<Page, string> = {
  home: '待我处理', customers: '客户工作台', customer: '客户档案', credits: '信审管理', credit: '客户信审',
  contracts: '合同审查', case: '合同案件', new: '发起合同审查', records: '我的记录', approvals: '审批中心',
  admin: '组织与规则', settings: '系统与集成',
}

const access: Record<RoleKey, Page[]> = {
  business: ['home', 'customers', 'customer', 'credits', 'credit', 'contracts', 'case', 'new', 'records'],
  reviewer: ['home', 'customers', 'customer', 'credits', 'credit', 'contracts', 'case', 'records'],
  director: ['home', 'customers', 'customer', 'credits', 'credit', 'contracts', 'case', 'records', 'approvals'],
  admin: ['home', 'customers', 'customer', 'credits', 'credit', 'contracts', 'case', 'records', 'approvals', 'admin', 'settings'],
}

const activeMenuFor = (page: Page): string => {
  const parent: Partial<Record<Page, string>> = { customer: 'customers', credit: 'credits', case: 'contracts', new: 'home' }
  return parent[page] || page
}

function AppInner() {
  const { user, loading, logout } = useAuth()
  const [route, setRoute] = useState<Route>(parseRoute())
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [rules, setRules] = useState<RuleItem[]>([])
  const [rulesOpen, setRulesOpen] = useState(false)
  const [customerSearchOpen, setCustomerSearchOpen] = useState(false)
  const [customerSearch, setCustomerSearch] = useState('')
  const [customerOptions, setCustomerOptions] = useState<CustomerWorkspace[]>([])
  const go = (path: string) => { window.location.hash = path }

  useEffect(() => {
    const onHashChange = () => setRoute(parseRoute())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const ping = async () => {
    try { setHealth(await api.health()) } catch { setHealth({ ollama: false, llm: false } as HealthInfo) }
  }
  useEffect(() => {
    if (user) { ping(); api.rules().then(result => setRules(result.rules)).catch(() => {}); api.customerWorkspaces().then(result => setCustomerOptions(result.items || [])).catch(() => {}) }
  }, [user])
  const role = (user?.role || 'business') as RoleKey

  const menu = useMemo<MenuProps['items']>(() => {
    const homeLabel = ['director', 'admin'].includes(role) ? '待我决策' : '待我处理'
    const base: MenuProps['items'] = [
      { key: 'home', icon: <DashboardOutlined />, label: homeLabel },
      { key: 'customers', icon: <TeamOutlined />, label: role === 'business' ? '客户与业务' : '客户工作台' },
    ]
    if (role === 'business') base.push({ key: 'records', icon: <UnorderedListOutlined />, label: '我的申请' })
    if (role === 'reviewer') base.push(
      { key: 'credits', icon: <SafetyCertificateOutlined />, label: '信审管理' },
      { key: 'contracts', icon: <FolderOpenOutlined />, label: '合同审查' },
      { key: 'records', icon: <CheckCircleOutlined />, label: '我的记录' },
    )
    if (['director', 'admin'].includes(role)) base.push(
      { key: 'approvals', icon: <ApartmentOutlined />, label: '审批中心' },
      { key: 'records', icon: <CheckCircleOutlined />, label: '我的记录' },
    )
    if (role === 'admin') base.push(
      { type: 'divider' },
      { key: 'admin', icon: <TeamOutlined />, label: '组织与规则' },
      { key: 'settings', icon: <SettingOutlined />, label: '系统与集成' },
    )
    return base
  }, [role])

  if (loading) return <div className="boot"><Spin size="large" /></div>
  if (!user) return <Suspense fallback={<div className="boot"><Spin size="large" /></div>}><LoginPage /></Suspense>

  const activeRoute = access[role].includes(route.page) ? route : { page: 'home' as Page }
  const canCreateContract = role === 'business'
  const canCreateCredit = ['business', 'reviewer'].includes(role)
  const openCase = (id: string) => go(`/cases/${id}`)
  const openCredit = (id: string) => go(`/credit/${id}`)
  const openCustomer = (key: string) => go(`/customers/${encodeURIComponent(key)}`)
  const createContractFor = (customer?: CustomerWorkspace) => go(`/new${customer ? `/${encodeURIComponent(customer.customer_key)}` : ''}`)
  const createCreditFor = (customer?: CustomerWorkspace) => go(`/credit/new${customer ? `/${encodeURIComponent(customer.customer_key)}` : ''}`)

  const createMenu: MenuProps['items'] = role === 'business'
    ? [
        { key: 'credit', icon: <SafetyCertificateOutlined />, label: '发起客户信审' },
        { key: 'contract', icon: <FileAddOutlined />, label: '发起合同审查' },
      ]
    : [{ key: 'credit', icon: <SafetyCertificateOutlined />, label: '新建信审版本' }]

  let page: ReactNode
  if (activeRoute.page === 'home') {
    page = <WorkbenchPage canCreateContract={canCreateContract} canCreateCredit={canCreateCredit} onCreateContract={createContractFor} onCreateCredit={createCreditFor} onOpenCase={openCase} onOpenCredit={openCredit} onNavigate={key => go(key.startsWith('/') ? key : `/${key}`)} />
  } else if (activeRoute.page === 'customers') {
    page = <CustomerWorkspacePage onOpenCustomer={openCustomer} onOpenCase={openCase} onOpenCredit={openCredit} onCreateContract={() => createContractFor()} onOpenCreditList={() => go('/credits')} canCreateContract={canCreateContract} />
  } else if (activeRoute.page === 'customer' && activeRoute.customerKey) {
    page = <CustomerProfilePage customerKey={activeRoute.customerKey} onBack={() => go('/customers')} onOpenCase={openCase} onOpenCredit={openCredit} onCreateCredit={createCreditFor} canCreateCredit={canCreateCredit} onCreateContract={createContractFor} canCreateContract={canCreateContract} />
  } else if (activeRoute.page === 'contracts') {
    page = <CaseCenterPage onCreate={() => createContractFor()} onOpen={openCase} canCreateContract={canCreateContract} />
  } else if (activeRoute.page === 'case' && activeRoute.caseId) {
    page = <CaseDetailPage caseId={activeRoute.caseId} onBack={() => go('/contracts')} />
  } else if (activeRoute.page === 'new') {
    page = <ReviewPage initialCustomerKey={activeRoute.customerKey} onCreated={openCase} />
  } else if (activeRoute.page === 'credits' || activeRoute.page === 'credit') {
    page = <CreditPage focusCaseId={activeRoute.creditId} startNew={activeRoute.creditCreate} initialCustomerKey={activeRoute.creditNewCustomerKey} />
  } else if (activeRoute.page === 'records') {
    page = <WorkboxPage bucket="done" canCreateContract={canCreateContract} canCreateCredit={canCreateCredit} onCreateContract={() => createContractFor()} onCreateCredit={() => createCreditFor()} onOpenCase={openCase} onOpenCredit={openCredit} />
  } else if (activeRoute.page === 'approvals') {
    page = <ApprovalCenterPage onOpenCase={openCase} onOpenCredit={openCredit} />
  } else if (activeRoute.page === 'settings' && role === 'admin') {
    page = <SettingsPage onSaved={ping} />
  } else if (activeRoute.page === 'admin' && role === 'admin') {
    page = <AdminPage />
  } else {
    page = <WorkbenchPage canCreateContract={canCreateContract} canCreateCredit={canCreateCredit} onCreateContract={createContractFor} onCreateCredit={createCreditFor} onOpenCase={openCase} onOpenCredit={openCredit} onNavigate={key => go(key.startsWith('/') ? key : `/${key}`)} />
  }

  return <Layout className="app-shell" style={{ minHeight: '100vh' }}>
    <Sider collapsible breakpoint="lg" collapsedWidth="0" theme="dark" width={236}>
      <div className="brand"><SafetyCertificateOutlined /><span>ContractGuard</span></div>
      {canCreateCredit && <div className="sider-create"><Dropdown menu={{ items: createMenu, onClick: ({ key }) => key === 'contract' ? createContractFor() : createCreditFor() }} trigger={['click']}><Button type="primary" block icon={<FileAddOutlined />}>{role === 'business' ? '新建业务申请' : '新建信审版本'}</Button></Dropdown></div>}
      <Menu theme="dark" mode="inline" selectedKeys={[activeMenuFor(activeRoute.page)]} items={menu} onSelect={event => go(`/${event.key}`)} />
      <div className="sider-foot"><Text>合同协同与风险控制</Text></div>
    </Sider>
    <Layout>
      <Header className="workspace-header">
        <Title level={4} style={{ margin: 0 }}>{routeTitle[activeRoute.page]}</Title>
        <Space wrap>
          <Tag color="blue">{approvalRoleLabel(role)}</Tag>
          <Text className="header-user">{user.display_name}</Text>
          <Badge className="header-health" status={health?.llm ? 'success' : 'warning'} text={health?.llm ? '模型在线' : '模型未配置'} />
          <Button size="small" icon={<SearchOutlined />} onClick={() => setCustomerSearchOpen(true)}>搜索</Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={ping}>检测</Button>
          {role === 'reviewer' && <Button size="small" icon={<BookOutlined />} onClick={() => setRulesOpen(true)}>规则库</Button>}
          <Button size="small" onClick={logout}>退出</Button>
        </Space>
      </Header>
      <Content className="workspace-content"><Suspense fallback={<div className="page-loading"><Spin /><Text type="secondary">正在加载工作区…</Text></div>}>{page}</Suspense></Content>
    </Layout>
    <Drawer title="合同规则库" open={rulesOpen} onClose={() => setRulesOpen(false)} width={620}>
      <List dataSource={rules} renderItem={rule => <List.Item><List.Item.Meta avatar={<Tag color={rule.severity === 'high' ? 'red' : 'orange'}>{rule.id}</Tag>} title={<Text strong>{rule.baseline}</Text>} description={<><Text type="secondary">适用：{rule.applies_to?.join('、') || '全部'}　{rule.approval_role ? `例外审批：${approvalRoleLabel(rule.approval_role)}` : '无需例外审批'}</Text><br /><Text type="secondary">判定：{rule.check}</Text></>} /></List.Item>} />
    </Drawer>
    <Modal title="快速定位客户业务" open={customerSearchOpen} onCancel={() => { setCustomerSearchOpen(false); setCustomerSearch('') }} footer={null} destroyOnClose>
      <AutoComplete style={{ width: '100%' }} value={customerSearch} options={customerOptions.map(customer => ({ value: customer.customer_name, label: <div className="customer-search-option"><b>{customer.customer_name}</b><span>{customer.latest_credit?.status === 'approved' ? `有效信审 V${customer.latest_credit.version}` : '暂无有效信审'} · 合同 ${customer.contracts.length} 份</span></div> }))} onChange={setCustomerSearch} filterOption={(input, option) => String(option?.value || '').toLowerCase().includes(input.toLowerCase())} onSelect={(_, option) => { const customer = customerOptions.find(item => item.customer_name === option.value); if (customer) { openCustomer(customer.customer_key); setCustomerSearchOpen(false); setCustomerSearch('') } }} placeholder="搜索客户名称" />
      {!customerOptions.length && <div className="page-loading"><Spin size="small" /><Text type="secondary">正在加载客户索引…</Text></div>}
    </Modal>
  </Layout>
}

export default function App() {
  return <AuthProvider><RoleProvider><AppInner /></RoleProvider></AuthProvider>
}
