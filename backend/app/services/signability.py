"""Deterministic contract-to-policy signability planning.

This module does not approve a contract and does not alter credit conditions.
It turns the current report into an explainable repair path: which findings can
be fixed by editing the contract, and which ones require a new effective credit
decision first.
"""
from __future__ import annotations

from typing import Any


METHOD_LABELS = {
    'bank_transfer': '银行转账',
    'acceptance_bill': '银行承兑汇票',
    'commercial_acceptance': '商业承兑汇票',
}


def _number(value: Any) -> float | None:
    if value is None or value == '':
        return None
    try:
        return float(str(value).replace(',', '').replace('元', '').replace('人民币', '').strip())
    except (TypeError, ValueError):
        return None


def _money(value: Any, currency: str = 'CNY') -> str:
    number = _number(value)
    if number is None:
        return '未识别'
    return f'{number:,.2f}'.rstrip('0').rstrip('.') + f' {currency}'


def _method(value: Any) -> str:
    return METHOD_LABELS.get(str(value or ''), str(value or '未识别'))


def _risk_key(risk: dict[str, Any]) -> str:
    return str(risk.get('finding_id') or f"{risk.get('clause_id') or 'current'}-{risk.get('rule_id') or 'risk'}")


def _item(
    *,
    item_id: str,
    category: str,
    rule_id: str,
    title: str,
    current: str,
    target: str,
    action: str,
    can_resolve_in_contract: bool,
    requires_credit_reapproval: bool = False,
    status: str = 'blocked',
    clause_id: str = '',
    source_ref: str = '',
) -> dict[str, Any]:
    return {
        'id': item_id,
        'category': category,
        'rule_id': rule_id,
        'title': title,
        'current': current,
        'target': target,
        'action': action,
        'can_resolve_in_contract': can_resolve_in_contract,
        'requires_credit_reapproval': requires_credit_reapproval,
        'status': status,
        'clause_id': clause_id,
        'source_ref': source_ref,
    }


