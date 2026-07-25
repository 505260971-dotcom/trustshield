import { useEffect, useState } from 'react'
import { Button, Card, Drawer, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography, message } from 'antd'
import { AuditOutlined, EditOutlined, PlusOutlined, TeamOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import { fmtTime } from '../components/common'
import type { RuleItem, RuleVersion } from '../types'

const { Text } = Typography
const businessTypes = ['全部', '一般', '模塑一体', 'TKM', 'TKP', '采购订单']
const labels: Record<string, string> = { admin: '管理员', credit: '信审人员', legal: '法务', director: '总监', ceo: 'CEO', business: '业务人员' }
type User = { id:string; username:string; display_name:string; role:string; active:number; created_at:number }

export default function AdminPage () {
  const [users, setUsers] = useState<User[]>([])
  const [audit, setAudit] = useState<any[]>([])
  const [versions, setVersions] = useState<RuleVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState('')
  const [rules, setRules] = useState<RuleItem[]>([])
  const [userOpen, setUserOpen] = useState(false)
  const [ruleOpen, setRuleOpen] = useState(false)
  const [editing, setEditing] = useState<RuleItem | null>(null)
  const [userForm] = Form.useForm()
  const [ruleForm] = Form.useForm()

  const load = async () => {
    try {
      const [u, a, v] = await Promise.all([api.adminUsers(), api.audit(), api.ruleVersions()])
      setUsers(u.items); setAudit(a.items); setVersions(v.items)
      const active = selectedVersion || v.items.find((x: RuleVersion) => x.status === 'published')?.version || ''
      if (active) await loadRules(active)
    } catch { message.error('加载管理数据失败') }
  }
  const loadRules = async (version: string) => {
    try { const result = await api.ruleVersion(version); setSelectedVersion(version); setRules(result.rules) }
    catch { message.error('加载规则版本失败') }
  }
  useEffect(() => { load() }, [])
  const selected = versions.find(x => x.version === selectedVersion)
  const editable = selected?.status === 'draft'
  const createUser = async (values: any) => {
    try { await api.createUser(values); message.success('用户已创建'); setUserOpen(false); userForm.resetFields(); load() }
    catch { message.error('创建失败：用户名可能重复或密码不足10位') }
  }
  const patchUser = async (id: string, values: any) => {
    try { await api.patchUser(id, values); message.success('已更新'); load() }
    catch { message.error('更新失败') }
  }
  const createDraft = async () => {
    try { const result = await api.createRuleDraft(); message.success(`已创建草稿 ${result.version}`); setVersions([]); await load(); await loadRules(result.version) }
    catch (error: any) { message.error(error?.message || '创建草稿失败') }
  }
  const editRule = (rule: RuleItem) => {
    setEditing(rule); ruleForm.setFieldsValue({ ...rule, applies_to: rule.applies_to || ['全部'] }); setRuleOpen(true)
  }
  const saveRule = async () => {
    try {
      const values = await ruleForm.validateFields()
      if (!editing) return
      await api.updateRule(selectedVersion, editing.id, values)
      message.success('规则草稿已保存'); setRuleOpen(false); await loadRules(selectedVersion)
    } catch (error: any) { if (error?.errorFields) return; message.error(error?.message || '规则保存失败') }
  }
  const publish = async () => {
    try { await api.publishRuleVersion(selectedVersion); message.success('规则版本已发布，新发起的审查将使用此版本'); await load() }
    catch (error: any) { message.error(error?.message || '发布失败') }
  }

  return <>
    <Card title={<Space><TeamOutlined />团队成员与合同评审权限</Space>} extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setUserOpen(true)}>新增成员</Button>}>
      <Table rowKey="id" dataSource={users} pagination={false} columns={[
        { title: '姓名', dataIndex: 'display_name' }, { title: '用户名', dataIndex: 'username' },
        { title: '角色', dataIndex: 'role', render: (value: string) => <Tag color={value === 'admin' ? 'red' : 'blue'}>{labels[value] || value}</Tag> },
        { title: '状态', dataIndex: 'active', render: (value:number, row:User) => <Switch checked={!!value} onChange={active => patchUser(row.id, { active })} /> },
        { title: '创建时间', dataIndex: 'created_at', render: fmtTime }
      ]} />
    </Card>

    <Card style={{ marginTop: 16 }} title="合同底线规则版本" extra={<Space><Button onClick={createDraft} icon={<PlusOutlined />}>从已发布版本创建草稿</Button>{editable && <Popconfirm title={`发布 ${selectedVersion} 后将替换当前生效版本，确认吗？`} onConfirm={publish}><Button type="primary">发布草稿</Button></Popconfirm>}</Space>}>
      <Space style={{ marginBottom: 12 }} wrap><Text type="secondary">当前查看：</Text><Select value={selectedVersion || undefined} style={{ minWidth: 220 }} onChange={loadRules} options={versions.map(version => ({ value: version.version, label: `${version.version} · ${version.status}` }))} />{selected && <Tag color={selected.status === 'published' ? 'green' : selected.status === 'draft' ? 'orange' : 'default'}>{selected.status}</Tag>}</Space>
      <Table rowKey="id" dataSource={rules} size="small" pagination={{ pageSize: 8 }} columns={[
        { title: '规则', dataIndex: 'id', width: 72, render: (value:string, rule:RuleItem) => <Tag color={rule.severity === 'high' ? 'red' : 'orange'}>{value}</Tag> },
        { title: '底线', dataIndex: 'baseline', width: 260 }, { title: '适用', dataIndex: 'applies_to', width: 150, render: (value:string[]) => value?.join('、') },
        { title: '例外审批', dataIndex: 'approval_role', width: 100, render: (value:string) => value ? value.toUpperCase() : '—' },
        { title: '红线改写', dataIndex: 'template', ellipsis: true },
        { title: '操作', width: 80, render: (_:unknown, rule:RuleItem) => <Button disabled={!editable} size="small" icon={<EditOutlined />} onClick={() => editRule(rule)}>编辑</Button> }
      ]} />
    </Card>

    <Card style={{ marginTop: 16 }} title={<Space><AuditOutlined />合同评审审计日志</Space>}>
      <Table size="small" rowKey="event_id" dataSource={audit} pagination={{ pageSize: 8 }} columns={[
        { title:'时间', dataIndex:'created_at', render:fmtTime }, { title:'动作', dataIndex:'action' },
        { title:'资源', render:(_:unknown,row:any) => `${row.resource_type || '—'} / ${row.resource_id || '—'}` },
        { title:'操作者', dataIndex:'actor_role', render:(value:string) => labels[value] || value }, { title:'元数据', dataIndex:'metadata', render:(value:any) => <Text type="secondary">{JSON.stringify(value)}</Text> }
      ]} />
    </Card>

    <Drawer title="新增合同评审成员" open={userOpen} onClose={() => setUserOpen(false)} width={420}>
      <Form form={userForm} layout="vertical" onFinish={createUser} initialValues={{ role:'legal' }}>
        <Form.Item name="display_name" label="姓名" rules={[{ required:true }]}><Input /></Form.Item><Form.Item name="username" label="用户名" rules={[{ required:true, min:3 }]}><Input /></Form.Item><Form.Item name="role" label="角色" rules={[{ required:true }]}><Select options={['admin','credit','legal','director','ceo','business'].map(value => ({ value, label:labels[value] }))} /></Form.Item><Form.Item name="password" label="初始密码" rules={[{ required:true, min:10 }]}><Input.Password /></Form.Item><Button type="primary" htmlType="submit">创建成员</Button>
      </Form>
    </Drawer>
    <Modal title={`编辑 ${editing?.id || ''} 草稿规则`} open={ruleOpen} onCancel={() => setRuleOpen(false)} onOk={saveRule} okText="保存草稿">
      <Form form={ruleForm} layout="vertical"><Form.Item name="baseline" label="底线规则" rules={[{ required:true }]}><Input.TextArea rows={2} /></Form.Item><Form.Item name="check" label="裁决说明" rules={[{ required:true }]}><Input.TextArea rows={2} /></Form.Item><Form.Item name="severity" label="风险等级" rules={[{ required:true }]}><Select options={['high','mid','low'].map(value => ({ value, label:value }))} /></Form.Item><Form.Item name="applies_to" label="适用业务类型" rules={[{ required:true }]}><Select mode="multiple" options={businessTypes.map(value => ({ value, label:value }))} /></Form.Item><Form.Item name="approval_role" label="例外审批角色"><Select allowClear options={[{ value:'ceo', label:'CEO' }, { value:'director', label:'总监' }]} /></Form.Item><Form.Item name="template" label="红线改写模板" rules={[{ required:true }]}><Input.TextArea rows={3} /></Form.Item></Form>
    </Modal>
  </>
}
