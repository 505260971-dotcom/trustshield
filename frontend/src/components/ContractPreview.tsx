import { useEffect, useMemo, useRef } from 'react'
import { Empty, Spin, Tag, Typography } from 'antd'
import { FileTextOutlined, HighlightOutlined, LinkOutlined } from '@ant-design/icons'
import type { ContractPreviewRecord } from '../types'

const { Text } = Typography

type Anchor = {
  clause_id?: string
  source_ref?: string
  page?: number
  evidence_quote?: string
  evidence?: string
  rule_id?: string
}

type Props = {
  filename?: string
  records: ContractPreviewRecord[]
  anchors: Anchor[]
  activeAnchor?: Anchor | null
  loading?: boolean
  error?: string
  onSelectAnchor?: (anchor: Anchor) => void
}

const compact = (value: unknown) => String(value || '').replace(/\s+/g, '').toLowerCase()

const matches = (anchor: Anchor, record: ContractPreviewRecord) => {
  const recordRef = compact(record.source_ref)
  const anchorRef = compact(anchor.source_ref)
  if (anchorRef && recordRef && (anchorRef === recordRef || anchorRef.includes(recordRef) || recordRef.includes(anchorRef))) return true
  const quote = compact(anchor.evidence_quote || anchor.evidence)
  return Boolean(quote && quote.length >= 4 && compact(record.text).includes(quote.slice(0, 180)))
}

const highlightText = (text: string, anchors: Anchor[]) => {
  const terms = anchors.map(anchor => anchor.evidence_quote || anchor.evidence || '').map(value => String(value).trim()).filter(value => value.length >= 4).sort((a, b) => b.length - a.length).slice(0, 3)
  if (!terms.length) return text
  const pattern = new RegExp(`(${terms.map(item => item.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'ig')
  return text.split(pattern).map((part, index) => terms.some(term => term.toLowerCase() === part.toLowerCase()) ? <mark key={index}>{part}</mark> : <span key={index}>{part}</span>)
}

export default function ContractPreview({ filename, records, anchors, activeAnchor, loading, error, onSelectAnchor }: Props) {
  const refs = useRef<Record<number, HTMLDivElement | null>>({})
  const matched = useMemo(() => records.map((record, index) => ({ record, index, anchors: anchors.filter(anchor => matches(anchor, record)) })), [anchors, records])
  const markedCount = matched.filter(item => item.anchors.length > 0).length

  useEffect(() => {
    if (!activeAnchor) return
    const item = matched.find(candidate => matches(activeAnchor, candidate.record))
    if (item) window.setTimeout(() => refs.current[item.index]?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 0)
  }, [activeAnchor, matched])

  return <div className="contract-preview-panel">
    <div className="contract-preview-heading">
      <div><Text strong><FileTextOutlined /> 原合同与证据定位</Text><Text type="secondary">Agent 读取或风险引用的合同来源，会在原文中高亮并保留下划线。</Text></div>
      <Tag color={markedCount ? 'gold' : 'default'} icon={<HighlightOutlined />}>{markedCount ? `已标注 ${markedCount} 段` : '等待证据'}</Tag>
    </div>
    <div className="contract-preview-meta"><Text strong>{filename || '原合同'}</Text><Text type="secondary">{records.length} 个解析记录</Text></div>
    {loading ? <div className="contract-preview-loading"><Spin tip="正在读取合同原文…" /></div> : !records.length ? <div className="contract-preview-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={error || '暂时没有可展示的合同原文'} /></div> : <div className="contract-preview-scroll">
      {matched.map(({ record, index, anchors: recordAnchors }) => <div
        key={`${record.source_ref || 'record'}-${index}`}
        ref={node => { refs.current[index] = node }}
        className={`contract-preview-record ${recordAnchors.length ? 'is-evidence' : ''} ${activeAnchor && matches(activeAnchor, record) ? 'is-active' : ''}`}
        onClick={() => recordAnchors[0] && onSelectAnchor?.(recordAnchors[0])}
      >
        <div className="contract-preview-record-meta"><Text code>{record.source_ref || `记录 ${index + 1}`}</Text>{record.start_page && <Tag>{`第 ${record.start_page} 页`}</Tag>}{record.source_kind && <Tag color={record.source_kind === 'table' || record.source_kind === 'sheet' ? 'blue' : record.source_kind === 'ocr' ? 'orange' : 'default'}>{record.source_kind === 'table' ? '表格' : record.source_kind === 'sheet' ? '工作表' : record.source_kind === 'ocr' ? 'OCR' : '正文'}</Tag>}{recordAnchors.map((anchor, anchorIndex) => <Tag key={`${anchor.source_ref || anchor.rule_id}-${anchorIndex}`} color="gold" icon={<LinkOutlined />} onClick={event => { event.stopPropagation(); onSelectAnchor?.(anchor) }}>{anchor.rule_id || anchor.source_ref || '风险证据'}</Tag>)}</div>
        <div className="contract-preview-record-text">{highlightText(record.text, recordAnchors)}</div>
      </div>)}
    </div>}
  </div>
}
