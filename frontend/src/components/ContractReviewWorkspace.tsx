import { useEffect, useMemo, useRef, useState } from 'react'
import { message } from 'antd'
import { api } from '../services/api'
import type { ContractPreview, Report, ReviewJobStatus } from '../types'
import ContractLivePanel from './ContractLivePanel'
import ContractPreviewPanel from './ContractPreview'

type Props = { jobId: string; report?: Report | null; onStatusChange?: (status: ReviewJobStatus) => void }

export default function ContractReviewWorkspace({ jobId, report, onStatusChange }: Props) {
  const [preview, setPreview] = useState<ContractPreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(true)
  const [status, setStatus] = useState<ReviewJobStatus | null>(null)
  const [activeAnchor, setActiveAnchor] = useState<any>(null)
  const statusChangeRef = useRef(onStatusChange)

  useEffect(() => {
    statusChangeRef.current = onStatusChange
  }, [onStatusChange])

  useEffect(() => {
    let cancelled = false
    setPreviewLoading(true)
    api.reviewPreview(jobId).then(result => { if (!cancelled) setPreview(result) }).catch(error => { if (!cancelled) message.error(`合同预览加载失败：${error?.message || error}`) }).finally(() => { if (!cancelled) setPreviewLoading(false) })
    return () => { cancelled = true }
  }, [jobId])

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const next = await api.reviewStatus(jobId)
        if (cancelled) return
        setStatus(next); statusChangeRef.current?.(next)
        if (next.status === 'running') timer = window.setTimeout(poll, 1000)
      } catch (error: any) {
        if (!cancelled) message.error(`合同 Agent 审查进度读取失败：${error?.message || error}`)
      }
    }
    poll()
    return () => { cancelled = true; if (timer) window.clearTimeout(timer) }
  }, [jobId])

  const finalReport = report || status?.result || null
  const anchors = useMemo(() => {
    const sources = [...(status?.live_evidence || []), ...(finalReport?.risks || []), ...(finalReport?.review_hints || [])]
    return Array.from(new Map(sources.filter((item: any) => item && (item.source_ref || item.evidence || item.evidence_quote)).map((item: any, index: number) => [`${item.clause_id || ''}:${item.source_ref || ''}:${item.rule_id || index}`, item])).values())
  }, [finalReport, status?.live_evidence])
  const selectSource = (source: any) => { setActiveAnchor(source) }

  return <div className="contract-review-workspace"><ContractPreviewPanel filename={preview?.filename || finalReport?.filename} records={preview?.records || []} anchors={anchors} activeAnchor={activeAnchor} loading={previewLoading} error={preview?.error} onSelectAnchor={selectSource} /><ContractLivePanel running={status?.status === 'running'} status={status} report={finalReport} onSelectSource={selectSource} /></div>
}
