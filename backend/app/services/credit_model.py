"""Explainable, versioned quantitative model for customer credit review.

The module intentionally contains deterministic arithmetic and policy gates only.
LLMs may extract evidence from reports or explain the result, but may not alter a
score, limit or hard-stop condition.  That distinction keeps every published
credit recommendation reproducible from its saved input facts.
"""
from __future__ import annotations

from typing import Any


DEFAULT_MODEL_VERSION = 'credit-score-v1'
DEFAULT_MODEL_CONFIG = {
    'weights': {
        'liquidity': 25,
        'leverage': 20,
        'cashflow': 15,
        'profitability': 10,
        'external_credit': 15,
        'trade_behavior': 15,
    },
    'grades': [
        {'grade': 'A', 'minimum_score': 85, 'limit_multiplier': 1.0, 'revenue_cap_ratio': 0.12},
        {'grade': 'B', 'minimum_score': 70, 'limit_multiplier': 0.70, 'revenue_cap_ratio': 0.08},
        {'grade': 'C', 'minimum_score': 55, 'limit_multiplier': 0.40, 'revenue_cap_ratio': 0.04},
        {'grade': 'D', 'minimum_score': 0, 'limit_multiplier': 0.0, 'revenue_cap_ratio': 0.0},
    ],
    # Production ReAct only calls this engine with all core Claims verified.
    # Keep the policy itself equally strict so a future caller cannot silently
    # turn partial extraction into an automatic recommendation.
    'minimum_fact_coverage': 1.0,
    'overdue_lock_days': 30,
}


def _number(value: Any) -> float | None:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(numerator: Any, denominator: Any) -> float | None:
    n, d = _number(numerator), _number(denominator)
    return n / d if n is not None and d not in (None, 0) else None


def _score_band(value: float | None, bands: list[tuple[float, float]], default: float=0) -> float:
    if value is None:
        return default
    for floor, score in bands:
        if value >= floor:
            return score
    return 0


def normalized_business_type(value: Any) -> str:
    raw = str(value or '一般').strip().upper()
    if raw in {'TKM', '模具制作'}:
        return 'TKM'
    if raw in {'TKP', '注塑组件制造', '模塑一体'}:
        return 'TKP'
    return '一般'


def calculate_ratios(facts: dict[str, Any]) -> dict[str, float | None]:
    """Calculate ratios once from source facts; output is safe to show in UI."""
    current_assets = facts.get('current_assets')
    current_liabilities = facts.get('current_liabilities')
    return {
        'current_ratio': _ratio(current_assets, current_liabilities),
        'quick_ratio': _ratio(facts.get('quick_assets', current_assets), current_liabilities),
        'debt_to_assets': _ratio(facts.get('total_liabilities'), facts.get('total_assets')),
        'net_margin': _ratio(facts.get('net_profit'), facts.get('revenue')),
        'operating_cashflow_margin': _ratio(facts.get('operating_cashflow'), facts.get('revenue')),
    }


def _trend(current: Any, prior: Any) -> float | None:
    return _ratio((_number(current) or 0) - (_number(prior) or 0), prior)


