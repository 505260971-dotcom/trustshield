import { useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Divider, Form, Input, InputNumber, Row, Space, Spin, Switch, Tag, Typography, message } from 'antd'
import { ApiOutlined, ExperimentOutlined, SafetyCertificateOutlined, SaveOutlined } from '@ant-design/icons'
import { api } from '../services/api'

const { Text, Paragraph } = Typography

type Settings = {
  llm_api_base: string; llm_model: string; llm_api_key_configured: boolean
  ollama_base: string; enable_masking: boolean; smart_mask: boolean
  mask_llm_api_base: string; mask_llm_model: string; mask_llm_api_key_configured: boolean
  financial_llm_extraction: boolean; financial_llm_mode: string; financial_llm_api_base: string; financial_llm_model: string; financial_llm_api_key_configured: boolean
  rerank_enabled: boolean; rerank_allow_remote_financial_data: boolean; rerank_base_url: string; rerank_model: string; rerank_api_key_configured: boolean
  embedding_enabled: boolean; embedding_allow_remote_financial_data: boolean; embedding_base_url: string; embedding_model: string; embedding_dimensions: number; embedding_api_key_configured: boolean
  storage: 'plain_config_file'
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
      ;['llm_api_key', 'mask_llm_api_key', 'financial_llm_api_key', 'rerank_api_key', 'embedding_api_key'].forEach(key => {
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

  const test = async (kind:'llm'|'rerank'|'embedding') => {
    const values = form.getFieldsValue(true)
    setTesting(true)
    try {
      const prefix = kind==='llm'?'llm':kind
      const result = await api.testAdminSettings({
        kind,
        api_base: values[`${prefix}_api_base`] || values[`${prefix}_base_url`],
        api_key: values[`${prefix}_api_key`],
        model: values[`${prefix}_model`],
        dimensions: kind==='embedding' ? values.embedding_dimensions : undefined,
      })
      if (result.ok) message.success(`${kind==='llm'?'主模型':kind==='rerank'?'Rerank':'Embedding'} 连接成功（${result.latency_ms} ms）`)
      else message.warning(result.message || '连接失败')
    } catch (error: any) {
      message.error(`连接测试失败：${error?.message || '请求失败'}`)
    } finally {
      setTesting(false)
    }
  }

  const clearLegacyEnv = async () => {
    try {
      const result = await api.clearLegacyModelEnv()
      setRequiresRestart(!!result.requires_restart)
      message.success(result.removed?.length ? `已清理 .env 中 ${result.removed.length} 项旧模型配置` : '未发现需要清理的旧模型配置')
    } catch (error: any) {
      message.error(`清理失败：${error?.message || '请检查 config.json 配置'}`)
    }
  }

  if (loading || !settings) return <Card><Spin /> <Text type="secondary">正在加载系统配置…</Text></Card>

  return <Form form={form} layout="vertical" onFinish={save} initialValues={settings}>
    <Alert
      type="info"
      showIcon
      icon={<SafetyCertificateOutlined />}
      message="管理员系统设置"
      description="模型配置与 API Key 以明文方式保存到 backend/data/config.json；浏览器不会回显密钥，审计日志也不会保存密钥内容。保存后重启后端生效。请限制该文件的访问权限，认证密钥和数据库加密主密钥仍由部署环境管理。"
      style={{ marginBottom: 16 }}
    />

    {requiresRestart && <Alert type="warning" showIcon message="配置已保存，重启后端后生效" description="在 contractguard 目录执行 .\dev.ps1，或按你的部署方式重启 API 服务。" style={{ marginBottom: 16 }} />}

    <Row gutter={[16, 16]}>
      <Col xs={24} xl={12}>
        <Card title={<Space><ApiOutlined />主审查模型</Space>} extra={<Button icon={<ExperimentOutlined />} loading={testing} onClick={()=>test('llm')}>测试连接</Button>}>
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
        <Card title={<Space><SafetyCertificateOutlined />脱敏与专用模型</Space>}>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item name="enable_masking" label="合同脱敏" valuePropName="checked" extra="建议保持开启">
                <Switch checkedChildren="开启" unCheckedChildren="关闭" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="smart_mask" label="启用智能脱敏" valuePropName="checked" extra="演示环境可使用远端替代模型；正式部署切换至本地/内网模型。未配置时使用正则快速脱敏">
                <Switch checkedChildren="开启" unCheckedChildren="关闭" />
              </Form.Item>
            </Col>
          </Row>
          <Divider style={{ margin: '4px 0 16px' }} />
          <Form.Item name="mask_llm_api_base" label="脱敏专用模型 API 地址"><Input placeholder="本地 http://localhost:11434/v1；演示远端 https://provider/v1" /></Form.Item>
          <Form.Item name="mask_llm_model" label="脱敏专用模型"><Input placeholder="例如 qwen3.5:9b 或远端替代模型" /></Form.Item>
          <Form.Item name="mask_llm_api_key" label={<Space>专用模型 Key {settings.mask_llm_api_key_configured && <Tag color="green">已配置</Tag>}</Space>}><Input.Password placeholder={settings.mask_llm_api_key_configured ? '已配置，留空保持不变' : '本地 Ollama 通常填写 ollama；远端填写对应 Key'} /></Form.Item>
        </Card>
      </Col>
    </Row>

    <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
      <Col xs={24} xl={12}>
        <Card title="信审 ReAct 财报模型">
          <Form.Item name="financial_llm_extraction" label="启用财报证据抽取" valuePropName="checked"><Switch checkedChildren="开启" unCheckedChildren="关闭" /></Form.Item>
          <Form.Item name="financial_llm_mode" label="部署模式" extra="remote_substitute 用于受控演示；正式财务材料建议使用 local_or_intranet"><Input placeholder="remote_substitute 或 local_or_intranet" /></Form.Item>
          <Form.Item name="financial_llm_api_base" label="专用模型 API 地址" extra="留空则继承主审查模型"><Input placeholder="留空继承主模型" /></Form.Item>
          <Form.Item name="financial_llm_model" label="专用财报模型" extra="留空则继承主审查模型"><Input placeholder="留空继承主模型" /></Form.Item>
          <Form.Item name="financial_llm_api_key" label={<Space>专用模型 Key {settings.financial_llm_api_key_configured && <Tag color="green">已配置</Tag>}</Space>}><Input.Password placeholder={settings.financial_llm_api_key_configured?'已配置，留空保持不变':'留空继承主模型 Key'} /></Form.Item>
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Card title="信审证据检索 · 百炼向量召回与精排">
          <Alert showIcon type="warning" style={{marginBottom:12}} message="仅在完成财务数据出境/传输评估后开启" description="Embedding 用于词法候选的语义补充召回，结果再交由 qwen3-rerank 精排；两项都不会直接生成财务事实或授信结论。" />
          <Divider plain>Embedding（百炼 OpenAI 兼容 embeddings）</Divider>
          <Space wrap><Form.Item name="embedding_enabled" label="启用 Embedding" valuePropName="checked"><Switch /></Form.Item><Form.Item name="embedding_allow_remote_financial_data" label="授权发送财务证据" valuePropName="checked"><Switch /></Form.Item></Space>
          <Form.Item name="embedding_base_url" label="Embedding API 地址"><Input placeholder="https://dashscope.aliyuncs.com/compatible-api/v1" /></Form.Item>
          <Space wrap><Form.Item name="embedding_model" label="Embedding 模型"><Input style={{width:220}} placeholder="控制台中的模型 ID" /></Form.Item><Form.Item name="embedding_dimensions" label="输出维度（按控制台要求；0 为默认）"><InputNumber min={0} max={4096} /></Form.Item></Space>
          <Form.Item name="embedding_api_key" label={<Space>Embedding API Key {settings.embedding_api_key_configured&&<Tag color="green">已配置</Tag>}</Space>}><Input.Password placeholder={settings.embedding_api_key_configured?'已配置，留空保持不变':'输入百炼 API Key'} /></Form.Item>
          <Button icon={<ExperimentOutlined/>} loading={testing} onClick={()=>test('embedding')}>测试 Embedding</Button>
          <Divider plain>qwen3-rerank</Divider>
          <Space wrap><Form.Item name="rerank_enabled" label="启用 Rerank" valuePropName="checked"><Switch /></Form.Item><Form.Item name="rerank_allow_remote_financial_data" label="授权发送财务证据" valuePropName="checked"><Switch /></Form.Item></Space>
          <Form.Item name="rerank_base_url" label="Rerank API 地址"><Input placeholder="https://dashscope.aliyuncs.com/compatible-api/v1" /></Form.Item>
          <Form.Item name="rerank_model" label="Rerank 模型"><Input placeholder="qwen3-rerank" /></Form.Item>
          <Form.Item name="rerank_api_key" label={<Space>Rerank API Key {settings.rerank_api_key_configured&&<Tag color="green">已配置</Tag>}</Space>}><Input.Password placeholder={settings.rerank_api_key_configured?'已配置，留空保持不变':'输入百炼 API Key'} /></Form.Item>
          <Button icon={<ExperimentOutlined/>} loading={testing} onClick={()=>test('rerank')}>测试 Rerank</Button>
        </Card>
      </Col>
    </Row>

    <Card style={{ marginTop: 16 }}>
      <Space>
        <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>保存系统设置</Button>
        <Button onClick={load}>重新读取</Button>
        <Button danger onClick={clearLegacyEnv}>清理 .env 中旧模型配置</Button>
        <Text type="secondary">当前配置由管理员维护，普通成员不可见。</Text>
      </Space>
    </Card>
  </Form>
}
