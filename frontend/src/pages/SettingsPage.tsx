import { useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Form, Input, InputNumber, Row, Space, Spin, Switch, Tag, Typography, message } from 'antd'
import { ApiOutlined, DatabaseOutlined, ExperimentOutlined, SafetyCertificateOutlined, SaveOutlined, SortAscendingOutlined } from '@ant-design/icons'
import { api } from '../services/api'

const { Text } = Typography

type Settings = {
  llm_api_base: string; llm_model: string; llm_api_key_configured: boolean
  enable_masking: boolean; smart_mask: boolean
  mask_llm_api_base: string; mask_llm_model: string; mask_llm_api_key_configured: boolean
  rerank_enabled: boolean; rerank_allow_remote_financial_data: boolean
  rerank_base_url: string; rerank_model: string; rerank_api_key_configured: boolean
  embedding_enabled: boolean; embedding_allow_remote_financial_data: boolean
  embedding_base_url: string; embedding_model: string; embedding_dimensions: number; embedding_api_key_configured: boolean
  external_due_diligence_enabled: boolean; external_due_diligence_recent_days: number; external_due_diligence_max_results: number; external_due_diligence_timeout_seconds: number
}
type Props = { onSaved?: () => void }

const TEST_KINDS = ['llm', 'mask', 'rerank', 'embedding', 'exa'] as const
type TestKind = typeof TEST_KINDS[number]
const KIND_LABELS: Record<TestKind, string> = {
  llm: 'Agent 审查模型', mask: '合同脱敏模型', rerank: '证据精排模型', embedding: '语义召回模型', exa: 'Exa 公开信息尽调',
}
const SECRET_FIELDS = ['llm_api_key', 'mask_llm_api_key', 'rerank_api_key', 'embedding_api_key'] as const

