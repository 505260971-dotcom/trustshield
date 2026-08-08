import type { WorkboxItem } from '../types'

export type WorkflowTone = 'default' | 'blue' | 'processing' | 'cyan' | 'gold' | 'orange' | 'red' | 'purple' | 'green'

export type WorkflowMeta = {
  label: string
  color: WorkflowTone
  action?: string
  description?: string
}

export const roleDisplayName: Record<string, string> = {
  business: '业务申请人',
  reviewer: '信用审核专员',
  director: '财务审批主管',
  admin: '系统管理员',
  final_approver: '集团财务总监 / 最终审批人',
  system: '系统',
}

export const stageMeta: Record<string, WorkflowMeta> = {
  draft: { label: '草稿', color: 'default', action: '继续填写申请', description: '申请尚未提交' },
  awaiting_credit: { label: '等待有效信用审核', color: 'orange', action: '选择有效信用审核版本', description: '合同暂不能进入正式审查' },
  ai_review: { label: '系统审查中', color: 'processing', action: '查看审查进度', description: '系统正在解析合同和校验规则' },
  legal_review: { label: '信用审核专员复核', color: 'blue', action: '处理风险条款', description: '等待信用审核专员确认风险处理结果' },
  awaiting_business: { label: '待业务补充材料', color: 'orange', action: '补充材料 / 上传修订版', description: '需要业务补充材料或修改合同' },
  approval: { label: '待主管审批', color: 'purple', action: '查看申请并决定', description: '等待财务审批主管决定' },
  final_approval: { label: '待最终审批', color: 'purple', action: '查看申请并决定', description: '等待集团财务总监决定' },
  ready_to_sign: { label: '可签约', color: 'green', action: '确认签署并归档', description: '合同已通过审查，等待签署' },
  archived: { label: '已签约归档', color: 'default', action: '查看归档记录', description: '流程已经完成' },
  cancelled: { label: '已取消', color: 'red', action: '查看取消记录', description: '流程已取消' },
  returned_to_reviewer: { label: '退回审核专员', color: 'orange', action: '补充审核意见', description: '需要审核专员重新处理' },
  returned_to_business: { label: '待业务补充材料', color: 'orange', action: '补充材料 / 上传修订版', description: '需要业务人员补齐材料' },
  pending_director: { label: '待主管复核', color: 'purple', action: '作出主管审批决定', description: '等待财务审批主管复核' },
  pending_final: { label: '待最终审批', color: 'purple', action: '作出最终审批决定', description: '等待集团财务总监最终审批' },
  approved: { label: '已生效', color: 'green', action: '查看生效边界', description: '可以作为合同审查前置条件' },
  rejected: { label: '已拒绝', color: 'red', action: '查看拒绝原因', description: '本版本未获批准' },
  superseded: { label: '历史版本', color: 'default', action: '查看历史版本', description: '已经被新版本替代' },
}

export const creditStatusMeta: Record<string, WorkflowMeta> = {
  draft: { label: '待评估', color: 'processing', action: '开始信用审核评估', description: '等待信用审核专员核验' },
  returned_to_business: { label: '待业务补充', color: 'orange', action: '补齐信用审核材料', description: '业务资料需要补充' },
  returned_to_reviewer: { label: '退回审核专员', color: 'orange', action: '修订评估依据', description: '需要重新确认信用审核条件' },
  pending_director: { label: '待主管复核', color: 'purple', action: '作出主管审批决定', description: '等待财务审批主管复核' },
  pending_final: { label: '待最终审批', color: 'purple', action: '作出最终审批决定', description: '等待集团财务总监最终审批' },
  approved: { label: '已生效', color: 'green', action: '查看生效边界', description: '可以作为合同审查前置条件' },
  rejected: { label: '已拒绝', color: 'red', action: '查看拒绝原因', description: '本版本未获批准' },
  superseded: { label: '历史版本', color: 'default', action: '查看历史版本', description: '已经被新版本替代' },
}

export const stageInfo = (stage?: string): WorkflowMeta => stageMeta[stage || ''] || {
  label: stage || '未知阶段',
  color: 'default',
  action: '查看案件详情',
  description: '查看当前流程状态和处理记录',
}

export const creditStatusInfo = (status?: string): WorkflowMeta => creditStatusMeta[status || ''] || {
  label: status || '未知状态',
  color: 'default',
  action: '查看信用审核状态',
  description: '查看当前信用审核版本和审批记录',
}

export function aiConclusionInfo(value?: string): WorkflowMeta {
  if (!value) return { label: '尚未审查', color: 'default', action: '等待 Agent 审查', description: '当前还没有 Agent 审查结论' }
  if (value.startsWith('阻断')) return { label: value, color: 'red', action: '处理阻断风险', description: '存在不能直接放行的风险' }
  if (value.startsWith('需')) return { label: value, color: 'orange', action: '查看待确认事项', description: '需要人工确认或例外审批' }
  if (/通过|可签约|已生效/.test(value)) return { label: value, color: 'green', action: '查看通过依据', description: '当前结论允许继续推进' }
  return { label: value, color: 'blue', action: '查看审查结果', description: '查看审查结果和依据' }
}

export function workItemAction(item: Pick<WorkboxItem, 'source_type' | 'current_stage'>): string {
  if (item.source_type === 'credit') return creditStatusInfo(item.current_stage).action || '进入信用审核处理'
  return stageInfo(item.current_stage).action || '进入合同处理'
}

export function customerContractAction(stage?: string): string {
  return stageInfo(stage).action || '查看案件详情'
}

export function gateStateInfo(input: {
  hasCredit: boolean
  hasDocument: boolean
  gateCount: number
  stage?: string
  loading?: boolean
}): WorkflowMeta & { state: 'blocked' | 'pending' | 'running' | 'passed' } {
  if (input.loading) return { state: 'running', label: '正在检查放行条件', color: 'processing', action: '等待条件检查完成', description: '正在整理当前版本的风险、补充材料和审批状态' }
  if (!input.hasCredit) return { state: 'blocked', label: '信用审核前置条件未完成', color: 'red', action: '先完成客户信用审核', description: '未绑定已生效的信用审核版本，合同不能进入正式审查' }
  if (!input.hasDocument && input.stage !== 'archived') return { state: 'pending', label: '等待上传合同', color: 'blue', action: '上传主合同', description: '绑定有效信用审核版本后，需要上传主合同才能启动审查' }
  if (input.stage === 'ai_review') return { state: 'running', label: '系统审查中', color: 'processing', action: '查看审查进度', description: '系统正在解析合同和校验已生效信用审核条件' }
  if (input.gateCount > 0) return { state: 'pending', label: `还有 ${input.gateCount} 项待处理`, color: 'orange', action: '处理风险与放行条件', description: '仍有风险、补充材料或例外审批需要处理' }
  return { state: 'passed', label: '当前版本已满足放行条件', color: 'green', action: '查看审查结果', description: '当前版本可以继续按流程推进' }
}
