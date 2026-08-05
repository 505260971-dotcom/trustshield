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
# TKM（模具制作）制度字段：走模/试模/模具验收后的尾期放账比例与信用期。
# 与通用账期正则不同，这两条必须锚定模具语境，避免把普通货款的
# “验收后 N 天付款”误判为模具尾款。
_TAIL_TERM = re.compile(r'(?:走模|试模|模具(?:交付|验收)|模试|mold\s+trial|mold\s+run|mold\s+acceptance|acceptance\s+of\s+mold)[^。；;]{0,80}?(?:后|起|within|after)?\s*(\d{1,4})\s*(?:个?工作)?(?:天|日|days?)', re.I)
_TAIL_RATIO = re.compile(r'(?:走模|试模|模具(?:交付|验收)|模试|mold\s+trial|mold\s+run|mold\s+acceptance)[^。；;]{0,60}?(?:后|起|after)?[^。；;]{0,50}?(\d{1,3})\s*[%％]', re.I)
_TAIL_RATIO_REVERSED = re.compile(r'(\d{1,3})\s*[%％][^。；;]{0,60}?(?:走模|试模|模具(?:交付|验收)|模试|mold\s+trial|mold\s+run|mold\s+acceptance)', re.I)
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
    """Validate and normalize the commercial conditions stored with a decision.

    TKP（注塑组件制造）使用通用字段：信用额、账期、最低收款比例、付款方式。
    TKM（模具制作）按东江制度为三段式申请，另有三个字段：首期款采购豁免、
    走模后尾款放账比例、走模后尾款信用期。非 TKM 案件三者归一化为默认值，
    保持跨类型条件比较的确定性。
    """
    raw = value or {}
    try:
        max_credit_amount = float(raw.get('max_credit_amount') or 0)
        max_payment_days = int(raw.get('max_payment_days') or 0)
        min_prepayment_ratio = float(raw.get('min_prepayment_ratio') or 0)
        tail_payment_ratio = float(raw.get('tail_payment_ratio') or 0)
        tail_payment_days = int(raw.get('tail_payment_days') or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError('授信金额、最长账期和最低预付款比例必须为数字') from exc
    if max_credit_amount < 0 or max_payment_days < 0 or not 0 <= min_prepayment_ratio <= 100:
        raise ValueError('信用审核条件范围无效')
    if not 0 <= tail_payment_ratio <= 100 or tail_payment_days < 0:
        raise ValueError('TKM 走模后尾款放账比例与信用期范围无效')
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
        # TKM 三段式申请字段（东江客户信用管理制度）：
        # 1) 首期款采购豁免：豁免后允许客户在未收回首期款时即开始项目物料采购；
        # 2) 走模后尾款放账比例上限；3) 走模后尾款信用期（天）。
        'first_payment_exempt': bool(raw.get('first_payment_exempt', False)),
        'tail_payment_ratio': tail_payment_ratio,
        'tail_payment_days': tail_payment_days,
    }