export default function SettingsPage({ onSaved }: Props) {
  const [form] = Form.useForm()
  const [settings, setSettings] = useState<Settings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState<TestKind | null>(null)
  const [requiresRestart, setRequiresRestart] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const value = await api.adminSettings()
      setSettings(value)
      form.setFieldsValue(value)
    } catch { message.error('系统配置加载失败') } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const save = async (values: Record<string, any>) => {
    setSaving(true)
    try {
      const payload = { ...values }
      SECRET_FIELDS.forEach(key => { if (!payload[key]) delete payload[key] })
      const result = await api.patchAdminSettings(payload)
      setSettings(result)
      form.setFieldsValue(result)
      setRequiresRestart(!!result.requires_restart)
      message.success('系统配置已保存')
      onSaved?.()
    } catch (error: any) { message.error(`保存失败：${error?.message || '请检查配置'}`) } finally { setSaving(false) }
  }

  const test = async (kind: TestKind) => {
    const values = form.getFieldsValue(true)
    setTesting(kind)
    try {
      const field = { llm: 'llm', mask: 'mask_llm', rerank: 'rerank', embedding: 'embedding', exa: 'exa' }[kind]
      const payload: Record<string, any> = {
        kind,
        api_base: values[`${field}_api_base`] || values[`${field}_base_url`] || '',
        api_key: values[`${field}_api_key`] || '',
        model: values[`${field}_model`] || '',
      }
      if (kind === 'embedding') payload.dimensions = values.embedding_dimensions
      const result = await api.testAdminSettings(payload)
      if (result.ok) message.success(`${KIND_LABELS[kind]}连接成功（${result.latency_ms} ms）`)
      else message.warning(result.message || '连接失败')
    } catch (error: any) { message.error(`连接测试失败：${error?.message || '请求失败'}`) } finally { setTesting(null) }
  }

  if (loading || !settings) return <Card><Spin /> <Text type="secondary">正在加载系统配置…</Text></Card>

  return <Form className="role-page settings-page" form={form} layout="vertical" onFinish={save} initialValues={settings}>
    <section className="page-hero page-hero-light settings-hero">
      <div><Typography.Title level={2}>系统设置</Typography.Title></div>
      <div className="page-hero-actions"><Tag color={settings.llm_api_key_configured ? 'green' : 'orange'}>{settings.llm_api_key_configured ? 'Agent 审查模型已配置' : 'Agent 审查模型待配置'}</Tag></div>
    </section>

    {requiresRestart && <Alert type="warning" showIcon message="配置已保存，重启后端后生效" style={{ marginBottom: 16 }} />}
    <Alert showIcon type="info" style={{ marginBottom: 16 }} message="信审财务证据外发强制脱敏" description="发往外部 Embedding / Rerank 及财务模型服务的证据文本，外发前必须先经脱敏模型（默认本地 Ollama）掩码，此步骤无法绕过；未配置可用的脱敏模型时，正式依据检索会安全失败。案件本身的结构化数据（客户名、授信条件、敞口快照）仍按授权外发。" />

    <Row gutter={[16, 16]}>
      <Col xs={24} xl={12}>
        <Card title={<Space><ApiOutlined />Agent 审查模型</Space>} extra={<Button icon={<ExperimentOutlined />} loading={testing === 'llm'} onClick={() => test('llm')}>测试连接</Button>}>
          <Form.Item name="llm_api_base" label="OpenAI 兼容 API 地址"><Input placeholder="https://your-provider.example/v1" /></Form.Item>
          <Form.Item name="llm_model" label="模型名称" rules={[{ max: 200 }]}><Input placeholder="例如 qwen-plus、deepseek-chat" /></Form.Item>
          <Form.Item name="llm_api_key" label={<Space>API Key {settings.llm_api_key_configured && <Tag color="green">已配置</Tag>}</Space>}><Input.Password placeholder={settings.llm_api_key_configured ? '已配置，留空保持不变' : '输入模型服务 API Key'} /></Form.Item>
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Card title={<Space><SafetyCertificateOutlined />合同脱敏模型</Space>} extra={<Button icon={<ExperimentOutlined />} loading={testing === 'mask'} onClick={() => test('mask')}>测试连接</Button>}>
          <Form.Item name="enable_masking" label="启用合同脱敏" valuePropName="checked"><Switch checkedChildren="开启" unCheckedChildren="关闭" /></Form.Item>
          <Form.Item name="smart_mask" label="使用模型脱敏" valuePropName="checked"><Switch checkedChildren="开启" unCheckedChildren="关闭" /></Form.Item>
          <Form.Item name="mask_llm_api_base" label="OpenAI 兼容 API 地址"><Input placeholder="https://your-provider.example/v1" /></Form.Item>
          <Form.Item name="mask_llm_model" label="模型名称" extra="该脱敏模型同时用于信审财务证据外发前的强制掩码（默认本地 Ollama）。"><Input placeholder="例如 qwen3.5:4b" /></Form.Item>
          <Form.Item name="mask_llm_api_key" label={<Space>API Key {settings.mask_llm_api_key_configured && <Tag color="green">已配置</Tag>}</Space>}><Input.Password placeholder={settings.mask_llm_api_key_configured ? '已配置，留空保持不变' : '输入模型服务 API Key'} /></Form.Item>
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Card title={<Space><SortAscendingOutlined />证据精排（Rerank）</Space>} extra={<Button icon={<ExperimentOutlined />} loading={testing === 'rerank'} onClick={() => test('rerank')}>测试连接</Button>}>
          <Form.Item name="rerank_enabled" label="启用 Rerank 精排" valuePropName="checked"><Switch checkedChildren="开启" unCheckedChildren="关闭" /></Form.Item>
          <Form.Item name="rerank_allow_remote_financial_data" label="允许财务证据发送至重排服务" valuePropName="checked" extra="数据出域授权（外发内容先经本地脱敏模型掩码）；关闭时证据检索会安全失败，不会降级为本地词法排序"><Switch checkedChildren="已授权" unCheckedChildren="未授权" /></Form.Item>
          <Form.Item name="rerank_base_url" label="Rerank API 地址"><Input placeholder="https://dashscope.aliyuncs.com/compatible-api/v1" /></Form.Item>
          <Form.Item name="rerank_model" label="模型名称"><Input placeholder="例如 qwen3-rerank" /></Form.Item>
          <Form.Item name="rerank_api_key" label={<Space>API Key {settings.rerank_api_key_configured && <Tag color="green">已配置</Tag>}</Space>}><Input.Password placeholder={settings.rerank_api_key_configured ? '已配置，留空保持不变' : '输入阿里百炼 API Key（DashScope 兼容模式）'} /></Form.Item>
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Card title={<Space><DatabaseOutlined />语义召回（Embedding）</Space>} extra={<Button icon={<ExperimentOutlined />} loading={testing === 'embedding'} onClick={() => test('embedding')}>测试连接</Button>}>
          <Form.Item name="embedding_enabled" label="启用 Embedding 语义召回" valuePropName="checked"><Switch checkedChildren="开启" unCheckedChildren="关闭" /></Form.Item>
          <Form.Item name="embedding_allow_remote_financial_data" label="允许财务证据发送至向量服务" valuePropName="checked" extra="数据出域授权（外发内容先经本地脱敏模型掩码）；开启后与本地词法召回做 RRF 融合，再交由 Rerank 精排"><Switch checkedChildren="已授权" unCheckedChildren="未授权" /></Form.Item>
          <Form.Item name="embedding_base_url" label="Embedding API 地址"><Input placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" /></Form.Item>
          <Form.Item name="embedding_model" label="模型名称"><Input placeholder="例如 qwen3.7-text-embedding" /></Form.Item>
          <Form.Item name="embedding_dimensions" label="向量维度"><InputNumber min={0} max={4096} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="embedding_api_key" label={<Space>API Key {settings.embedding_api_key_configured && <Tag color="green">已配置</Tag>}</Space>}><Input.Password placeholder={settings.embedding_api_key_configured ? '已配置，留空保持不变' : '输入阿里百炼 API Key（DashScope 兼容模式）'} /></Form.Item>
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Card title={<Space><SafetyCertificateOutlined />Exa 公开信息尽调</Space>} extra={<Button icon={<ExperimentOutlined />} loading={testing === 'exa'} onClick={() => test('exa')}>测试连接</Button>}>
          <Alert showIcon type="info" style={{marginBottom:12}} message="无需 API Key；仅发送企业全称、统一社会信用代码和注册地" description="不会发送合同、财报、CRM/ERP 敞口或联系人信息。匿名调用可能受到 Exa 免费额度限制；限流时会要求审核专员人工核验，绝不会显示为“无风险”。"/>
          <Form.Item name="external_due_diligence_enabled" label="启用 Exa 公开尽调" valuePropName="checked"><Switch checkedChildren="开启" unCheckedChildren="关闭" /></Form.Item>
          <Form.Item name="external_due_diligence_recent_days" label="第三方信用/经营动态检索窗口（天）"><InputNumber min={30} max={730} style={{width:'100%'}}/></Form.Item>
          <Form.Item name="external_due_diligence_max_results" label="每类查询最大结果数"><InputNumber min={2} max={12} style={{width:'100%'}}/></Form.Item>
          <Form.Item name="external_due_diligence_timeout_seconds" label="单次 MCP 超时（秒）"><InputNumber min={5} max={60} style={{width:'100%'}}/></Form.Item>
        </Card>
      </Col>
    </Row>

    <Card className="settings-save-card"><Space><Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>保存系统设置</Button><Button onClick={load}>重新读取</Button></Space></Card>
  </Form>
}