def score_facts(facts: dict[str, Any], exposure: dict[str, Any] | None, config: dict[str, Any] | None=None) -> dict[str, Any]:
    """Return a transparent scorecard and explicitly report missing evidence."""
    config = config or DEFAULT_MODEL_CONFIG
    weights = config.get('weights') or DEFAULT_MODEL_CONFIG['weights']
    ratios = calculate_ratios(facts)
    revenue_trend = _trend(facts.get('revenue'), facts.get('prior_revenue'))
    profit_trend = _trend(facts.get('net_profit'), facts.get('prior_net_profit'))
    coverage_fields = ('revenue', 'current_assets', 'current_liabilities', 'total_assets', 'total_liabilities', 'net_profit', 'operating_cashflow')
    present = [field for field in coverage_fields if _number(facts.get(field)) is not None]
    coverage = round(len(present) / len(coverage_fields), 3)

    liquidity = _score_band(ratios['current_ratio'], [(1.5, weights['liquidity']), (1.2, weights['liquidity'] * .72), (1.0, weights['liquidity'] * .42)])
    leverage = _score_band((1 - ratios['debt_to_assets']) if ratios['debt_to_assets'] is not None else None,
                            [(0.55, weights['leverage']), (0.40, weights['leverage'] * .65), (0.25, weights['leverage'] * .30)])
    cashflow = _score_band(ratios['operating_cashflow_margin'], [(0.08, weights['cashflow']), (0, weights['cashflow'] * .55)])
    profitability = _score_band(ratios['net_margin'], [(0.05, weights['profitability']), (0, weights['profitability'] * .50)])

    rating = str(facts.get('external_rating') or '').upper().replace(' ', '')
    rating_score = weights['external_credit'] if rating.startswith(('AAA', 'AA')) else weights['external_credit'] * .72 if rating.startswith('A') else weights['external_credit'] * .42 if rating.startswith('BBB') else 0
    if not rating and facts.get('audit_opinion') == 'unqualified':
        rating_score = weights['external_credit'] * .40

    exposure = exposure or {}
    overdue_days = int(_number(exposure.get('overdue_days')) or 0)
    overdue_amount = _number(exposure.get('overdue_amount')) or 0
    trade = weights['trade_behavior'] if overdue_days == 0 and overdue_amount == 0 else weights['trade_behavior'] * .55 if overdue_days <= 15 else weights['trade_behavior'] * .20 if overdue_days <= 30 else 0
    score = round(liquidity + leverage + cashflow + profitability + rating_score + trade, 1)
    missing = [field for field in coverage_fields if field not in present]
    return {
        'score': score,
        'coverage': coverage,
        'ratios': {key: round(value, 4) if value is not None else None for key, value in ratios.items()},
        'trends': {'revenue_yoy': round(revenue_trend, 4) if revenue_trend is not None else None, 'net_profit_yoy': round(profit_trend, 4) if profit_trend is not None else None},
        'breakdown': {
            'liquidity': round(liquidity, 1), 'leverage': round(leverage, 1), 'cashflow': round(cashflow, 1),
            'profitability': round(profitability, 1), 'external_credit': round(rating_score, 1), 'trade_behavior': round(trade, 1),
        },
        'missing_fields': missing,
    }


def grade_for_score(score: float, config: dict[str, Any] | None=None) -> dict[str, Any]:
    config = config or DEFAULT_MODEL_CONFIG
    for grade in sorted(config.get('grades') or [], key=lambda item: item['minimum_score'], reverse=True):
        if score >= float(grade['minimum_score']):
            return grade
    return {'grade': 'D', 'minimum_score': 0, 'limit_multiplier': 0, 'revenue_cap_ratio': 0}


