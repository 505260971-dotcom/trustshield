# -*- coding: utf-8 -*-
"""泛微 OA / CRM 集成适配器（黑客松 Mock 契约）。

生产环境应替换为真实 HTTP 客户端；此处保持可演示的状态机与端口形状。
"""
import time
import uuid


class OAAdapter:
    """泛微OA 合同审批流程集成。

    命题: 为不同评审角色提供风险提示/修改建议;手动调整后批量更新原文;导出带/不带修订版。
    生产: 配置 OA_API_URL/OA_TOKEN, 实现 create_flow / submit / callback。
    """

    def __init__(self):
        self._flows = {}  # flow_id -> state

    def create_review_flow(self, contract_meta, report_summary, job_id='', findings=None):
        """在 OA 创建合同评审流程，挂载 Agent 风险清单。"""
        flow_id = 'OA-' + str(int(time.time()))[-7:] + uuid.uuid4().hex[:4].upper()
        summary = report_summary or {}
        risks = findings or []
        self._flows[flow_id] = {
            'flow_id': flow_id,
            'job_id': job_id,
            'contract': contract_meta or {},
            'summary': summary,
            'findings_preview': [
                {
                    'finding_id': item.get('finding_id'),
                    'rule_id': item.get('rule_id'),
                    'level': item.get('level') or item.get('severity'),
                    'suggestion': (item.get('suggestion') or '')[:120],
                }
                for item in risks[:20]
            ],
            'status': 'draft',
            'role_decisions': {},
            'accepted': [],
            'created_at': time.time(),
            'updated_at': time.time(),
            'mock': True,
            'integration': 'weaver_oa',
            'note': '演示流程；正式环境可替换为泛微流程创建接口',
        }
        return {'flow_id': flow_id, 'mock': True, 'status': 'draft', 'job_id': job_id}

    def submit_role_decision(self, flow_id, role, decision, note=''):
        """各评审层级（信用审核专员/财务审批主管/集团财务总监最终审批人）提交决策。"""
        f = self._flows.get(flow_id)
        if not f:
            return {'ok': False, 'msg': 'flow not found'}
        f['role_decisions'][role] = {
            'decision': decision,
            'note': note or '',
            'at': time.time(),
        }
        f['status'] = 'in_review'
        f['updated_at'] = time.time()
        # All configured roles decided → ready
        if all(r in f['role_decisions'] for r in APPROVAL_ROLES):
            f['status'] = 'role_complete'
        return {'ok': True, 'mock': True, 'status': f['status'], 'role_decisions': f['role_decisions']}

    def batch_update(self, flow_id, accepted_suggestions):
        """批量更新原文(采纳的建议写回合同文本)。"""
        f = self._flows.get(flow_id)
        if not f:
            return {'ok': False, 'msg': 'flow not found'}
        f['accepted'] = accepted_suggestions or []
        f['status'] = 'updated'
        f['updated_at'] = time.time()
        return {
            'ok': True,
            'mock': True,
            'status': f['status'],
            'accepted_count': len(f['accepted']),
            'export_hint': '请在 TrustShield 导出 revised（带修订）或 plain（无修订）稿',
        }

    def get_flow(self, flow_id):
        return self._flows.get(flow_id)


oa = OAAdapter()

# ---- 评审角色矩阵(可配置) ----
APPROVAL_ROLES = ['信用审核专员', '财务审批主管', '集团财务总监 / 最终审批人']
ROLE_FOCUS = {
    '信用审核专员': ['all'],  # 全量风险初审
    '财务审批主管': ['high', 'mid'],
    '集团财务总监 / 最终审批人': ['high'],
}


class CRMAdapter:
    """CRM 预留端口：接收客户主数据/信用申请占位，不执行授信测算。

    真正的东江信用评估模型由信用审核流程实现；本适配器只保证接口可以演示和对接。
    """

    def __init__(self):
        self._hooks = {}

    def create_credit_hook(self, payload: dict) -> dict:
        hook_id = 'CRM-' + uuid.uuid4().hex[:10].upper()
        now = time.time()
        record = {
            'hook_id': hook_id,
            'mock': True,
            'integration': 'crm_credit_hook',
            'status': 'received',
            'customer_name': str(payload.get('customer_name') or '').strip(),
            'crm_account_id': str(payload.get('crm_account_id') or ''),
            'request_note': str(payload.get('request_note') or 'CRM 推送的信用申请'),
            'conditions_hint': payload.get('conditions') or {},
            'credit_case_id': None,
            'created_at': now,
            'updated_at': now,
            'note': '已接收 CRM 请求；可创建信用审核草稿，完成 Agent 评估和人工审批后生效',
        }
        self._hooks[hook_id] = record
        return dict(record)

    def attach_credit_case(self, hook_id: str, credit_case_id: str) -> dict | None:
        record = self._hooks.get(hook_id)
        if not record:
            return None
        record['credit_case_id'] = credit_case_id
        record['status'] = 'draft_created'
        record['updated_at'] = time.time()
        return dict(record)

    def get_hook(self, hook_id: str) -> dict | None:
        record = self._hooks.get(hook_id)
        return dict(record) if record else None

    def list_hooks(self, limit: int = 50) -> list[dict]:
        items = sorted(self._hooks.values(), key=lambda x: x.get('created_at', 0), reverse=True)
        return [dict(x) for x in items[: max(1, min(limit, 200))]]


crm = CRMAdapter()
