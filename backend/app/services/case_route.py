"""合同差异化审批路径评估（tiered contract approval routing）。

合同不再由人工在两个按钮之间选择审批路径：系统根据已生效信用审核
条件、ERP 额度占用快照和当前版本的处置状态自动判定档位，并给出可
审计的理由。档位只影响审批链长短，不改变任何放行 gate 的权威性——
store.transition_case 仍是唯一决定合同能否推进的执行者。

档位：
- fast（快速路径）：合同金额 + 已有敞口 ≤ 额度 × 快速路径比例，且无
  越界、无待处理风险/例外审批/待补材料。审批链：业务 → 审核专员确认
  → 可签约（跳过主管和集团财务总监的案件级审批）。
- standard（标准路径）：金额接近额度上限，或存在条款例外审批/待处理
  风险/待补材料，或关键字段缺失（fail-safe）。审批链：业务 → 审核
  专员 → 主管 → 总监终审 → 可签约。
- blocked（阻断）：合同金额/账期/收款比例等超过已生效信用审核条件，
  或需重新信审/逾期锁定。任何审批档位都不适用，必须先修订合同或
  更新信用审核。
"""
from __future__ import annotations

from typing import Any

# 快速路径的额度占用上限：合同 + 已有敞口达到该比例后即使未越界，
# 也要求集团财务总监终审，避免额度逼近红线时被主管直接放行。
FAST_TRACK_UTILIZATION_RATIO = 0.8

# 需要先解决客户级信用审核/主体/逾期问题，单靠改合同无法放行。
REAPPROVAL_RULE_IDS = {'CREDIT_CUSTOMER_MISMATCH', 'CREDIT_CUSTOMER_UNCONFIRMED', 'CREDIT_OVERDUE_LOCK'}

# 审核专员处置后视为已闭环的动作状态（与 signability 保持一致）。
FINDING_CLOSED = {'adopted', 'edited', 'ignored'}


def _number(value: Any) -> float | None:
    if value is None or value == '':
        return None
    try:
        return float(str(value).replace(',', '').replace('元', '').replace('人民币', '').strip())
    except (TypeError, ValueError):
        return None


def _money(value: float | None) -> str:
    if value is None:
        return '未识别'
    return f'{value:,.2f}'.rstrip('0').rstrip('.')


def _result(tier: str, requires_final: bool, reasons: list[str], based_on: dict[str, Any]) -> dict[str, Any]:
    return {'tier': tier, 'requires_final': requires_final, 'reasons': reasons, 'based_on': based_on}


def evaluate_case_route(report: dict[str, Any], findings: list[dict[str, Any]] | None = None,
                        approvals: list[dict[str, Any]] | None = None, open_materials: int = 0) -> dict[str, Any]:
    """Evaluate the approval tier for a reviewed contract document.

    ``report`` is the decrypted review report (contains ``contract_fields``,
    ``credit_decision`` and ``risks``).  ``findings``/``approvals`` come from
    the normalized tables so the tier reflects disposition progress, not just
    the moment the review finished.
    """
    report = report or {}
    decision = report.get('credit_decision') or {}
    conditions = decision.get('conditions') or {}
    exposure = decision.get('exposure_snapshot_at_review') or {}
    risks = report.get('risks') or []
    fields = report.get('contract_fields') or {}
    findings = findings or []
    approvals = approvals or []

    # 1. 信用审核阻断（CREDIT_*）：先解决越界，不谈审批路径。
    credit_risks = [risk for risk in risks if str(risk.get('rule_id') or '').startswith('CREDIT_')]
    if credit_risks:
        reasons: list[str] = []
        for risk in credit_risks:
            rid = str(risk.get('rule_id') or '')
            baseline = str(risk.get('rule_baseline') or risk.get('rule_id') or '信用审核条件')
            if rid in REAPPROVAL_RULE_IDS:
                reasons.append(f'{baseline}：需先更新客户信用审核或完成主体核验')
            else:
                reasons.append(f'{baseline}：需修订合同并重新审查')
        return _result('blocked', False, reasons, {'credit_blocks': len(credit_risks)})

    # 2. 金额与额度占用：差异化审批路径的核心维度。ERP 快照（已出货未
    #    收款 + 已入单金额）是“已有敞口”，与合同金额合计后对照额度。
    contract_amount = _number(fields.get('total_amount'))
    existing_exposure = (_number(exposure.get('current_receivables')) or 0) + (_number(exposure.get('booked_order_amount')) or 0)
    credit_limit = _number(conditions.get('max_credit_amount'))
    projected_exposure = existing_exposure + contract_amount if contract_amount is not None else None
    utilization = projected_exposure / credit_limit if (projected_exposure is not None and credit_limit) else None
    currency = str(conditions.get('currency') or fields.get('currency') or 'CNY')

    based_on: dict[str, Any] = {
        'contract_amount': contract_amount, 'existing_exposure': existing_exposure,
        'credit_limit': credit_limit, 'projected_exposure': projected_exposure,
        'utilization_pct': round(utilization * 100, 1) if utilization is not None else None,
        'currency': currency,
    }
    if contract_amount is None:
        return _result('standard', True, ['未识别合同金额，保守要求集团财务总监终审'], based_on)
    if credit_limit is None:
        return _result('standard', True, ['已生效信用审核缺少额度上限，需集团财务总监终审'], based_on)
    if utilization is not None and utilization > 1.0:
        return _result('blocked', False, [f'合同金额 {_money(contract_amount)} {currency} + 已有敞口 {_money(existing_exposure)} {currency} 合计超过已生效信用审核额度 {_money(credit_limit)} {currency}，需修订合同或更新信用审核'], based_on)
    if utilization is not None and utilization > FAST_TRACK_UTILIZATION_RATIO:
        return _result('standard', True,
                       [f'额度占用 {utilization:.0%}（合同 {_money(contract_amount)} + 已有敞口 {_money(existing_exposure)} 已超过额度 {_money(credit_limit)} {currency} 的 {FAST_TRACK_UTILIZATION_RATIO:.0%}），需集团财务总监终审'],
                       based_on)

    # 3. 例外审批 / 待处理风险 / 待补材料：任何未闭环事项都提升到总监终审。
    pending_approvals = [item for item in approvals if str(item.get('status') or '') == 'pending']
    if pending_approvals:
        roles = '、'.join(dict.fromkeys(str(item.get('required_role') or '审批人') for item in pending_approvals))
        return _result('standard', True, [f'含 {len(pending_approvals)} 项条款例外审批（{roles}），需集团财务总监终审'], based_on)
    pending_findings = [item for item in findings
                        if str(item.get('action_status') or 'pending') not in FINDING_CLOSED
                        and not str(item.get('rule_id') or '').startswith('CREDIT_')]
    if pending_findings:
        return _result('standard', True, [f'仍有 {len(pending_findings)} 项待处理风险，需集团财务总监终审'], based_on)
    if open_materials:
        return _result('standard', True, [f'仍有 {open_materials} 项待补充材料，需集团财务总监终审'], based_on)

    # 4. 快速路径：未越界、无待办、金额占用在安全比例内。
    return _result('fast', False,
                   [f'合同金额 {_money(contract_amount)} + 已有敞口 {_money(existing_exposure)} 未超过已生效信审额度 {_money(credit_limit)} {currency} 的 {FAST_TRACK_UTILIZATION_RATIO:.0%}，且风险、材料和例外均已闭环，可走快速路径直接签约'],
                   based_on)
