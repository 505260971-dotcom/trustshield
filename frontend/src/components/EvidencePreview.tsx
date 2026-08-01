import { useEffect, useMemo, useRef } from 'react'
import { Empty, Select, Spin, Tag, Typography } from 'antd'
import { FileTextOutlined, HighlightOutlined, LinkOutlined } from '@ant-design/icons'
import type { CreditDocument, CreditDocumentPreview, CreditSourceRecord } from '../types'

const { Text } = Typography

type EvidenceAnchor = {
  chunk_id?: string
  document_id?: string
  source_ref?: string
  page?: number
  source_kind?: string
  preview?: string
  text?: string
  evidence_quote?: string
  claim_id?: string
}

type Props = {
  documents: CreditDocument[]
  documentPreview: CreditDocumentPreview | null
  selectedDocumentId: string
  onSelectDocument: (documentId: string) => void
  activeAnchor?: EvidenceAnchor | null
  anchors: EvidenceAnchor[]
  loading?: boolean
  onSelectAnchor?: (anchor: EvidenceAnchor) => void
}

const documentTypeText: Record<string, string> = {
  financial_report: '客户财报',
  credit_report: '第三方信用报告',
  trade_history: '交易/回款记录',
  application: '申请材料',
  approval_evidence: '特别审批依据',
  other: '其他材料',
}
const EMPTY_RECORDS: CreditSourceRecord[] = []

const compact = (value: unknown) => String(value || '').replace(/\s+/g, '').toLowerCase()

const sourceMatchesRecord = (anchor: EvidenceAnchor, record: CreditSourceRecord, documentId: string, index: number) => {
  const expectedChunkId = `${documentId}:R${index + 1}`
  if (anchor.chunk_id && anchor.chunk_id === expectedChunkId) return true
  if (anchor.document_id && anchor.document_id !== documentId) return false
  const source = compact(record.source_ref)
  const anchorSource = compact(anchor.source_ref)
  if (anchorSource && (anchorSource === source || anchorSource.includes(source) || source.includes(anchorSource))) return true
  const quote = compact(anchor.evidence_quote || anchor.preview || anchor.text)
  return Boolean(quote && quote.length >= 4 && compact(record.text).includes(quote.slice(0, 180)))
}

const highlightText = (text: string, terms: string[]) => {
  const useful = terms.map(item => String(item || '').trim()).filter(item => item.length >= 4).sort((a, b) => b.length - a.length).slice(0, 3)
  if (!useful.length) return text
  const pattern = new RegExp(`(${useful.map(item => item.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'ig')
  return text.split(pattern).map((part, index) => useful.some(term => term.toLowerCase() === part.toLowerCase()) ? <mark key={index}>{part}</mark> : <span key={index}>{part}</span>)
}

export default function EvidencePreview({ documents, documentPreview, selectedDocumentId, onSelectDocument, activeAnchor, anchors, loading, onSelectAnchor }: Props) {
  const recordRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const selectedDocument = documents.find(item => item.document_id === selectedDocumentId)
  const records = documentPreview?.records ?? EMPTY_RECORDS
  const matched = useMemo(() => records.map((record, index) => ({
    record,
    index,
    anchors: anchors.filter(anchor => sourceMatchesRecord(anchor, record, selectedDocumentId, index)),
  })), [anchors, records, selectedDocumentId])
  const markedCount = matched.filter(item => item.anchors.length > 0).length

  useEffect(() => {
    if (!activeAnchor || !selectedDocumentId) return
    const target = matched.find(item => item.anchors.some(anchor => anchor.chunk_id === activeAnchor.chunk_id || sourceMatchesRecord(activeAnchor, item.record, selectedDocumentId, item.index)))
    if (target) {
      window.setTimeout(() => recordRefs.current[`${selectedDocumentId}:${target.index}`]?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 0)
    }
  }, [activeAnchor, matched, selectedDocumentId])

  return <div className="credit-evidence-preview">
    <div className="credit-preview-heading">
      <div>
        <Text strong><FileTextOutlined /> 材料原文与证据定位</Text>
        <Text type="secondary">Agent 读取到的来源会在下方高亮；点击来源标签可跳到对应材料行。</Text>
      </div>
      <Tag color={markedCount ? 'gold' : 'default'} icon={<HighlightOutlined />}>{markedCount ? `已标注 ${markedCount} 行` : '等待来源'}</Tag>
    </div>
    <div className="credit-preview-toolbar">
      <Select
        value={selectedDocumentId || undefined}
        placeholder="选择要预览的材料"
        style={{ minWidth: 250, flex: '1 1 250px' }}
        options={documents.map(item => ({ value: item.document_id, label: `${documentTypeText[item.document_type] || item.document_type} · ${item.original_name}` }))}
        onChange={onSelectDocument}
        notFoundContent="暂无信审材料"
      />
      {selectedDocument && <Text type="secondary">{documentPreview?.total ?? selectedDocument.text_record_count ?? 0} 个来源记录 · {documentPreview?.status === 'partial' ? '部分页面待 OCR' : documentPreview?.status === 'failed' ? '解析失败' : '可核验'}</Text>}
    </div>
    {loading ? <div className="credit-preview-loading"><Spin tip="正在读取材料文字资产…" /></div> : !documents.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先上传财报、信用报告或交易材料" /> : !records.length ? <div className="credit-preview-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={documentPreview?.error || '当前材料没有可展示的文字记录'} /></div> : <div className="credit-preview-scroll">
      {matched.map(({ record, index, anchors: recordAnchors }) => <div
        key={`${record.source_ref}-${index}`}
        ref={node => { recordRefs.current[`${selectedDocumentId}:${index}`] = node }}
        className={`credit-preview-record ${recordAnchors.length ? 'is-evidence' : ''} ${activeAnchor && recordAnchors.some(anchor => anchor.chunk_id === activeAnchor.chunk_id) ? 'is-active' : ''}`}
        onClick={() => recordAnchors[0] && onSelectAnchor?.(recordAnchors[0])}
      >
        <div className="credit-preview-record-meta">
          <Text code>{record.source_ref || `记录 ${index + 1}`}</Text>
          {record.start_page && <Tag>{`第 ${record.start_page} 页`}</Tag>}
          {record.source_kind && <Tag color={record.source_kind === 'ocr' ? 'orange' : record.source_kind === 'table' || record.source_kind === 'sheet' ? 'blue' : 'default'}>{record.source_kind === 'ocr' ? 'OCR' : record.source_kind === 'table' ? '表格' : record.source_kind === 'sheet' ? '工作表' : '正文'}</Tag>}
          {recordAnchors.map((anchor, sourceIndex) => <Tag key={`${anchor.chunk_id || anchor.source_ref}-${sourceIndex}`} color="gold" icon={<LinkOutlined />} onClick={event => { event.stopPropagation(); onSelectAnchor?.(anchor) }}>{anchor.source_ref || anchor.chunk_id || 'Agent 来源'}</Tag>)}
        </div>
        <div className="credit-preview-record-text">{highlightText(record.text, recordAnchors.map(anchor => anchor.evidence_quote || anchor.preview || ''))}</div>
      </div>)}
    </div>}
  </div>
}
