"""Deterministic guardrails that compare a contract with its approved credit decision.

This module intentionally contains no approval logic.  A contract can only consume
an already-approved credit snapshot; changing a commercial boundary belongs to the
credit workflow in ``store.py``.
"""
from __future__ import annotations

import re
from typing import Any


_TERM_PATTERNS = (
    re.compile(r'(?:发货|交货|交付|出货|shipment|delivery)[^。；;]{0,80}?(?:后|起|within|after)?\s*(\d{1,4})\s*(?:个?工作)?(?:天|日|days?)', re.I),
    re.compile(r'(?:付款|支付|payment|pay(?:ment)?\s+(?:shall\s+be\s+)?due|net)[^。；;]{0,60}?(\d{1,4})\s*(?:个?工作)?(?:天|日|days?)', re.I),
    re.compile(r'(\d{1,4})\s*(?:个?工作)?(?:天|日|days?)[^。；;]{0,60}(?:付款|支付|payment|invoice|net)', re.I),
)
_PREPAY = re.compile(r'(?:预付|预付款|定金|发货前|交付前|before\s+(?:delivery|shipment))[^。；;]{0,60}?(\d{1,3})\s*[%％]', re.I)
_PREPAY_REVERSED = re.compile(r'(\d{1,3})\s*[%％][^。；;]{0,60}?(?:预付|预付款|定金|发货前|交付前|before\s+(?:delivery|shipment))', re.I)
_ACCEPTANCE = re.compile(r'(?:银行承兑|商业承兑|bank\s+acceptance|acceptance\s+bill)', re.I)
# Chinese text immediately following an English acronym is also a word character
# to Python's regex engine, so \bVMI\b would miss forms such as “VMI模式”.
_VMI_JIT = re.compile(r'(?:VMI|JIT|vendor\s*managed\s*inventory|just[ -]?in[ -]?time)|供应商管理库存|准时制', re.I)
_AMOUNT = re.compile(r'(\d[\d,]*\.?\d*)\s*(元|人民币|港币|美元|RMB|CNY|HKD|USD)', re.I)
_VMI_JIT_NEGATION = re.compile(r'(?:不(?:采用|使用|含有?|包含|涉及)|未(?:采用|使用|包含)|禁止(?:采用|使用|包含)?|不得(?:采用|使用|包含)?|无)[^。；;]{0,24}$', re.I)


def positive_vmi_jit_match(text: str):
    """Return a VMI/JIT mention only when the surrounding clause does not negate it.

    Contract revisions frequently contain wording such as "不采用 VMI、JIT".  A
    lexical hit is useful for candidate recall, but it must not become a credit
    blocker or deterministic contract risk when the delivery mode is explicitly
    prohibited in the same sentence.
    """
    value = text or ''
    for match in _VMI_JIT.finditer(value):
        prefix = value[max(0, match.start() - 32):match.start()]
        if not _VMI_JIT_NEGATION.search(prefix):
            return match
    return None


