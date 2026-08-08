import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography, message } from 'antd'
import { EditOutlined, PlusOutlined, ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import { useAuth } from '../context/AuthContext'
import type { RuleItem, RuleVersion } from '../types'
import { approvalRoleLabel } from '../components/common'

const { Title } = Typography
const versionStatusText: Record<string, string> = { draft: '草稿', published: '已发布生效', archived: '历史版本' }
const severityMeta: Record<string, { label: string; color: string }> = {
  high: { label: '高风险', color: 'red' }, mid: { label: '中风险', color: 'orange' }, low: { label: '低风险', color: 'blue' },
}
const businessTypes = ['一般', '模塑一体', 'TKM', 'TKP', '采购订单']

export default function RiskRulePage() {
  const { user } = useAuth()
  const canDraft = user?.role === 'reviewer'
  const canPublish = user?.role === 'director'
  const canManage = canDraft || canPublish
  const [rules, setRules] = useState<RuleItem[]>([])
  const [versions, setVersions] = useState<RuleVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState('')
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<RuleItem | null>(null)
  const [ruleForm] = Form.useForm()

  const loadRules = async (version: string) => {
    try {
      const result = await api.ruleVersion(version)
      setSelectedVersion(version)
      setRules(result.rules)
    } catch (error: any) { message.error(error?.message || '加载条款版本失败') }
  }

  const load = async () => {
    setLoading(true)
    try {
      if (canManage) {
        const v = await api.ruleVersions()
        setVersions(v.items)
        const active = v.items.find((item: RuleVersion) => item.status === 'published')?.version || v.items[0]?.version || ''
        if (active) await loadRules(active)
      } else {
        // 非规则治理角色只读当前生效版本：规则目录对审批角色可见，
        // 让他们理解 Agent 为什么这样判风险、例外该找谁。
        const result = await api.rules()
        setRules(result.rules)
      }
    } catch (error: any) { message.error(error?.message || '风险条款加载失败') } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const createDraft = async () => {
    try {
      const result = await api.createRuleDraft()
      message.success('已创建草稿 ' + result.version)
      setVersions([])
      await load()
      await loadRules(result.version)
    } catch (error: any) { message.error(error?.message || '创建草稿失败') }
  }
  const editRule = (rule: RuleItem) => {
    setEditing(rule)
    ruleForm.setFieldsValue({ ...rule, applies_to: rule.applies_to || ['全部'] })
    setModalOpen(true)
  }
  const [modalOpen, setModalOpen] = useState(false)
  const saveRule = async () => {
    try {
      const values = await ruleForm.validateFields()
      if (!editing) return
      await api.updateRule(selectedVersion, editing.id, values)
      message.success('规则草稿已保存，发布后对新审查生效')
      setModalOpen(false)
      await loadRules(selectedVersion)
    } catch (error: any) { if (!error?.errorFields) message.error(error?.message || '规则保存失败') }
  }
  const publish = async () => {
    try {
      await api.publishRuleVersion(selectedVersion)
      message.success('条款版本已发布生效，新发起的合同审查将使用此版本')
      await load()
    } catch (error: any) { message.error(error?.message || '发布失败') }
  }

  const columns = [
    { title: '条款', dataIndex: 'id', width: 76, render: (value: string, rule: RuleItem) => <Tag color={severityMeta[rule.severity]?.color || 'default'}>{value}</Tag> },
    { title: '风险等级', dataIndex: 'severity', width: 92, render: (value: string) => severityMeta[value]?.label || value },
    { title: '规则底线', dataIndex: 'baseline', width: 280 },
    { title: '适用业务', dataIndex: 'applies_to', width: 150, render: (value?: string[]) => (value || []).join('、') },
    { title: '例外审批层级', dataIndex: 'approval_role', width: 150, render: (value?: string) => value ? approvalRoleLabel(value) : '无需例外审批' },
    { title: '判定逻辑', dataIndex: 'check', ellipsis: true },
    ...(canDraft ? [{ title: '操作', width: 84, render: (_: unknown, rule: RuleItem) => <Button size="small" icon={<EditOutlined />} onClick={() => editRule(rule)}>编辑</Button> }] : []),
  ]

  return <div className="role-page matrix-page">
    <section className="page-hero page-hero-light">
      <div><span className="section-kicker">合同底线规则</span><Title level={2}>风险条款管理</Title><Typography.Paragraph>信用审核专员负责起草和维护条款草稿，财务审批主管负责复核发布。Agent 审查时逐条扫描合同文本，已进入流程的案件保留当时使用的规则版本。</Typography.Paragraph></div>
      <div className="page-hero-actions"><Tag color="blue">R01–R16</Tag>{canManage && <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>}</div>
    </section>

    {canManage && <section className="compact-metrics" aria-label="条款版本概览">
      <div className="compact-metric"><span className="compact-metric-icon"><SafetyCertificateOutlined /></span><div><small>条款版本</small><strong>{versions.length}</strong><em>草稿 / 已发布 / 历史</em></div></div>
      <div className="compact-metric metric-attention"><span className="compact-metric-icon"><SafetyCertificateOutlined /></span><div><small>当前生效版本</small><strong>{selectedVersion}</strong><em>新审查使用此版本</em></div></div>
      <div className="compact-metric"><span className="compact-metric-icon"><SafetyCertificateOutlined /></span><div><small>条款数量</small><strong>{rules.length}</strong><em>R01–R16</em></div></div>
    </section>}

    <Alert showIcon type="info" style={{ marginBottom: 16 }} message="规则怎么生效" description="只有“已发布生效”版本用于合同审查；信用审核专员从当前版本创建和修订草稿，财务审批主管复核发布。历史案件保留当时的规则快照不受影响。" />

    <Card className="page-data-card" title={<div><span className="card-kicker">条款目录</span><span>{canManage ? `版本 ${selectedVersion} · ${versionStatusText[versions.find(v => v.version === selectedVersion)?.status || ''] || '已发布生效'}` : '当前生效版本'}</span></div>} extra={
      <Space wrap>
        {canManage && <>
          <Select value={selectedVersion || undefined} style={{ minWidth: 220 }} onChange={loadRules} options={versions.map(item => ({ value: item.version, label: `${item.version} · ${versionStatusText[item.status] || item.status}` }))} />
          {canDraft && <Button icon={<PlusOutlined />} onClick={createDraft}>从已发布版本创建草稿</Button>}
          {canPublish && versions.find(v => v.version === selectedVersion)?.status === 'draft' && <Popconfirm title={'发布 ' + selectedVersion + ' 后将替换当前生效版本，确认吗？'} onConfirm={publish}><Button type="primary">复核并发布草稿</Button></Popconfirm>}
        </>}
      </Space>
    }>
      <Table rowKey="id" loading={loading} dataSource={rules} size="small" pagination={false} scroll={{ x: 1200 }} columns={columns} />
    </Card>

    <Modal title={'编辑 ' + (editing?.id || '') + ' 草稿条款'} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={saveRule} okText="保存草稿">
      <Form form={ruleForm} layout="vertical">
        <Form.Item name="baseline" label="底线规则" rules={[{ required: true }]}><Input.TextArea rows={2} /></Form.Item>
        <Form.Item name="check" label="规则判定说明" rules={[{ required: true }]}><Input.TextArea rows={2} /></Form.Item>
        <Form.Item name="severity" label="风险等级" rules={[{ required: true }]}><Select options={['high', 'mid', 'low'].map(value => ({ value, label: severityMeta[value].label }))} /></Form.Item>
        <Form.Item name="applies_to" label="适用业务类型" rules={[{ required: true }]}><Select mode="multiple" options={businessTypes.map(value => ({ value, label: value }))} /></Form.Item>
        <Form.Item name="approval_role" label="例外审批层级"><Select allowClear options={[{ value: 'director', label: '财务审批主管' }, { value: 'final_approver', label: '集团财务总监（最终审批人）' }]} /></Form.Item>
        <Form.Item name="template" label="建议改写模板" rules={[{ required: true }]}><Input.TextArea rows={3} /></Form.Item>
      </Form>
    </Modal>
  </div>
}
