"""LangGraph workflow for evidence-led quantitative customer credit assessment."""
from __future__ import annotations

import json
import re
from typing import Any, Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from ..config import configured_llm
from ..services.credit_model import recommend_conditions
from ..services.llm import get_llm, invoke_remote
from ..services.parse import read_paragraphs


class CreditState(TypedDict, total=False):
    case: dict[str, Any]
    documents: list[dict[str, Any]]
    exposure: dict[str, Any]
    model: dict[str, Any]
    facts: dict[str, Any]
    evidence: list[dict[str, Any]]
    missing_materials: list[dict[str, str]]
    assessment: dict[str, Any]
    narrative: dict[str, Any]
    report: dict[str, Any]
    steps: Annotated[list[str], lambda left, right: left + right]


_NUMBER = r'(-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿元|亿元人民币|亿|百万元|万元|万|人民币元|元|RMB|CNY|HKD|USD|million|billion)?'
_FACT_PATTERNS: dict[str, tuple[str, ...]] = {
    'revenue': (r'(?:营业收入|主营业务收入|收入|revenue|turnover)[^0-9\-]{0,24}' + _NUMBER,),
    'prior_revenue': (r'(?:上年(?:营业)?收入|prior\s+year\s+revenue)[^0-9\-]{0,24}' + _NUMBER,),
    'current_assets': (r'(?:流动资产(?:合计)?|current\s+assets)[^0-9\-]{0,24}' + _NUMBER,),
    'quick_assets': (r'(?:速动资产|quick\s+assets)[^0-9\-]{0,24}' + _NUMBER,),
    'current_liabilities': (r'(?:流动负债(?:合计)?|current\s+liabilities)[^0-9\-]{0,24}' + _NUMBER,),
    'total_assets': (r'(?:资产(?:总额|合计)|total\s+assets)[^0-9\-]{0,24}' + _NUMBER,),
    'total_liabilities': (r'(?:负债(?:总额|合计)|total\s+liabilities)[^0-9\-]{0,24}' + _NUMBER,),
    'net_profit': (r'(?:净利润|net\s+profit)[^0-9\-]{0,24}' + _NUMBER,),
    'prior_net_profit': (r'(?:上年净利润|prior\s+year\s+net\s+profit)[^0-9\-]{0,24}' + _NUMBER,),
    'operating_cashflow': (r'(?:经营(?:活动)?产生的现金流量净额|经营现金流|operating\s+cash\s*flow)[^0-9\-]{0,30}' + _NUMBER,),
}
_RATING = re.compile(r'(?:信用评级|主体评级|credit\s+rating)\s*[:：]?\s*((?:AAA|AA\+?|A\+?|BBB\+?|BB\+?|B\+?)[-+]?)', re.I)


def _amount(match: re.Match) -> float:
    raw, unit = match.group(1), (match.group(2) or '').lower()
    value = float(raw.replace(',', ''))
    if '亿' in unit or 'billion' in unit:
        return value * 100_000_000
    if '万' in unit:
        return value * 10_000
    if 'million' in unit or '百万' in unit:
        return value * 1_000_000
    return value


