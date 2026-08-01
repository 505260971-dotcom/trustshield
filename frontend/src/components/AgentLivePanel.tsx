import dayjs from 'dayjs'
import { Badge, Button, Card, Empty, List, Space, Tag, Typography } from 'antd'
import { BranchesOutlined, CheckCircleOutlined, ClockCircleOutlined, FileSearchOutlined, RobotOutlined } from '@ant-design/icons'
import type { CreditAssessment, CreditAssessmentEvent, CreditAssessmentStatus } from '../types'

const { Text } = Typography

type Props = {
  running: boolean
  status: CreditAssessmentStatus | null
  assessment: CreditAssessment | null
  onSelectSource?: (source: any) => void
}

const actionText: Record<string, string> = { tool: '读取证据', submit_claims: '提交事实核验', request_materials: '请求补充材料', finish: '完成审查', invalid_action: '修正操作' }
const eventColor: Record<string, string> = { agent_action: 'blue', tool_result: 'purple', claim_validated: 'green', request_materials: 'orange', error: 'red', completed: 'green', milestone: 'default' }
const eventText: Record<string, string> = { agent_action: 'Agent 操作', trace: 'Agent 记录', milestone: '流程节点', tool_result: '读取结果', claim_validated: '事实核验', request_materials: '补充材料', completed: 'Agent 审查完成', error: '运行失败' }
const statusText: Record<string, string> = { waiting: '等待开始', running: '运行中', done: '已完成', error: '运行失败', execution_failed: '运行失败' }

const progressText = (progress: any) => {
  if (!progress) return ''
  const missing = (progress.missing_metrics || []).join('、')
  return `主体 ${progress.identity_verified ? '✓' : '—'} · 口径 ${progress.financial_context_verified ? '✓' : '—'} · 指标 ${progress.verified_metrics?.length || 0}/7${missing ? ` · 缺 ${missing}` : ''}`
}

export default function AgentLivePanel({ running, status, assessment, onSelectSource }: Props) {
  const runtime = assessment?.report?.audit_runtime || {}
  const liveSources = status?.live_evidence?.length ? status.live_evidence : (runtime.evidence_sources || [])
  const sourceById = new Map(liveSources.map((source: any) => [source.chunk_id, source]))
  const events: CreditAssessmentEvent[] = status?.events?.length ? status.events : (runtime.trace || []).map((item: any) => ({
    type: 'trace', event_id: `trace-${item.step}`, created_at: assessment?.completed_at, step: item.step, action: item.action, tool: item.tool,
    reason_summary: item.reason_summary, result_summary: item.result_summary, progress: item.progress_after || item.progress,
    sources: (item.observation?.chunk_ids || []).map((chunkId: string) => sourceById.get(chunkId)).filter(Boolean),
  }))
  const steps = (status?.steps || assessment?.report?.steps || []) as string[]
  const claims = status?.live_claims?.length ? status.live_claims : (runtime.claims || [])
  const runtimeStatus = status?.status || runtime.status || (assessment?.status === 'done' ? 'done' : 'waiting')
  const displayEvents = events.slice(-30)

  return <Card
    size="small"
    className="credit-agent-live-panel"
    title={<Space><RobotOutlined /> Agent 实时审查记录 <Badge status={running ? 'processing' : runtimeStatus === 'execution_failed' || assessment?.status === 'error' ? 'error' : 'success'} text={running ? '运行中' : assessment?.status === 'done' ? '已完成' : statusText[runtimeStatus] || runtimeStatus} /></Space>}
    extra={<Space size={6}><Tag icon={<BranchesOutlined />}>{claims.length} 条已核验事实</Tag><Tag icon={<FileSearchOutlined />}>{liveSources.length} 个来源</Tag></Space>}
  >
    <div className="credit-agent-active">
      <ClockCircleOutlined />
      <div><Text strong>{status?.active?.message || (running ? 'Agent 正在处理下一步审查…' : '本次 Agent 审查尚未开始')}</Text><Text type="secondary">{status?.active?.step ? `第 ${status.active.step} 步` : '状态会自动更新'}{status?.active?.tool ? ` · ${status.active.tool}` : ''}</Text></div>
    </div>
    {running && <div className="credit-agent-live-note">Agent 每完成一步处理、读取来源或核验事实，都会实时显示在这里，无需等到最终评分生成。</div>}
    {displayEvents.length ? <div className="credit-agent-timeline">
      {displayEvents.map((event, index) => {
        const label = event.type === 'agent_action' ? actionText[event.action || ''] || event.action || '系统操作' : event.type === 'trace' ? actionText[event.action || ''] || event.action || '审查记录' : eventText[event.type] || event.type
        const sources = event.sources || []
        return <div className={`credit-agent-event ${event.type === 'claim_validated' ? 'is-success' : event.type === 'error' ? 'is-error' : ''}`} key={event.event_id || `${event.type}-${event.step}-${index}`}>
          <div className="credit-agent-event-dot"><span /></div>
          <div className="credit-agent-event-body">
            <Space wrap size={[5, 4]}><Tag color={eventColor[event.type] || 'default'}>{label}</Tag>{event.step && <Tag>第 {event.step} 轮</Tag>}{event.tool && <Tag color="purple">{event.tool}</Tag>}{event.created_at && <Text type="secondary">{dayjs(event.created_at * 1000).format('HH:mm:ss')}</Text>}</Space>
            <Text>{event.message || event.result_summary || event.reason_summary || 'Agent 已更新审查状态'}</Text>
            {event.reason_summary && event.message !== event.reason_summary && <Text type="secondary">判断依据：{event.reason_summary}</Text>}
            {progressText(event.progress) && <Text type="secondary">核验进度：{progressText(event.progress)}</Text>}
            {event.error && <Text type="danger">{event.error}</Text>}
            {sources.length > 0 && <Space wrap size={[4, 4]} className="credit-agent-source-links">{sources.slice(0, 12).map((source: any, sourceIndex: number) => <Button key={`${source.chunk_id || source.source_ref}-${sourceIndex}`} type="link" size="small" onClick={() => onSelectSource?.(source)}>{source.source_ref || source.chunk_id || '查看来源'}</Button>)}</Space>}
          </div>
        </div>
      })}
    </div> : steps.length ? <List size="small" dataSource={steps} renderItem={(step, index) => <List.Item><Space><Tag>{index + 1}</Tag><Text>{step}</Text></Space></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={running ? '正在生成第一条 Agent 审查记录…' : '暂无 Agent 审查记录'} />}
    {claims.length > 0 && <div className="credit-agent-claims"><CheckCircleOutlined /><Text type="secondary">最近已核验 {claims.length} 条事实；点击上方来源标签可在左侧材料中对照。</Text></div>}
  </Card>
}
