import { useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Form, Input, Row, Space, Spin, Switch, Tag, Typography, message } from 'antd'
import { ApiOutlined, ExperimentOutlined, SafetyCertificateOutlined, SaveOutlined } from '@ant-design/icons'
import { api } from '../services/api'

const { Text } = Typography

type Settings = {
  llm_api_base: string; llm_model: string; llm_api_key_configured: boolean
  enable_masking: boolean; smart_mask: boolean
  mask_llm_api_base: string; mask_llm_model: string; mask_llm_api_key_configured: boolean
}
type Props = { onSaved?: () => void }

export default function SettingsPage({ onSaved }: Props) {
  const [form] = Form.useForm()
  const [settings, setSettings] = useState<Settings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState<'llm' | 'mask' | null>(null)
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
      ;['llm_api_key', 'mask_llm_api_key'].forEach(key => { if (!payload[key]) delete payload[key] })
      const result = await api.patchAdminSettings(payload)
      setSettings(result)
      form.setFieldsValue(result)
      setRequiresRestart(!!result.requires_restart)
      message.success('系统配置已保存')
      onSaved?.()
    } catch (error: any) { message.error(`保存失败：${error?.message || '请检查配置'}`) } finally { setSaving(false) }
  }

  const test = async (kind: 'llm' | 'mask') => {
    const values = form.getFieldsValue(true)
    setTesting(kind)
    try {
      const prefix = kind === 'llm' ? 'llm' : 'mask_llm'
      const result = await api.testAdminSettings({ kind, api_base: values[`${prefix}_api_base`], api_key: values[`${prefix}_api_key`], model: values[`${prefix}_model`] })
      if (result.ok) message.success(`${kind === 'llm' ? 'Agent 审查模型' : '合同脱敏模型'}连接成功（${result.latency_ms} ms）`)
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
          <Form.Item name="mask_llm_model" label="模型名称"><Input placeholder="例如 qwen3.5:9b" /></Form.Item>
          <Form.Item name="mask_llm_api_key" label={<Space>API Key {settings.mask_llm_api_key_configured && <Tag color="green">已配置</Tag>}</Space>}><Input.Password placeholder={settings.mask_llm_api_key_configured ? '已配置，留空保持不变' : '输入模型服务 API Key'} /></Form.Item>
        </Card>
      </Col>
    </Row>

    <Card className="settings-save-card"><Space><Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>保存系统设置</Button><Button onClick={load}>重新读取</Button></Space></Card>
  </Form>
}