def _risk(rule_id: str, baseline: str, evidence: str, note: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {
        'clause_id': 'CREDIT', 'page': 0, 'source_ref': '信用审核前置检查', 'rule_id': rule_id,
        'rule_baseline': baseline, 'dim': 'credit_control', 'evidence': evidence[:180],
        'suggestion': '不能在合同端直接放宽。请先发起客户信用审核变更并取得新的已生效版本，再重新提交合同。',
        'severity': 'high', 'level': '信用审核条件不符', 'numeric_note': note, 'facts': facts,
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
        return [_risk('CREDIT_CUSTOMER_UNCONFIRMED', f'合同交易相对方必须与信用审核客户“{customer_name}”一致',
                      '未能从合同字段确认交易相对方', '无法确认合同客户，不能证明所绑定信用审核版本适用', {'credit_customer': customer_name})]
    if not any(expected and (expected in _entity_key(name) or _entity_key(name) in expected) for name in candidates):
        return [_risk('CREDIT_CUSTOMER_MISMATCH', f'合同交易相对方必须与信用审核客户“{customer_name}”一致', '；'.join(candidates),
                      f'合同相对方与所选信用审核客户不一致：信用审核客户={customer_name}', {'credit_customer': customer_name, 'contract_counterparties': candidates})]
    return []


def contract_amount_from_text(text: str, currency: str = '') -> tuple[float, str] | None:
    """从合同全文确定性提取“带币种的金额”中的最大一笔及其币种。

    与合规检查同一口径（_AMOUNT 正则 + 币种过滤），供字段抽取在模型
    结果不可还原时兜底，避免总金额字段缺失影响报告与信审门禁。
    """
    text = str(text or '')
    if not text:
        return None
    amounts = [(float(raw.replace(',', '')), currency_label.upper()) for raw, currency_label in _AMOUNT.findall(text)]
    if not amounts:
        return None
    preferred = str(currency or '').upper()
    candidates = [item for item in amounts if item[1] in {preferred, '人民币', '元', 'RMB', 'CNY'}]
    candidates = candidates or amounts
    return max(candidates, key=lambda item: item[0])


def assess_credit_compliance(clauses: list[dict], conditions: dict[str, Any], exposure_snapshot: dict[str, Any] | None=None, business_type: str='') -> list[dict]:
    """Return non-overridable findings when contract terms are worse than credit terms.

    ``exposure_snapshot`` is an encrypted-at-rest CRM/ERP point-in-time input
    supplied by the credit module.  It lets the contract guard enforce the
    documented total-credit rule instead of comparing only this one contract's
    face value with the approved cap.

    ``business_type`` selects the TKM tail-payment rules: TKM（模具制作）按制度
    走模后尾款放账比例与信用期单独约束，且“首期款采购豁免”时不再要求交付前
    最低收款比例。TKP/一般案件不启用这些字段，保持两类型字段分离。
    """
    text = '\n'.join(str(item.get('text') or '') for item in clauses or [])
    findings: list[dict] = []
    lane = 'TKM' if str(business_type or '').strip().upper() in {'TKM', '模具制作'} else ''
    term_days = [int(match.group(1)) for pattern in _TERM_PATTERNS for match in pattern.finditer(text)]
    maximum = conditions.get('max_payment_days', 0)
    # 0 means cash/no post-delivery credit, not “unlimited”.
    if term_days and max(term_days) > maximum:
        actual = max(term_days)
        findings.append(_risk('CREDIT_TERM', f'该客户信用审核最长账期为 {maximum} 天', f'合同约定账期 {actual} 天',
                              f'合同账期 {actual} 天 > 已生效信用审核上限 {maximum} 天', {'term_days': actual, 'max_payment_days': maximum}))

    required_prepay = conditions.get('min_prepayment_ratio', 0)
    prepay = [int(m.group(1)) for m in _PREPAY.finditer(text)] + [int(m.group(1)) for m in _PREPAY_REVERSED.finditer(text)]
    if lane == 'TKM' and conditions.get('first_payment_exempt'):
        # 制度允许“首期款采购豁免”：客户不收回首期款即可采购项目物料，
        # 因此交付前最低收款比例检查整体豁免，避免与豁免权自相矛盾。
        pass
    elif required_prepay and (not prepay or max(prepay) < required_prepay):
        actual = max(prepay, default=0)
        evidence = f'合同中识别的交付前收款比例 {actual:g}%' if prepay else '未识别到合同约定的交付前收款比例'
        findings.append(_risk('CREDIT_PREPAYMENT', f'该客户信用审核要求交付前最低收款 {required_prepay:g}%', evidence,
                              f'合同交付前收款 {actual:g}% < 已生效信用审核下限 {required_prepay:g}%', {'prepayment_ratio': actual, 'min_prepayment_ratio': required_prepay}))

    # TKM 制度三段式：走模后尾款放账比例与信用期单独受批核条件约束，
    # 不混入通用账期/收款比例字段（TKP 无此字段）。
    if lane == 'TKM':
        tail_ratio_limit = float(conditions.get('tail_payment_ratio') or 0)
        tail_ratios = [int(m.group(1)) for m in _TAIL_RATIO.finditer(text)] + [int(m.group(1)) for m in _TAIL_RATIO_REVERSED.finditer(text)]
        if tail_ratios and max(tail_ratios) > tail_ratio_limit:
            actual = max(tail_ratios)
            evidence = f'合同走模后尾款比例 {actual:g}%' if tail_ratio_limit > 0 else f'合同约定走模后放账 {actual:g}%'
            findings.append(_risk('CREDIT_TAIL_PAYMENT_RATIO', f'该客户 TKM 信用审核允许走模后放账比例不超过 {tail_ratio_limit:g}%', evidence,
                                  f'合同走模后放账 {actual:g}% > 已生效信用审核上限 {tail_ratio_limit:g}%', {'tail_payment_ratio': actual, 'tail_payment_ratio_limit': tail_ratio_limit}))
        tail_days_limit = int(conditions.get('tail_payment_days') or 0)
        tail_days = [int(m.group(1)) for m in _TAIL_TERM.finditer(text)]
        if tail_days and max(tail_days) > tail_days_limit:
            actual = max(tail_days)
            findings.append(_risk('CREDIT_TAIL_PAYMENT_TERM', f'该客户 TKM 信用审核允许走模后尾款信用期为 {tail_days_limit} 天', f'合同走模后尾款信用期 {actual} 天',
                                  f'合同走模后尾款信用期 {actual} 天 > 已生效信用审核上限 {tail_days_limit} 天', {'tail_payment_days': actual, 'tail_payment_days_limit': tail_days_limit}))

    methods = set(conditions.get('allowed_payment_methods') or [])
    if _ACCEPTANCE.search(text) and 'acceptance_bill' not in methods:
        findings.append(_risk('CREDIT_PAYMENT_METHOD', '该客户信用审核未授权承兑汇票付款', _ACCEPTANCE.search(text).group(0),
                              '合同付款方式包含承兑汇票，但绑定信用审核版本未授权该方式', {'payment_method': 'acceptance_bill', 'allowed_payment_methods': sorted(methods)}))
    vmi_jit = positive_vmi_jit_match(text)
    if vmi_jit and not conditions.get('allow_vmi_jit', False):
        findings.append(_risk('CREDIT_DELIVERY_MODE', '该客户信用审核未授权 VMI/JIT 交付模式', vmi_jit.group(0),
                              '合同包含 VMI/JIT，但绑定信用审核版本未授权该交付模式', {'delivery_mode': 'vmi_jit'}))

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
            evidence += f'；CRM/ERP 已有额度占用 {existing_exposure:g}；合计 {total_exposure:g}'
        findings.append(_risk('CREDIT_EXPOSURE', f'该客户信用审核总额度上限为 {cap:g} {conditions.get("currency", "CNY")}', evidence,
                              f'合同计入后总额度占用 {total_exposure:g} > 已生效信用审核上限 {cap:g}', {'contract_amount': contract_amount, 'existing_exposure': existing_exposure, 'total_exposure': total_exposure, 'max_credit_amount': cap, 'currency': conditions.get('currency', 'CNY')}))
    try:
        overdue_days = int(snapshot.get('overdue_days') or 0)
    except (TypeError, ValueError):
        overdue_days = 0
    if overdue_days > 30:
        findings.append(_risk('CREDIT_OVERDUE_LOCK', '同一客户逾期超过 30 天未付款时，系统应暂停继续入单、出货或模具交付',
                              f'CRM/ERP 快照显示最长逾期 {overdue_days} 天', f'客户逾期 {overdue_days} 天，超过制度锁定阈值 30 天', {'overdue_days': overdue_days, 'source': 'credit_exposure_snapshot'}))
    return findings