def recommend_conditions(requested: dict[str, Any], facts: dict[str, Any], exposure: dict[str, Any] | None, business_type: str, config: dict[str, Any] | None=None) -> dict[str, Any]:
    """Generate a non-binding recommendation with policy exceptions and locks."""
    config = config or DEFAULT_MODEL_CONFIG
    scorecard = score_facts(facts, exposure, config)
    grade = grade_for_score(scorecard['score'], config)
    requested = requested or {}
    requested_limit = max(0, _number(requested.get('max_credit_amount')) or 0)
    revenue = max(0, _number(facts.get('revenue')) or 0)
    requested_currency = str(requested.get('currency') or facts.get('currency') or 'CNY').upper()
    financial_currency = str(facts.get('financial_currency') or '').upper()
    exposure = exposure or {}
    exposure_currency = str(exposure.get('currency') or '').upper()
    current_exposure = max(0, (_number(exposure.get('current_receivables')) or 0) + (_number(exposure.get('booked_order_amount')) or 0))
    overdue_days = int(_number(exposure.get('overdue_days')) or 0)
    min_coverage = float(config.get('minimum_fact_coverage', 1.0))
    lock_days = int(config.get('overdue_lock_days', 30))
    risk_flags: list[dict[str, str]] = []
    if scorecard['coverage'] < min_coverage:
        risk_flags.append({'code': 'MATERIAL_INCOMPLETE', 'level': 'high', 'message': '核心财务事实不完整，不能自动形成可审批授信额度。'})
    if overdue_days > lock_days:
        risk_flags.append({'code': 'OVERDUE_LOCK', 'level': 'high', 'message': f'客户逾期 {overdue_days} 天，超过制度锁定阈值 {lock_days} 天。'})
    if str(facts.get('audit_opinion') or '').lower() in {'qualified', 'adverse', 'disclaimer'}:
        risk_flags.append({'code': 'AUDIT_OPINION', 'level': 'high', 'message': '审计意见存在保留、否定或无法表示意见，须人工专项复核。'})
    if financial_currency and requested_currency and financial_currency != requested_currency:
        risk_flags.append({'code': 'FINANCIAL_CURRENCY_MISMATCH', 'level': 'high',
                           'message': f'财报金额口径为 {financial_currency}，申请授信币种为 {requested_currency}；未提供经批准汇率，不能自动换算授信额度。'})
    if exposure_currency and requested_currency and exposure_currency != requested_currency:
        risk_flags.append({'code': 'EXPOSURE_CURRENCY_MISMATCH', 'level': 'high',
                           'message': f'应收和订单额度占用的币种为 {exposure_currency}，申请授信币种为 {requested_currency}；未提供经批准汇率，不能自动计算可用额度。'})

    can_recommend = not risk_flags and revenue > 0 and requested_limit > 0
    revenue_cap = revenue * float(grade.get('revenue_cap_ratio', 0))
    recommended_limit = min(requested_limit * float(grade.get('limit_multiplier', 0)), revenue_cap) if can_recommend else 0.0
    available_after_existing = max(0.0, recommended_limit - current_exposure)
    lane = normalized_business_type(business_type)
    requested_days = int(_number(requested.get('max_payment_days')) or 0)
    requested_prepay = max(0.0, _number(requested.get('min_prepayment_ratio')) or 0)
    # TKM 三段式申请字段：首期款采购豁免、走模后尾款放账比例与信用期。
    # 默认值与 normalize_conditions 一致，非 TKM 案件保持空值。
    requested_exempt = bool(requested.get('first_payment_exempt', False))
    requested_tail_ratio = max(0.0, _number(requested.get('tail_payment_ratio')) or 0)
    requested_tail_days = int(_number(requested.get('tail_payment_days')) or 0)
    policy_exceptions: list[str] = []
    if lane == 'TKP':
        recommended_days = min(requested_days, 90)
        recommended_prepay = requested_prepay
        if requested_days > 90:
            policy_exceptions.append('TKP 账期超过 Net 90，须上传市场总监特别账期审批依据。')
    elif lane == 'TKM':
        recommended_days = min(requested_days or 365, 365)
        recommended_prepay = max(requested_prepay, 60.0)
        if requested_prepay < 60:
            policy_exceptions.append('TKM 模具交付前收款低于 60%，须按尾款放账比例或特别信用申请进行专项审批。')
        # 精密模具业务走模后放账比例不超 40%；超出部分须专项审批。
        recommended_tail_ratio = min(requested_tail_ratio, 40.0)
        recommended_tail_days = min(requested_tail_days or 0, 365)
        if requested_tail_ratio > 40:
            policy_exceptions.append('TKM 走模后放账比例超过 40%，须专项审批。')
        if requested_tail_days > 365:
            policy_exceptions.append('TKM 走模后尾款信用期超过 365 天，须专项审批。')
    else:
        recommended_days = requested_days
        recommended_prepay = requested_prepay

    if requested_limit and current_exposure + requested_limit > recommended_limit and recommended_limit > 0:
        risk_flags.append({'code': 'EXPOSURE_CAP', 'level': 'mid', 'message': '现有应收与已入单额度占用叠加申请额度后，可能超过模型建议的信用额度。'})
    recommendation: dict[str, Any] = {
        'max_credit_amount': round(recommended_limit, 2),
        'available_credit_amount': round(available_after_existing, 2),
        'currency': requested_currency,
        'max_payment_days': recommended_days, 'min_prepayment_ratio': round(recommended_prepay, 2),
        'allowed_payment_methods': requested.get('allowed_payment_methods') or ['bank_transfer'],
        'allow_vmi_jit': bool(requested.get('allow_vmi_jit', False)),
        'exposure_at_assessment': round(current_exposure, 2),
    }
    if lane == 'TKM':
        recommendation.update({
            'first_payment_exempt': requested_exempt,
            'tail_payment_ratio': round(recommended_tail_ratio, 2),
            'tail_payment_days': recommended_tail_days,
        })
    return {
        'business_type': lane, 'model_status': 'ready_for_reviewer' if can_recommend else 'needs_material_or_manual_review',
        'credit_grade': grade['grade'], 'scorecard': scorecard, 'risk_flags': risk_flags,
        'policy_exceptions': policy_exceptions,
        'recommendation': recommendation,
    }
