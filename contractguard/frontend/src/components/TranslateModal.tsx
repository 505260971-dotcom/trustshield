import { useState, useRef, useEffect } from 'react'
import { Modal, Select, Button, Table, Progress, Alert, Spin, Empty, Typography, Space, message } from 'antd'
import { TranslationOutlined, FileWordOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { TranslateItem, TranslateResult } from '../types'

const { Text } = Typography

const LANGS = [
  { value: 'en', label: '英语 English' },
  { value: 'vi', label: '越南语 Tiếng Việt' },
  { value: 'ja', label: '日本語 Japanese' },
  { value: 'es', label: 'Español 西班牙语' }
]

export default function TranslateModal ({ jobId, open, onClose, onTranslated }: {
  jobId?: string; open: boolean; onClose: ()=>void; onTranslated?: (lang: string, result: TranslateResult)=>void
}) {
  const [lang, setLang] = useState<string>('en')
  const [running, setRunning] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [steps, setSteps] = useState<string[]>([])
  const [result, setResult] = useState<TranslateResult | null>(null)
  const [err, setErr] = useState('')
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!open) {
      esRef.current?.close(); esRef.current = null
      setSteps([]); setResult(null); setErr(''); setRunning(false)
    }
  }, [open])

  const start = async (force=false) => {
    if (!jobId) { setErr('缺少任务 ID（job_id），无法翻译'); return }
    setRunning(true); setSteps([]); setResult(null); setErr('')
    try {
      const { tfid } = await api.translateStart(jobId, lang, force)
      const es = new EventSource(api.streamUrl(`/api/translate/stream/${tfid}`))
      esRef.current = es
      es.addEventListener('step', (e: MessageEvent) =>
        setSteps(p => p.length < 400 ? [...p, e.data] : p))
      es.addEventListener('done', (e: MessageEvent) => {
        const r = JSON.parse(e.data) as TranslateResult
        setResult(r); setRunning(false); es.close()
        onTranslated?.(lang, r)
      })
      es.addEventListener('error', (e: any) => {
        try { if (e.data) { setErr('翻译失败：'+String(e.data).slice(0,200)); setRunning(false); es.close(); return } } catch {}
        if (es.readyState === EventSource.CLOSED) { setRunning(false); return }
        setErr('翻译流中断，请重试'); setRunning(false); es.close()
      })
    } catch (e: any) {
      setErr('提交失败：'+(e?.message||String(e))); setRunning(false)
    }
  }

  const exportBilingual = async () => {
    if (!jobId) return
    setExporting(true)
    try {
      await api.exportWord(jobId, 'bilingual', `双语对照_${lang}.docx`, lang)
      message.success('双语对照稿已开始下载')
    } catch (e: any) {
      message.error('导出失败：'+(e?.message||String(e)))
    } finally { setExporting(false) }
  }

  const close = () => { esRef.current?.close(); esRef.current = null; onClose() }

  const cols = [
    { title: '条款', dataIndex: 'clause_id', width: 70 },
    { title: '原文', dataIndex: 'original',
      render:(v:string)=> <Text style={{whiteSpace:'pre-wrap', fontSize:13}}>{v}</Text> },
    { title: '译文', dataIndex: 'translated',
      render:(v:string)=> <Text style={{whiteSpace:'pre-wrap', fontSize:13}} type="success">{v}</Text> }
  ]

  return (
    <Modal title={<Space><TranslationOutlined/> 合同多语言翻译</Space>}
      open={open} onCancel={close} width={900} destroyOnClose
      footer={[
        <Button key="c" onClick={close}>关闭</Button>,
        result ? <Button key="b" icon={<FileWordOutlined/>} loading={exporting} onClick={exportBilingual}>导出双语对照稿</Button> : null,
        result ? <Button key="r" onClick={()=>start(true)} loading={running}>强制重译</Button> : null,
        <Button key="s" type="primary" loading={running} disabled={!jobId} onClick={()=>start(false)}>开始翻译</Button>
      ].filter(Boolean)}>
      <Alert type="info" showIcon style={{marginBottom:12}}
        message="翻译前会用审查时的脱敏映射重建令牌；远程模型只见 <MASK-...>，译文在本机还原后持久化，可一键导出段落后插入译文的双语稿。" />
      <Space style={{marginBottom:12}}>
        <Text>目标语言：</Text>
        <Select value={lang} onChange={setLang} style={{width:220}} options={LANGS} disabled={running}/>
      </Space>
      {err && <Alert type="error" showIcon message={err} style={{marginBottom:12}}/>}
      {running && <div style={{textAlign:'center', margin:'16px 0'}}><Spin tip="翻译中…"/><Progress percent={Math.min(95, steps.length*8)} status="active" style={{marginTop:12}}/><div style={{marginTop:8}}>{steps.slice(-3).map((s,i)=><div key={i}><Text type="secondary">{s}</Text></div>)}</div></div>}
      {!running && !result && !err && <Empty description="选择语言后开始翻译；结果会持久化，可供双语导出" />}
      {result && <Table size="small" rowKey="clause_id" columns={cols} dataSource={result.translated as TranslateItem[]} pagination={{pageSize:8}} scroll={{y:360}}/>}
    </Modal>
  )
}
