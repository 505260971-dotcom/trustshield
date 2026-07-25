import { useEffect, useState } from 'react'
import { Drawer, Spin, Empty, message, Button } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import type { Report } from '../types'
import ReportView from './ReportView'

export default function HistoryDetail ({ id, onClose }: { id: string|null; onClose: ()=>void }) {
  const [loading, setLoading] = useState(false)
  const [report, setReport] = useState<Report | null>(null)
  useEffect(() => {
    if (!id) { setReport(null); return }
    setLoading(true); setReport(null)
    api.historyDetail(id).then(r => setReport(r.report)).catch(e=> message.error('加载失败:'+e.message))
      .finally(()=> setLoading(false))
  }, [id])
  return (
    <Drawer open={!!id} onClose={onClose} width={1000} destroyOnClose
      title="历史审查详情" extra={<Button icon={<ArrowLeftOutlined/>} onClick={onClose}>返回列表</Button>}>
      {loading ? <div style={{textAlign:'center',padding:60}}><Spin tip="加载中…"/></div>
       : report ? <ReportView report={report} jobId={id ?? undefined}/>
       : !id ? null : <Empty/>}
    </Drawer>
  )
}