def calculate_signability(report: dict[str, Any], findings: list[dict[str, Any]] | None = None, job_id: str = '') -> dict[str, Any]:
    """Build a minimum repair path from a stored report.

    The result is intentionally a recommendation/diagnostic object.  The
    existing case transition and export gates remain the only authority for
    whether a contract can actually progress or be exported.
    """
    report = report or {}
    fields = report.get('contract_fields') or {}
    decision = report.get('credit_decision') or {}
    conditions = decision.get('conditions') or {}
    exposure = decision.get('exposure_snapshot_at_review') or {}
    risks = report.get('risks') or []
    finding_by_id = {str(item.get('finding_id')): item for item in findings or [] if item.get('finding_id')}
    currency = str(conditions.get('currency') or fields.get('currency') or exposure.get('currency') or 'CNY')
    items: list[dict[str, Any]] = []

    if not decision:
        items.append(_item(
            item_id='credit-binding', category='credit', rule_id='CREDIT_BINDING',
            title='已生效信用审核条件', current='未绑定', target='选择客户已生效信用审核版本',
            action='先完成客户信用审核并绑定已生效版本，再继续合同复审。',
            can_resolve_in_contract=False, requires_credit_reapproval=True,
        ))
    else:
        amount_risk = next((risk for risk in risks if risk.get('rule_id') == 'CREDIT_EXPOSURE'), {})
        term_risk = next((risk for risk in risks if risk.get('rule_id') == 'CREDIT_TERM'), {})
        prepay_risk = next((risk for risk in risks if risk.get('rule_id') == 'CREDIT_PREPAYMENT'), {})
        tail_ratio_risk = next((risk for risk in risks if risk.get('rule_id') == 'CREDIT_TAIL_PAYMENT_RATIO'), {})
        tail_term_risk = next((risk for risk in risks if risk.get('rule_id') == 'CREDIT_TAIL_PAYMENT_TERM'), {})
        payment_risk = next((risk for risk in risks if risk.get('rule_id') == 'CREDIT_PAYMENT_METHOD'), {})
        delivery_risk = next((risk for risk in risks if risk.get('rule_id') == 'CREDIT_DELIVERY_MODE'), {})

        contract_amount = _number(fields.get('total_amount'))
        amount_facts = amount_risk.get('facts') or {}
        contract_amount = contract_amount if contract_amount is not None else _number(amount_facts.get('contract_amount'))
        existing_exposure = _number(exposure.get('current_receivables')) or 0
        existing_exposure += _number(exposure.get('booked_order_amount')) or 0
        existing_exposure = _number(amount_facts.get('existing_exposure')) if amount_risk else existing_exposure
        existing_exposure = existing_exposure or 0
        credit_limit = _number(conditions.get('max_credit_amount'))
        available_for_contract = credit_limit - existing_exposure if credit_limit is not None else None
        total_exposure = (existing_exposure + contract_amount) if contract_amount is not None else None

        if amount_risk or (credit_limit is not None and total_exposure is not None and total_exposure > credit_limit):
            if available_for_contract is not None and available_for_contract >= 0:
                target = f'合同金额 ≤ {_money(available_for_contract, currency)}'
                action = f'将合同金额调整至不高于 {_money(available_for_contract, currency)}，使合同计入后总额度占用不超过信用审核上限。'
                requires_reapproval = False
            else:
                target = '先提高客户信用额度或降低已有额度占用'
                action = '当前已有额度占用已经达到或超过信用额度上限，单独修改合同金额无法解决，必须先更新客户信用审核条件或减少已有额度占用。'
                requires_reapproval = True
            items.append(_item(
                item_id='credit-exposure', category='credit', rule_id='CREDIT_EXPOSURE', title='客户额度占用合计',
                current=f'合同 {_money(contract_amount, currency)} · 合计 {_money(total_exposure, currency)}',
                target=target, action=action, can_resolve_in_contract=not requires_reapproval,
                requires_credit_reapproval=requires_reapproval, clause_id=amount_risk.get('clause_id', ''),
                source_ref=amount_risk.get('source_ref', ''),
            ))

        term_facts = term_risk.get('facts') or {}
        term_days = _number(term_facts.get('term_days'))
        max_days = _number(conditions.get('max_payment_days'))
        if term_risk:
            items.append(_item(
                item_id='credit-term', category='credit', rule_id='CREDIT_TERM', title='最长账期',
                current=f'{term_days:g} 天' if term_days is not None else '未识别账期',
                target=f'≤ {max_days:g} 天' if max_days is not None else '补充已生效信用审核账期',
                action=f'将合同最长账期调整为不超过 {max_days:g} 天。' if max_days is not None else '先确认已生效信用审核条件中的最长账期。',
                can_resolve_in_contract=max_days is not None, requires_credit_reapproval=max_days is None,
                clause_id=term_risk.get('clause_id', ''), source_ref=term_risk.get('source_ref', ''),
            ))

        prepay_facts = prepay_risk.get('facts') or {}
        prepay = _number(prepay_facts.get('prepayment_ratio'))
        min_prepay = _number(conditions.get('min_prepayment_ratio'))
        if prepay_risk:
            items.append(_item(
                item_id='credit-prepayment', category='credit', rule_id='CREDIT_PREPAYMENT', title='交付前收款',
                current=f'{prepay:g}%' if prepay is not None else '未识别比例',
                target=f'≥ {min_prepay:g}%' if min_prepay is not None else '补充已生效信用审核收款比例',
                action=f'将交付前收款提高至至少 {min_prepay:g}%。' if min_prepay is not None else '先确认已生效信用审核条件中的最低收款比例。',
                can_resolve_in_contract=min_prepay is not None, requires_credit_reapproval=min_prepay is None,
                clause_id=prepay_risk.get('clause_id', ''), source_ref=prepay_risk.get('source_ref', ''),
            ))

        # TKM 制度三段式：走模后尾款放账比例与信用期是独立约束，不与通用
        # 账期/收款比例混用；未配置上限时只能通过更新信用审核条件解决。
        tail_ratio_facts = tail_ratio_risk.get('facts') or {}
        tail_ratio = _number(tail_ratio_facts.get('tail_payment_ratio'))
        tail_ratio_limit = _number(conditions.get('tail_payment_ratio'))
        if tail_ratio_risk:
            items.append(_item(
                item_id='credit-tail-ratio', category='credit', rule_id='CREDIT_TAIL_PAYMENT_RATIO', title='走模后尾款放账比例',
                current=f'{tail_ratio:g}%' if tail_ratio is not None else '合同约定走模后放账',
                target=f'≤ {tail_ratio_limit:g}%' if tail_ratio_limit is not None else '补充已生效 TKM 尾款放账比例',
                action=f'将走模后尾款放账比例调整为不超过 {tail_ratio_limit:g}%。' if tail_ratio_limit is not None else '先更新 TKM 信用审核条件中的走模后尾款放账比例。',
                can_resolve_in_contract=tail_ratio_limit is not None, requires_credit_reapproval=tail_ratio_limit is None,
                clause_id=tail_ratio_risk.get('clause_id', ''), source_ref=tail_ratio_risk.get('source_ref', ''),
            ))
        tail_term_facts = tail_term_risk.get('facts') or {}
        tail_days = _number(tail_term_facts.get('tail_payment_days'))
        tail_days_limit = _number(conditions.get('tail_payment_days'))
        if tail_term_risk:
            items.append(_item(
                item_id='credit-tail-term', category='credit', rule_id='CREDIT_TAIL_PAYMENT_TERM', title='走模后尾款信用期',
                current=f'{tail_days:g} 天' if tail_days is not None else '合同约定走模后尾款账期',
                target=f'≤ {tail_days_limit:g} 天' if tail_days_limit is not None else '补充已生效 TKM 尾款信用期',
                action=f'将走模后尾款信用期调整为不超过 {tail_days_limit:g} 天。' if tail_days_limit is not None else '先更新 TKM 信用审核条件中的走模后尾款信用期。',
                can_resolve_in_contract=tail_days_limit is not None, requires_credit_reapproval=tail_days_limit is None,
                clause_id=tail_term_risk.get('clause_id', ''), source_ref=tail_term_risk.get('source_ref', ''),
            ))

        if payment_risk:
            allowed = conditions.get('allowed_payment_methods') or []
            allowed_label = '、'.join(_method(item) for item in allowed) or '信用审核未提供允许方式'
            current = _method((payment_risk.get('facts') or {}).get('payment_method') or 'acceptance_bill')
            items.append(_item(
                item_id='credit-payment-method', category='credit', rule_id='CREDIT_PAYMENT_METHOD', title='付款方式',
                current=current, target=f'仅使用：{allowed_label}',
                action=f'将付款方式调整为已生效信用审核允许的方式：{allowed_label}。',
                can_resolve_in_contract=bool(allowed), requires_credit_reapproval=not bool(allowed),
                clause_id=payment_risk.get('clause_id', ''), source_ref=payment_risk.get('source_ref', ''),
            ))

        if delivery_risk:
            allow_vmi = bool(conditions.get('allow_vmi_jit'))
            items.append(_item(
                item_id='credit-delivery-mode', category='credit', rule_id='CREDIT_DELIVERY_MODE', title='交付模式',
                current='合同包含 VMI/JIT', target='删除 VMI/JIT 或取得新的信用审核授权',
                action='从合同中删除 VMI/JIT、安全库存或未确认的持续供货义务。' if not allow_vmi else '核对合同交付模式与信用审核授权是否一致。',
                can_resolve_in_contract=not allow_vmi, requires_credit_reapproval=allow_vmi,
                clause_id=delivery_risk.get('clause_id', ''), source_ref=delivery_risk.get('source_ref', ''),
            ))

        special_credit = {
            'CREDIT_CUSTOMER_MISMATCH': ('客户主体', '合同相对方与信用审核客户不一致', '重新绑定正确客户的信用审核版本或修正主体信息。'),
            'CREDIT_CUSTOMER_UNCONFIRMED': ('客户主体', '合同相对方未确认', '补充并确认交易相对方，不能直接按当前信用审核条件放行。'),
            'CREDIT_OVERDUE_LOCK': ('逾期锁定', '客户存在超过制度阈值的逾期', '先处理逾期或取得新的信用审批，不得仅修改合同规避锁定。'),
        }
        for risk in risks:
            rule_id = str(risk.get('rule_id') or '')
            if rule_id in special_credit:
                title, current, action = special_credit[rule_id]
                items.append(_item(
                    item_id=f'credit-{rule_id.lower()}', category='credit', rule_id=rule_id, title=title,
                    current=current, target='完成客户级信用审核或主体核验', action=action,
                    can_resolve_in_contract=False, requires_credit_reapproval=True,
                    clause_id=risk.get('clause_id', ''), source_ref=risk.get('source_ref', ''),
                ))

    # Non-credit findings remain contract-level work.  Their actual approval
    # state comes from the normalized finding table, not the encrypted report.
    seen: set[str] = set()
    for risk in risks:
        rule_id = str(risk.get('rule_id') or '')
        if rule_id.startswith('CREDIT_'):
            continue
        key = _risk_key(risk)
        if key in seen:
            continue
        seen.add(key)
        finding = finding_by_id.get(str(risk.get('finding_id'))) or {}
        action_status = str(risk.get('action_status') or finding.get('action_status') or 'pending')
        closed = action_status in {'adopted', 'edited', 'ignored'}
        items.append(_item(
            item_id=f'contract-{key}', category='contract', rule_id=rule_id, title=str(risk.get('rule_baseline') or rule_id or '合同底线风险'),
            current='已识别合同底线风险', target='采纳建议、编辑建议或完成对应例外审批',
            action=str(risk.get('suggestion') or '请基于原文证据完成风险处置。'),
            can_resolve_in_contract=True, status='passed' if closed else 'pending',
            clause_id=str(risk.get('clause_id') or ''), source_ref=str(risk.get('source_ref') or ''),
        ))

    for hint in report.get('review_hints') or []:
        items.append(_item(
            item_id=f"review-hint-{_risk_key(hint)}", category='workflow', rule_id=str(hint.get('rule_id') or 'REVIEW_HINT'),
            title='待人工确认', current='依据或事实尚未完全确认', target='补充材料或完成审核员确认',
            action=str(hint.get('suggestion') or '请补充材料并完成人工核验。'),
            can_resolve_in_contract=False, status='pending', clause_id=str(hint.get('clause_id') or ''),
            source_ref=str(hint.get('source_ref') or ''),
        ))

    blockers = [item for item in items if item['status'] == 'blocked']
    pending = [item for item in items if item['status'] == 'pending']
    repairable = [item for item in blockers if item['can_resolve_in_contract'] and not item['requires_credit_reapproval']]
    reapproval = [item for item in blockers if item['requires_credit_reapproval']]
    if reapproval:
        status = 'credit_reapproval'
        next_action = '先处理客户级信用审核、主体或逾期锁定问题，再重新提交合同复审。'
    elif blockers or pending:
        status = 'contract_revision'
        next_action = '按最小修订路径调整合同，并在同一案件上传新版本复审。'
    else:
        status = 'ready'
        next_action = '当前未发现阻断项；完成案件流程中的放行条件后可继续签约交付。'

    return {
        'job_id': job_id,
        'status': status,
        'signable': not blockers and not pending,
        'next_action': next_action,
        'credit': {
            'case_id': decision.get('case_id'), 'customer_name': decision.get('customer_name'),
            'version': decision.get('version'), 'currency': currency,
            'max_credit_amount': conditions.get('max_credit_amount'),
            'existing_exposure': existing_exposure if decision else None,
            'contract_amount': contract_amount if decision else None,
            'projected_exposure': total_exposure if decision else None,
            'available_for_contract': available_for_contract if decision else None,
        },
        'counts': {
            'total': len(items), 'blocked': len(blockers), 'repairable': len(repairable),
            'requires_credit_reapproval': len(reapproval), 'pending': len(pending),
        },
        'items': items,
    }
