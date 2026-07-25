import { useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Divider, Form, Input, Row, Space, Spin, Switch, Tag, Typography, message } from 'antd'
import { ApiOutlined, ExperimentOutlined, SafetyCertificateOutlined, SaveOutlined } from '@ant-design/icons'
import { api } from '../services/api'

const { Text, Paragraph } = Typography

type Settings = {
  llm_api_base: string; llm_model: string; llm_api_key_configured: boolean
  ollama_base: string; enable_masking: boolean; smart_mask: boolean
  mask_llm_api_base: string; mask_llm_model: string; mask_llm_api_key_configured: boolean
}

type Props = { onSaved?: () => void }

export default function SettingsPage({ onSaved }: Props) {
  const [form] = Form.useForm()
  const [settings, setSettings] = useState<Settings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [requiresRestart, setRequiresRestart] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const value = await api.adminSettings()
      setSettings(value)
      form.setFieldsValue(value)
    } catch {
      message.error('系统配置加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const save = async (values: Record<string, any>) => {
    setSaving(true)
    try {
      const payload = { ...values }
      ;['llm_api_key', 'mask_llm_api_key'].forEach(key => {
        if (!payload[key]) delete payload[key]
      })
      const result = await api.patchAdminSettings(payload)
      setSettings(result)
      form.setFieldsValue(result)
      setRequiresRestart(!!result.requires_restart)
      message.success('系统配置已保存')
      onSaved?.()
    } catch (error: any) {
      message.error(`保存失败：${error?.message || '请检查配置'}`)
    } finally {
      setSaving(false)
    }
  }

  const test = async () => {
    const values = form.getFieldsValue(true)
    setTesting(true)
    try {
      const result = await api.testAdminSettings({
        kind: 'llm',
        api_base: values.llm_api_base,
        api_key: values.llm_api_key,
        model: values.llm_model,
      })
      if (result.ok) message.success(`主模型连接成功（${result.latency_ms} ms）`)
      else message.warning(result.message || '连接失败')
    } catch (error: any) {
      message.error(`连接测试失败：${error?.message || '请求失败'}`)
    } finally {
      setTesting(false)
    }
  }

  if (loading || !settings) return <Card><Spin /> <Text type="secondary">正在加载系统配置…</Text></Card>

  return <Form form={form} layout="vertical" onFinish={save} initialValues={settings}>
    <Alert
      type="info"
      showIcon
      icon={<SafetyCertificateOutlined />}
      message="管理员系统设置"
      description="配置只写入后端本机的 .env 文件。API Key 不会回显到浏览器，也不会写入审计日志；保存后请重启后端服务。规则候选使用词法门控，无需 Embedding。"
      style={{ marginBottom: 16 }}
    />

    {requiresRestart && <Alert type="warning" showIcon message="配置已保存，重启后端后生效" description="在 contractguard 目录执行 .\dev.ps1，或按你的部署方式重启 API 服务。" style={{ marginBottom: 16 }} />}

    <Row gutter={[16, 16]}>
      <Col xs={24} xl={12}>
        <Card title={<Space><ApiOutlined />主审查模型</Space>} extra={<Button icon={<ExperimentOutlined />} loading={testing} onClick={test}>测试连接</Button>}>
          <Form.Item name="llm_api_base" label="OpenAI 兼容 API 地址" extra="例如 https://api.openai.com/v1；本地 Ollama 可填写 http://localhost:11434/v1">
            <Input placeholder="https://your-provider.example/v1" />
          </Form.Item>
          <Form.Item name="llm_model" label="模型名称" rules={[{ max: 200 }]}>
            <Input placeholder="例如 qwen-plus、deepseek-chat" />
          </Form.Item>
          <Form.Item name="llm_api_key" label={<Space>API Key {settings.llm_api_key_configured && <Tag color="green">已配置</Tag>}</Space>}>
            <Input.Password placeholder={settings.llm_api_key_configured ? '已配置，留空保持不变' : '输入模型服务 API Key'} />
          </Form.Item>
          <Form.Item name="ollama_base" label="Ollama 地址（可选，健康检查/本地脱敏）">
            <Input placeholder="http://localhost:11434" />
          </Form.Item>
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>合同原文经过脱敏后才会发送给主模型。未配置时，上传评审会被安全门禁拦截。</Paragraph>
        </Card>
      </Col>

      <Col xs={24} xl={12}>
        <Card title={<Space><SafetyCertificateOutlined />脱敏与本地模型</Space>}>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item name="enable_masking" label="合同脱敏" valuePropName="checked" extra="建议保持开启">
                <Switch checkedChildren="开启" unCheckedChildren="关闭" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="smart_mask" label="启用本地智能脱敏" valuePropName="checked" extra="未配置模型时仍会使用正则快速脱敏">
                <Switch checkedChildren="开启" unCheckedChildren="关闭" />
              </Form.Item>
            </Col>
          </Row>
          <Divider style={{ margin: '4px 0 16px' }} />
          <Form.Item name="mask_llm_api_base" label="本地脱敏模型 API 地址"><Input placeholder="http://localhost:11434/v1" /></Form.Item>
          <Form.Item name="mask_llm_model" label="本地脱敏模型"><Input placeholder="例如 qwen3.5:9b" /></Form.Item>
          <Form.Item name="mask_llm_api_key" label={<Space>本地模型 Key {settings.mask_llm_api_key_configured && <Tag color="green">已配置</Tag>}</Space>}><Input.Password placeholder={settings.mask_llm_api_key_configured ? '已配置，留空保持不变' : '本地 Ollama 通常填写 ollama'} /></Form.Item>
        </Card>
      </Col>
    </Row>

    <Card style={{ marginTop: 16 }}>
      <Space>
        <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>保存系统设置</Button>
        <Button onClick={load}>重新读取</Button>
        <Text type="secondary">当前配置由管理员维护，普通成员不可见。</Text>
      </Space>
    </Card>
  </Form>
}
