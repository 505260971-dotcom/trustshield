import { useEffect, useMemo, useState } from 'react'
import { Alert, AutoComplete, Button, Card, DatePicker, Form, Input, List, Select, Space, Steps, Typography, Upload, message } from 'antd'
import { ArrowLeftOutlined, ArrowRightOutlined, DeleteOutlined, FileAddOutlined, FileTextOutlined, SafetyCertificateOutlined, UploadOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { CreditCase, CustomerWorkspace } from '../types'

type Props = { onCreated: (caseId: string) => void; initialCustomerKey?: string }
const { Dragger } = Upload
const { Text } = Typography

export default function ReviewPage({ onCreated, initialCustomerKey }: Props) {
  const [form] = Form.useForm()
  const [step, setStep] = useState(0)
  const [mainFile, setMainFile] = useState<File | null>(null)
  const [attachments, setAttachments] = useState<File[]>([])
  const [credits, setCredits] = useState<CreditCase[]>([])
  const [customers, setCustomers] = useState<CustomerWorkspace[]>([])
  const [creditWarning, setCreditWarning] = useState(false)
  const [busy, setBusy] = useState(false)
  const selectedCreditId = Form.useWatch('credit_case_id', form)

  const loadCredits = async (customerName?: string) => {
    const customer = String(customerName ?? form.getFieldValue('customer_name') ?? '').trim()
    if (!customer) return message.info('请先选择或填写客户名称')
    try {
      const result = await api.creditDecisions(customer)
      setCredits(result.items)
      setCreditWarning(!result.items.length)
      if (result.items.length === 1) form.setFieldValue('credit_case_id', result.items[0].case_id)
      if (!result.items.length) form.setFieldValue('credit_case_id', undefined)
    } catch (error: any) { message.error(error?.message || '加载客户信审失败') }
  }

  useEffect(() => {
    api.customerWorkspaces().then(result => setCustomers(result.items || [])).catch(() => {})
    if (!initialCustomerKey) return
    api.customerWorkspace(initialCustomerKey).then(async customer => {
      form.setFieldValue('customer_name', customer.customer_name)
      await loadCredits(customer.customer_name)
    }).catch(error => message.error(error?.message || '未能载入客户信息'))
  }, [initialCustomerKey])

  const selectCustomer = async (customerName: string) => {
    form.setFieldValue('customer_name', customerName)
    await loadCredits(customerName)
  }
  const addAttachment = (file: File) => {
    setAttachments(existing => existing.some(item => item.name === file.name && item.size === file.size) ? existing : [...existing, file])
    return false
  }
  const next = async () => {
    try {
      if (step === 0) {
        const value = await form.validateFields(['customer_name'])
        await loadCredits(value.customer_name)
      }
      if (step === 1) await form.validateFields(['credit_case_id', 'business_type', 'priority'])
      setStep(current => Math.min(2, current + 1))
    } catch { /* Ant Design already displays field guidance */ }
  }
  const submit = async () => {
    try {
      const value = await form.validateFields()
      if (!mainFile) return message.warning('请上传一份主合同后再提交')
      setBusy(true)
      const root = await api.createCaseCenter({ customer_name: value.customer_name, business_type: value.business_type, credit_case_id: value.credit_case_id, priority: value.priority, due_at: value.due_at?.valueOf() / 1000, request_note: value.request_note })
      await api.upload(mainFile, { case_id: root.case_id, credit_case_id: value.credit_case_id, business_type: value.business_type, document_role: 'main' })
      for (const file of attachments) await api.upload(file, { case_id: root.case_id, credit_case_id: value.credit_case_id, business_type: value.business_type, document_role: 'annex' })
      message.success(`案件已创建，主合同和 ${attachments.length} 份关联材料正在进入系统审查`)
      onCreated(root.case_id)
    } catch (error: any) { if (!error?.errorFields) message.error(error?.message || '提交失败') } finally { setBusy(false) }
  }
  const customerOptions = useMemo(() => customers.map(customer => ({ value: customer.customer_name, label: <Space><span>{customer.customer_name}</span>{customer.latest_credit?.status === 'approved' ? <span className="customer-option-status">有效信审 V{customer.latest_credit.version}</span> : <span className="customer-option-status is-warning">暂无有效信审</span>}</Space> })), [customers])
  const selectedCredit = credits.find(item => item.case_id === selectedCreditId)

  return <div className="review-request-page">
    <Card title={<Space><FileAddOutlined />发起合同审查</Space>} extra={step === 2 ? <Button type="primary" loading={busy} onClick={submit}>创建案件并提交审查</Button> : null}>
      <Steps className="review-request-steps" current={step} responsive items={[{ title: '选择客户' }, { title: '确认信审' }, { title: '上传合同' }]} />
      <Form form={form} layout="vertical" initialValues={{ business_type: '一般', priority: 'normal' }} className="review-request-form">
        {step === 0 && <section className="request-step-panel">
          <Typography.Title level={4}>客户</Typography.Title>
          <Form.Item name="customer_name" label="客户名称" rules={[{ required: true, message: '请选择或填写客户名称' }]}>
            <AutoComplete options={customerOptions} placeholder="搜索已有客户，或输入新客户名称" filterOption={(input, option) => String(option?.value || '').toLowerCase().includes(input.toLowerCase())} onSelect={selectCustomer} onBlur={() => loadCredits()} />
          </Form.Item>
          {creditWarning && <Alert type="warning" showIcon message="该客户暂无可用的已生效信审版本" description={<Space direction="vertical" size={4}><span>合同不能直接进入正式审查。请先完成客户信审审批，再返回发起合同。</span><Button size="small" type="primary" icon={<SafetyCertificateOutlined />} onClick={() => { window.location.hash = '/credit/new' }}>先发起客户信审</Button></Space>} />}
        </section>}

        {step === 1 && <section className="request-step-panel">
          <Typography.Title level={4}>合同信息</Typography.Title>
          {!credits.length && <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="没有可绑定的有效信审" />}
          <div className="review-meta-grid case-create-grid">
            <Form.Item name="credit_case_id" label="已生效信审版本" rules={[{ required: true, message: '必须绑定已生效信审版本' }]}><Select placeholder="选择客户已生效的信审版本" options={credits.map(item => ({ value: item.case_id, label: `V${item.version} · 账期≤${item.conditions.max_payment_days}天 · 额度≤${item.conditions.max_credit_amount.toLocaleString()} ${item.conditions.currency}` }))} dropdownRender={menu => <><Button type="link" icon={<SafetyCertificateOutlined />} onClick={() => loadCredits()}>刷新信审版本</Button>{menu}</>} /></Form.Item>
            <Form.Item name="business_type" label="合同业务类型" rules={[{ required: true }]}><Select options={['一般', '模塑一体', 'TKM', 'TKP', '采购订单'].map(value => ({ value, label: value }))} /></Form.Item>
            <Form.Item name="priority" label="业务紧急度" rules={[{ required: true }]}><Select options={[{ value: 'low', label: '低' }, { value: 'normal', label: '普通' }, { value: 'high', label: '高' }, { value: 'urgent', label: '紧急' }]} /></Form.Item>
            <Form.Item name="due_at" label="期望完成时间"><DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="request_note" label="申请说明" className="request-note-field"><Input.TextArea rows={3} placeholder="说明签约背景、需重点确认的风险或交付要求" /></Form.Item>
          </div>
          {selectedCredit && <Card size="small" className="credit-boundary-card" title="本合同将遵守的信审边界"><div><span>额度上限 <b>{selectedCredit.conditions.max_credit_amount.toLocaleString()} {selectedCredit.conditions.currency}</b></span><span>最长账期 <b>{selectedCredit.conditions.max_payment_days} 天</b></span><span>最低预付款 <b>{selectedCredit.conditions.min_prepayment_ratio}%</b></span><span>付款方式 <b>{selectedCredit.conditions.allowed_payment_methods.join('、')}</b></span><span>VMI/JIT <b>{selectedCredit.conditions.allow_vmi_jit ? '允许' : '不允许'}</b></span></div></Card>}
        </section>}

        {step === 2 && <section className="request-step-panel">
          <Typography.Title level={4}>上传合同文件</Typography.Title>
          <div className="document-upload-grid">
            <div><Text strong>主合同 <Text type="danger">（必传，仅 1 份）</Text></Text><Dragger className="main-contract-uploader" multiple={false} showUploadList={false} disabled={busy} accept=".docx,.pdf,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.bmp" beforeUpload={file => { setMainFile(file as File); return false }}><p className="ant-upload-drag-icon"><FileTextOutlined /></p><p className="ant-upload-text">{mainFile ? mainFile.name : '拖入或选择主合同'}</p></Dragger>{mainFile && <List size="small" bordered dataSource={[mainFile]} renderItem={file => <List.Item actions={[<Button key="remove" type="link" danger icon={<DeleteOutlined />} onClick={() => setMainFile(null)}>移除</Button>]}><List.Item.Meta avatar={<FileTextOutlined />} title={file.name} description={`${(file.size / 1024).toFixed(1)} KB · 主合同`} /></List.Item>} />}</div>
            <div><Text strong>关联材料 <Text type="secondary">（可选）</Text></Text><Dragger className="annex-uploader" multiple showUploadList={false} disabled={busy} accept=".docx,.pdf,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.bmp" beforeUpload={file => addAttachment(file as File)}><p className="ant-upload-drag-icon"><UploadOutlined /></p><p className="ant-upload-text">上传关联材料</p></Dragger>{attachments.length > 0 && <List size="small" bordered dataSource={attachments} renderItem={file => <List.Item actions={[<Button key="remove" type="link" danger icon={<DeleteOutlined />} onClick={() => setAttachments(files => files.filter(item => item !== file))}>移除</Button>]}><List.Item.Meta avatar={<FileTextOutlined />} title={file.name} description={`${(file.size / 1024).toFixed(1)} KB · 关联材料`} /></List.Item>} />}</div>
          </div>
        </section>}
      </Form>
      <div className="request-wizard-actions"><Button disabled={step === 0 || busy} icon={<ArrowLeftOutlined />} onClick={() => setStep(current => current - 1)}>上一步</Button>{step < 2 ? <Button type="primary" icon={<ArrowRightOutlined />} iconPosition="end" onClick={next}>继续</Button> : <Button type="primary" loading={busy} icon={<FileAddOutlined />} onClick={submit}>创建案件并提交审查</Button>}</div>
    </Card>
  </div>
}