def _extract_from_document(document: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    facts: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    records = read_paragraphs(document['stored_path'])
    # Extract only the first source-bound statement for each fact.  Conflicting
    # values remain visible through the evidence trail and are left to review.
    for record in records:
        text = str(record.get('text') or '')
        for field, patterns in _FACT_PATTERNS.items():
            if field in facts:
                continue
            for pattern in patterns:
                found = re.search(pattern, text, re.I)
                if found:
                    value = _amount(found)
                    facts[field] = value
                    evidence.append({'category': 'financial_fact', 'field': field, 'value': value,
                                     'document_id': document['document_id'], 'source_ref': record.get('source_ref', ''), 'confidence': .78})
                    break
        rating = _RATING.search(text)
        if rating and 'external_rating' not in facts:
            value = rating.group(1).upper()
            facts['external_rating'] = value
            evidence.append({'category': 'credit_report', 'field': 'external_rating', 'value': value,
                             'document_id': document['document_id'], 'source_ref': record.get('source_ref', ''), 'confidence': .80})
        if '无保留意见' in text or re.search(r'unqualified\s+opinion', text, re.I):
            facts.setdefault('audit_opinion', 'unqualified')
        elif '保留意见' in text:
            facts.setdefault('audit_opinion', 'qualified')
        elif '否定意见' in text:
            facts.setdefault('audit_opinion', 'adverse')
        elif '无法表示意见' in text:
            facts.setdefault('audit_opinion', 'disclaimer')
    return facts, evidence


def node_materials(state: CreditState) -> CreditState:
    documents = state.get('documents') or []
    kinds = {item.get('document_type') for item in documents}
    missing = []
    if 'financial_report' not in kinds:
        missing.append({'type': 'financial_report', 'title': '补充客户财报', 'detail': '请上传最近一期经审计财报或可核验的财务报表。'})
    if 'credit_report' not in kinds:
        missing.append({'type': 'credit_report', 'title': '补充第三方信用报告', 'detail': '建议上传评级、征信或工商司法信用报告，并标明报告日期。'})
    if not state.get('exposure'):
        missing.append({'type': 'exposure_snapshot', 'title': '补充应收与订单敞口', 'detail': '请从 CRM/ERP 同步已出货未收款、已入单金额与最长逾期天数。'})
    state['missing_materials'] = missing
    state['steps'] = [f'材料完整性Agent: 已识别 {len(documents)} 份材料，待补 {len(missing)} 项']
    return state


def node_extract_facts(state: CreditState) -> CreditState:
    merged: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    parsed = 0
    for document in state.get('documents') or []:
        try:
            facts, rows = _extract_from_document(document)
            # Financial reports take precedence over less structured supporting
            # documents, while a later document may fill absent fields.
            for field, value in facts.items():
                merged.setdefault(field, value)
            evidence.extend(rows)
            parsed += 1
        except Exception as exc:
            evidence.append({'category': 'parse_error', 'field': 'document_parse', 'value': str(exc)[:300],
                             'document_id': document.get('document_id'), 'source_ref': '', 'confidence': 0})
    state['facts'] = merged
    state['evidence'] = evidence
    state['steps'] = [f'财务事实抽取Agent: 本地解析 {parsed} 份材料，提取 {len(merged)} 个结构化事实、{len(evidence)} 条证据']
    return state


def node_measure(state: CreditState) -> CreditState:
    case = state['case']
    result = recommend_conditions(case.get('conditions') or {}, state.get('facts') or {}, state.get('exposure') or {},
                                  case.get('business_type') or '一般', (state.get('model') or {}).get('config'))
    state['assessment'] = result
    state['steps'] = [f"量化模型Agent: 模型评分 {result['scorecard']['score']}/100，信用等级 {result['credit_grade']}，材料覆盖率 {result['scorecard']['coverage']:.0%}"]
    return state


def _fallback_narrative(assessment: dict[str, Any], missing: list[dict[str, str]]) -> dict[str, Any]:
    recommendation = assessment.get('recommendation') or {}
    flags = assessment.get('risk_flags') or []
    if flags:
        conclusion = '当前存在阻断或需复核事项，不建议自动提交审批。'
    elif missing:
        conclusion = '量化结果可供审核员参考，但建议补齐材料后再提交审批。'
    else:
        conclusion = '量化建议已生成，仍须由信用审核专员复核后送审。'
    return {
        'conclusion': conclusion,
        'summary': f"建议信用等级 {assessment.get('credit_grade')}；建议额度 {recommendation.get('max_credit_amount', 0):g} {recommendation.get('currency', 'CNY')}；建议最长账期 {recommendation.get('max_payment_days', 0)} 天。",
        'key_risks': [flag.get('message') for flag in flags],
        'next_actions': [item['title'] for item in missing] + list(assessment.get('policy_exceptions') or []),
        'generated_by': 'deterministic_fallback',
    }


def node_explain(state: CreditState) -> CreditState:
    fallback = _fallback_narrative(state['assessment'], state.get('missing_materials') or [])
    # The remote model never receives source documents. It only receives the
    # already-scored structured result and is allowed to phrase, not change, it.
    if not configured_llm():
        state['narrative'] = fallback
        state['steps'] = ['意见生成Agent: 主模型未配置，使用确定性说明模板']
        return state
    safe_input = {'assessment': state['assessment'], 'missing_materials': state.get('missing_materials') or []}
    prompt = ('你是企业信审意见生成Agent。仅根据给出的结构化模型结果撰写中文审查摘要；不得增加事实、'
              '不得改变评分、额度、账期、风险标记或制度例外。只输出 JSON：'
              '{"conclusion":"","summary":"","key_risks":[""],"next_actions":[""]}。')
    try:
        llm = get_llm(json_mode=True, temperature=0, max_tokens=700, timeout=20, max_retries=0)
        response = invoke_remote(llm, [SystemMessage(content=prompt), HumanMessage(content=json.dumps(safe_input, ensure_ascii=False))], completion_tokens=700)
        narrative = json.loads(response.content)
        if not isinstance(narrative, dict):
            raise ValueError('模型未返回对象')
        state['narrative'] = {**fallback, **{key: narrative[key] for key in ('conclusion', 'summary', 'key_risks', 'next_actions') if key in narrative}, 'generated_by': 'llm_structured'}
        state['steps'] = ['意见生成Agent: 基于脱离原文的量化结果生成审查摘要']
    except Exception:
        state['narrative'] = fallback
        state['steps'] = ['意见生成Agent: 模型调用失败，使用确定性说明模板']
    return state


def node_report(state: CreditState) -> CreditState:
    state['report'] = {
        'case_id': state['case']['case_id'], 'customer_name': state['case']['customer_name'],
        'case_version': state['case']['version'], 'business_type': state['assessment']['business_type'],
        'model_version': state['model']['version'], 'policy_version': 'dongjiang-credit-policy-v1',
        'created_at': state['case'].get('updated_at'), 'materials': [{key: value for key, value in document.items() if key != 'stored_path'} for document in state.get('documents') or []],
        'facts': state.get('facts') or {}, 'assessment': state['assessment'], 'narrative': state['narrative'],
        'missing_materials': state.get('missing_materials') or [], 'steps': state.get('steps') or [],
    }
    state['steps'] = ['信审汇总结论Agent: 已形成带模型版本、证据与待补项的审批建议快照']
    return state


def build_credit_graph():
    graph = StateGraph(CreditState)
    for name, handler in [('materials', node_materials), ('extract_facts', node_extract_facts), ('measure', node_measure), ('explain', node_explain), ('report', node_report)]:
        graph.add_node(name, handler)
    graph.add_edge(START, 'materials')
    graph.add_edge('materials', 'extract_facts')
    graph.add_edge('extract_facts', 'measure')
    graph.add_edge('measure', 'explain')
    graph.add_edge('explain', 'report')
    graph.add_edge('report', END)
    return graph.compile()


def run_credit_assessment(case: dict[str, Any], documents: list[dict[str, Any]], exposure: dict[str, Any] | None, model: dict[str, Any], on_step=None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run synchronously inside a worker and return report plus persisted evidence."""
    result = build_credit_graph().invoke({'case': case, 'documents': documents, 'exposure': exposure or {}, 'model': model, 'steps': []})
    for step in result.get('steps') or []:
        if on_step:
            on_step(step)
    return result['report'], result.get('evidence') or []