def normalize_conditions(value: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the commercial conditions stored with a decision."""
    raw = value or {}
    try:
        max_credit_amount = float(raw.get('max_credit_amount') or 0)
        max_payment_days = int(raw.get('max_payment_days') or 0)
        min_prepayment_ratio = float(raw.get('min_prepayment_ratio') or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError('授信金额、最长账期和最低预付款比例必须为数字') from exc
    if max_credit_amount < 0 or max_payment_days < 0 or not 0 <= min_prepayment_ratio <= 100:
        raise ValueError('信审条件范围无效')
    methods = raw.get('allowed_payment_methods') or ['bank_transfer']
    if not isinstance(methods, list) or not all(isinstance(x, str) and x.strip() for x in methods):
        raise ValueError('允许付款方式必须为非空文本数组')
    return {
        'max_credit_amount': max_credit_amount,
        'currency': str(raw.get('currency') or 'CNY').upper()[:8],
        'max_payment_days': max_payment_days,
        'min_prepayment_ratio': min_prepayment_ratio,
        'allowed_payment_methods': sorted({x.strip() for x in methods}),
        'allow_vmi_jit': bool(raw.get('allow_vmi_jit', False)),
        'valid_from': float(raw.get('valid_from') or 0),
        'valid_to': float(raw.get('valid_to') or 0),
    }


def _risk(rule_id: str, baseline: str, evidence: str, note: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {
        'clause_id': 'CREDIT', 'page': 0, 'source_ref': '信审前置校验', 'rule_id': rule_id,
        'rule_baseline': baseline, 'dim': 'credit_control', 'evidence': evidence[:180],
        'suggestion': '不得在合同端放宽。请先发起客户信审变更并取得新的已生效信审版本，再重新提交合同。',
        'severity': 'high', 'level': '信审阻断', 'numeric_note': note, 'facts': facts,
        'decision': 'blocked_by_credit', 'decision_source': 'credit_decision_snapshot',
        'credit_blocking': True,
    }


def _entity_key(value: Any) -> str:
    return re.sub(r'[\s\W_]+', '', str(value or '').lower(), flags=re.UNICODE)


def assess_customer_binding(contract_fields: dict[str, Any], customer_name: str) -> list[dict]:
    """Ensure the selected credit decision belongs to the contract counterparty."""
    fields = contract_fields or {}
    parties = fields.get('parties') or {}
    our_party = str(fields.get('our_party') or '')
    counterparty_keys = ['乙方'] if our_party == '甲方' else ['甲方'] if our_party == '乙方' else ['甲方', '乙方', '买方', '客户', 'buyer']
    candidates = [str(parties.get(key) or '').strip() for key in counterparty_keys if str(parties.get(key) or '').strip()]
    expected = _entity_key(customer_name)
    if not candidates:
        return [_risk('CREDIT_CUSTOMER_UNCONFIRMED', f'合同交易相对方必须与信审客户“{customer_name}”一致',
                      '未能从合同字段确认交易相对方', '无法确认合同客户，不能证明所绑定信审版本适用', {'credit_customer': customer_name})]
    if not any(expected and (expected in _entity_key(name) or _entity_key(name) in expected) for name in candidates):
        return [_risk('CREDIT_CUSTOMER_MISMATCH', f'合同交易相对方必须与信审客户“{customer_name}”一致', '；'.join(candidates),
                      f'合同相对方与所选信审客户不一致：信审客户={customer_name}', {'credit_customer': customer_name, 'contract_counterparties': candidates})]
    return []


def assess_credit_compliance(clauses: list[dict], conditions: dict[str, Any], exposure_snapshot: dict[str, Any] | None=None) -> list[dict]:
    """Return non-overridable findings when contract terms are worse than credit terms.

    ``exposure_snapshot`` is an encrypted-at-rest CRM/ERP point-in-time input
    supplied by the credit module.  It lets the contract guard enforce the
    documented total-credit rule instead of comparing only this one contract's
    face value with the approved cap.
    """
    text = '\n'.join(str(item.get('text') or '') for item in clauses or [])
    findings: list[dict] = []
    term_days = [int(match.group(1)) for pattern in _TERM_PATTERNS for match in pattern.finditer(text)]
    maximum = conditions.get('max_payment_days', 0)
    # 0 means cash/no post-delivery credit, not “unlimited”.
    if term_days and max(term_days) > maximum:
        actual = max(term_days)
        findings.append(_risk('CREDIT_TERM', f'该客户信审最长账期为 {maximum} 天', f'合同约定账期 {actual} 天',
                              f'合同账期 {actual} 天 > 已生效信审上限 {maximum} 天', {'term_days': actual, 'max_payment_days': maximum}))

    required_prepay = conditions.get('min_prepayment_ratio', 0)
    prepay = [int(m.group(1)) for m in _PREPAY.finditer(text)] + [int(m.group(1)) for m in _PREPAY_REVERSED.finditer(text)]
    if required_prepay and (not prepay or max(prepay) < required_prepay):
        actual = max(prepay, default=0)
        evidence = f'合同中识别的交付前收款比例 {actual:g}%' if prepay else '未识别到合同约定的交付前收款比例'
        findings.append(_risk('CREDIT_PREPAYMENT', f'该客户信审要求交付前最低收款 {required_prepay:g}%', evidence,
                              f'合同交付前收款 {actual:g}% < 已生效信审下限 {required_prepay:g}%', {'prepayment_ratio': actual, 'min_prepayment_ratio': required_prepay}))

    methods = set(conditions.get('allowed_payment_methods') or [])
    if _ACCEPTANCE.search(text) and 'acceptance_bill' not in methods:
        findings.append(_risk('CREDIT_PAYMENT_METHOD', '该客户信审未授权承兑汇票付款', _ACCEPTANCE.search(text).group(0),
                              '合同付款方式包含承兑汇票，但绑定信审版本未授权该方式', {'payment_method': 'acceptance_bill', 'allowed_payment_methods': sorted(methods)}))
    vmi_jit = positive_vmi_jit_match(text)
    if vmi_jit and not conditions.get('allow_vmi_jit', False):
        findings.append(_risk('CREDIT_DELIVERY_MODE', '该客户信审未授权 VMI/JIT 交付模式', vmi_jit.group(0),
                              '合同包含 VMI/JIT，但绑定信审版本未授权该交付模式', {'delivery_mode': 'vmi_jit'}))

    cap = conditions.get('max_credit_amount', 0)
    amounts = [(float(raw.replace(',', '')), currency.upper()) for raw, currency in _AMOUNT.findall(text)]
    matching = [amount for amount, currency in amounts if currency in {conditions.get('currency', 'CNY'), '人民币', '元', 'RMB', 'CNY'}]
    contract_amount = max(matching, default=0)
    snapshot = exposure_snapshot or {}
    snapshot_currency = str(snapshot.get('currency') or conditions.get('currency') or 'CNY').upper()
    same_currency = snapshot_currency == str(conditions.get('currency') or 'CNY').upper()
    existing_exposure = 0.0
    if same_currency:
        try:
            existing_exposure = max(0, float(snapshot.get('current_receivables') or 0)) + max(0, float(snapshot.get('booked_order_amount') or 0))
        except (TypeError, ValueError):
            existing_exposure = 0.0
    total_exposure = existing_exposure + contract_amount
    if cap and contract_amount and (contract_amount > cap or total_exposure > cap):
        evidence = f'合同金额 {contract_amount:g}'
        if existing_exposure:
            evidence += f'；CRM/ERP 既有敞口 {existing_exposure:g}；合计 {total_exposure:g}'
        findings.append(_risk('CREDIT_EXPOSURE', f'该客户信审总敞口上限为 {cap:g} {conditions.get("currency", "CNY")}', evidence,
                              f'合同后总敞口 {total_exposure:g} > 已生效信审上限 {cap:g}', {'contract_amount': contract_amount, 'existing_exposure': existing_exposure, 'total_exposure': total_exposure, 'max_credit_amount': cap, 'currency': conditions.get('currency', 'CNY')}))
    try:
        overdue_days = int(snapshot.get('overdue_days') or 0)
    except (TypeError, ValueError):
        overdue_days = 0
    if overdue_days > 30:
        findings.append(_risk('CREDIT_OVERDUE_LOCK', '同一客户逾期超过 30 天未付款时，系统应锁定继续入单、出货或走模',
                              f'CRM/ERP 快照显示最长逾期 {overdue_days} 天', f'客户逾期 {overdue_days} 天，超过制度锁定阈值 30 天', {'overdue_days': overdue_days, 'source': 'credit_exposure_snapshot'}))
    return findings
