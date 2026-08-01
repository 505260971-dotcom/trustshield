import dayjs from 'dayjs'
import { Badge, Card, Empty, List, Space, Tag, Typography } from 'antd'
import { CheckCircleOutlined, ClockCircleOutlined, FileSearchOutlined, RobotOutlined } from '@ant-design/icons'
import type { Report, ReviewJobEvent, ReviewJobStatus } from '../types'

const { Text } = Typography

type Props = { running: boolean; status: ReviewJobStatus | null; report?: Report | null; onSelectSource?: (source: any) => void }

const eventColor: Record<string, string> = { agent_update: 'blue', completed: 'green', error: 'red', milestone: 'default' }

export default function ContractLivePanel({ running, status, report, onSelectSource }: Props) {
  const finalReport = report || status?.result
  const reportSources = [...(finalReport?.risks || []), ...(finalReport?.review_hints || [])]
  const liveSources = status?.live_evidence?.length ? status.live_evidence : reportSources
  const events: ReviewJobEvent[] = status?.events?.length ? status.events : (finalReport?.steps || []).map((step, index) => ({ type: 'agent_update', message: step, step_index: index + 1 }))
  const displayEvents = events.slice(-30)
  const currentStatus = status?.status || (finalReport ? 'done' : 'running')

  return <Card size="small" className="contract-live-panel" title={<Space><RobotOutlined /> Agent 实时审查记录 <Badge status={running ? 'processing' : currentStatus === 'error' ? 'error' : 'success'} text={running ? '运行中' : currentStatus === 'done' ? '已完成' : currentStatus} /></Space>} extra={<Tag icon={<FileSearchOutlined />}>{liveSources.length} 个证据引用</Tag>}>
    <div className="contract-live-active"><ClockCircleOutlined /><div><Text strong>{status?.active?.message || (running ? '正在等待下一条审查节点…' : '已载入合同审查结果')}</Text><Text type="secondary">{status?.active?.step_index ? `流程节点 ${status.active.step_index}` : '同步间隔约 1 秒'}{status?.active?.updated_at ? ` · ${dayjs(status.active.updated_at * 1000).format('HH:mm:ss')}` : ''}</Text></div></div>
    {running && <div className="contract-live-note">审查节点完成后会立即追加到这里；证据引用会同步出现在左侧原合同预览。</div>}
    {displayEvents.length ? <div className="contract-live-timeline">{displayEvents.map((event, index) => <div className={`contract-live-event ${event.type === 'error' ? 'is-error' : event.type === 'completed' ? 'is-success' : ''}`} key={event.event_id || `${event.type}-${event.step_index}-${index}`}><div className="contract-live-dot"><span /></div><div className="contract-live-body"><Space wrap size={[5, 4]}><Tag color={eventColor[event.type] || 'default'}>{event.type === 'agent_update' ? 'Agent 节点' : event.type === 'completed' ? '审查完成' : event.type === 'error' ? '运行异常' : '流程节点'}</Tag>{event.step_index && <Tag>#{event.step_index}</Tag>}{event.created_at && <Text type="secondary">{dayjs(event.created_at * 1000).format('HH:mm:ss')}</Text>}</Space><Text>{event.message || 'Agent 已更新审查状态'}</Text>{event.clause_count !== undefined && <Text type="secondary">已解析 {event.clause_count} 条款 · 已研判 {event.reviewed_count || 0} 条 · 当前风险 {event.risk_count || 0} 条</Text>}{event.error && <Text type="danger">{event.error}</Text>}{(event.sources || []).length > 0 && <Space wrap className="contract-live-source-links">{(event.sources || []).slice(0, 12).map((source: any, sourceIndex: number) => <a key={`${source.source_ref || source.clause_id}-${sourceIndex}`} onClick={() => onSelectSource?.(source)}>{source.rule_id || source.source_ref || '查看证据'}</a>)}</Space>}</div></div>)}</div> : status?.steps?.length ? <List size="small" dataSource={status.steps} renderItem={(step, index) => <List.Item><Space><Tag>{index + 1}</Tag><Text>{step}</Text></Space></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={running ? '正在建立第一条 Agent 进度…' : '暂无审查记录'} />}
    {liveSources.length > 0 && <div className="contract-live-claims"><CheckCircleOutlined /><Text type="secondary">已收集 {liveSources.length} 条可定位来源；点击引用可在左侧合同中对照。</Text></div>}
  </Card>
}
