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

const actionText: Record<string, string> = { tool: '读取证据', submit_claims: '提交 Claim', request_materials: '请求补件', finish: '结束审计', invalid_action: '纠正动作' }
const eventColor: Record<string, string> = { agent_action: 'blue', tool_result: 'purple', claim_validated: 'green', request_materials: 'orange', error: 'red', completed: 'green', milestone: 'default' }

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
    title={<Space><RobotOutlined /> Agent 实时审计记录 <Badge status={running ? 'processing' : runtimeStatus === 'execution_failed' || assessment?.status === 'error' ? 'error' : 'success'} text={running ? '运行中' : assessment?.status === 'done' ? '已完成' : runtimeStatus} /></Space>}
    extra={<Space size={6}><Tag icon={<BranchesOutlined />}>{claims.length} 条 Claim</Tag><Tag icon={<FileSearchOutlined />}>{liveSources.length} 个来源</Tag></Space>}
  >
    <div className="credit-agent-active">
      <ClockCircleOutlined />
      <div><Text strong>{status?.active?.message || (running ? 'Agent 正在等待下一轮工具或模型返回…' : '尚未开始本次 Agent 审计')}</Text><Text type="secondary">{status?.active?.step ? `第 ${status.active.step} 轮` : '轮询间隔约 1 秒'}{status?.active?.tool ? ` · ${status.active.tool}` : ''}</Text></div>
    </div>
    {running && <div className="credit-agent-live-note">本区域会随着 Agent 每次决策、工具返回和 Claim 核验实时追加，不需要等到最终评分生成。</div>}
    {displayEvents.length ? <div className="credit-agent-timeline">
      {displayEvents.map((event, index) => {
        const label = event.type === 'agent_action' ? actionText[event.action || ''] || event.action || 'Agent 动作' : event.type === 'trace' ? actionText[event.action || ''] || event.action || '审计记录' : event.type === 'milestone' ? '流程节点' : event.type === 'tool_result' ? '工具返回' : event.type === 'claim_validated' ? 'Claim 核验' : event.type === 'request_materials' ? '补件判断' : event.type === 'completed' ? '运行完成' : event.type === 'error' ? '运行异常' : event.type
        const sources = event.sources || []
        return <div className={`credit-agent-event ${event.type === 'claim_validated' ? 'is-success' : event.type === 'error' ? 'is-error' : ''}`} key={event.event_id || `${event.type}-${event.step}-${index}`}>
          <div className="credit-agent-event-dot"><span /></div>
          <div className="credit-agent-event-body">
            <Space wrap size={[5, 4]}><Tag color={eventColor[event.type] || 'default'}>{label}</Tag>{event.step && <Tag>第 {event.step} 轮</Tag>}{event.tool && <Tag color="purple">{event.tool}</Tag>}{event.created_at && <Text type="secondary">{dayjs(event.created_at * 1000).format('HH:mm:ss')}</Text>}</Space>
            <Text>{event.message || event.result_summary || event.reason_summary || 'Agent 已更新审计状态'}</Text>
            {event.reason_summary && event.message !== event.reason_summary && <Text type="secondary">判断依据：{event.reason_summary}</Text>}
            {progressText(event.progress) && <Text type="secondary">核验进度：{progressText(event.progress)}</Text>}
            {event.error && <Text type="danger">{event.error}</Text>}
            {sources.length > 0 && <Space wrap size={[4, 4]} className="credit-agent-source-links">{sources.slice(0, 12).map((source: any, sourceIndex: number) => <Button key={`${source.chunk_id || source.source_ref}-${sourceIndex}`} type="link" size="small" onClick={() => onSelectSource?.(source)}>{source.source_ref || source.chunk_id || '查看来源'}</Button>)}</Space>}
          </div>
        </div>
      })}
    </div> : steps.length ? <List size="small" dataSource={steps} renderItem={(step, index) => <List.Item><Space><Tag>{index + 1}</Tag><Text>{step}</Text></Space></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={running ? '正在建立第一条 Agent 事件…' : '暂无 Agent 运行记录'} />}
    {claims.length > 0 && <div className="credit-agent-claims"><CheckCircleOutlined /><Text type="secondary">最近已核验 {claims.length} 条 Claim；点击上方来源标签可在左侧材料中对照。</Text></div>}
  </Card>
}
