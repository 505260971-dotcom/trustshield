"""Constrained, evidence-driven LLM credit-audit Agent.

The Agent may inspect a material manifest, plan source-evidence tasks, write
queries and decide whether a task has sufficient evidence.  It cannot set a
credit score, a limit, a payment term, a policy exception or an approval state.
All source facts are independently validated before the quantitative model sees
them.
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import CREDIT_AUDIT_AGENT_ENABLED, CREDIT_AUDIT_AGENT_MAX_TASKS, FINANCIAL_LLM_EXTRACTION, configured_financial_llm
from .llm import clip_text_to_tokens, get_financial_llm, invoke_remote
from .rerank import rerank


KNOWN_FACTS = frozenset({
    'revenue', 'prior_revenue', 'current_assets', 'quick_assets',
    'current_liabilities', 'total_assets', 'total_liabilities', 'net_profit',
    'prior_net_profit', 'operating_cashflow', 'external_rating', 'audit_opinion',
})
NUMERIC_FACTS = KNOWN_FACTS - {'external_rating', 'audit_opinion'}
_UNIT_MULTIPLIER = {'base': 1, 'thousand': 1_000, 'million': 1_000_000, 'billion': 1_000_000_000}
_NUMBER = re.compile(r'\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|\(?-?\d+(?:\.\d+)?\)?')


def _json_object(content: Any) -> dict[str, Any]:
    value = str(content or '').strip()
    if value.startswith('```'):
        value = re.sub(r'^```(?:json)?\s*|\s*```$', '', value, flags=re.I).strip()
    start, end = value.find('{'), value.rfind('}')
    if start >= 0 and end > start:
        value = value[start:end + 1]
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError('Agent 未返回 JSON 对象')
    return data


def build_document_manifest(document: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Give the planner a bounded material view, never an unbounded document."""
    preview_rows = []
    for record in records[:12]:
        text = str(record.get('text') or '').strip()
        if text:
            preview_rows.append({
                'source_ref': str(record.get('source_ref') or ''),
                'source_kind': str(record.get('source_kind') or 'text'),
                'text': clip_text_to_tokens(text, 420),
            })
    kinds: dict[str, int] = {}
    for record in records:
        kind = str(record.get('source_kind') or 'text')
        kinds[kind] = kinds.get(kind, 0) + 1
    return {
        'document_id': str(document.get('document_id') or ''),
        'declared_type': str(document.get('document_type') or 'other'),
        'original_name': str(document.get('original_name') or ''),
        'record_count': len(records), 'source_kinds': kinds, 'preview': preview_rows,
    }


def build_evidence_chunks(document: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make retrieval units with one-record context and stable source anchors."""
    chunks: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        center = str(record.get('text') or '').strip()
        if not center or record.get('source_kind') == 'ocr_pending':
            continue
        before = str(records[index - 1].get('text') or '').strip() if index else ''
        after = str(records[index + 1].get('text') or '').strip() if index + 1 < len(records) else ''
        text = '\n'.join(part for part in (before[-220:], center, after[:220]) if part)
        chunks.append({
            'chunk_id': f"{document.get('document_id') or 'document'}:R{index + 1}",
            'document_id': str(document.get('document_id') or ''),
            'document_type': str(document.get('document_type') or 'other'),
            'source_ref': str(record.get('source_ref') or ''),
            'source_kind': str(record.get('source_kind') or 'text'),
            'page': int(record.get('start_page') or 0),
            # Preserve parser/source provenance for the production Claim
            # verifier.  These fields are metadata, not inferred facts.
            'content_hash': str(document.get('content_hash') or ''),
            'parser_version': str(document.get('text_parser_version') or ''),
            'table_id': str(record.get('table_id') or ''),
            'row': record.get('row'),
            'column': record.get('column'),
            'bbox': record.get('bbox'),
            'text': clip_text_to_tokens(text, 2200),
        })
    return chunks


def _fallback_plan(manifests: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    ids = [item['document_id'] for item in manifests if item.get('document_id')]
    return {
        'mode': 'guardrail_fallback', 'reason': reason,
        'material_assessment': '未配置审查模型，执行本地证据任务；任何不足均转人工复核。',
        'tasks': [
            {'task_id': 'T1', 'objective': '识别可核验的财务状况、盈利与现金流事实。',
             'query': '查找能够直接证明收入、资产、负债、净利润、经营现金流、币种、单位和期间的原始财务证据。',
             'target_facts': ['revenue', 'current_assets', 'current_liabilities', 'total_assets', 'total_liabilities', 'net_profit', 'operating_cashflow'],
             'document_ids': ids, 'priority': 'high', 'required': True},
            {'task_id': 'T2', 'objective': '识别审计意见和第三方信用评级的原始证据。',
             'query': '查找审计意见、主体信用评级、评级机构、评级日期和评级展望的原始证据。',
             'target_facts': ['audit_opinion', 'external_rating'], 'document_ids': ids, 'priority': 'high', 'required': True},
        ],
        'manual_review_items': ['请人工确认客户主体、财务期间、报表口径和材料时效。'],
    }


def _validate_task(raw: Any, sequence: int, valid_ids: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    query = str(raw.get('query') or '').strip()
    objective = str(raw.get('objective') or '').strip()
    if not query or not objective:
        return None
    target_facts = [str(item) for item in raw.get('target_facts', []) if str(item) in KNOWN_FACTS]
    document_ids = [str(item) for item in raw.get('document_ids', []) if str(item) in valid_ids]
    # A task may audit material sufficiency without yielding a scoreable fact.
    priority = str(raw.get('priority') or 'medium').lower()
    return {
        'task_id': f'T{sequence}', 'objective': objective[:360], 'query': query[:900],
        'target_facts': target_facts, 'document_ids': document_ids,
        'priority': priority if priority in {'high', 'medium', 'low'} else 'medium',
        'required': bool(raw.get('required', False)),
    }


def plan_credit_audit(case: dict[str, Any], manifests: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask the LLM to plan auditable evidence work against the actual materials."""
    if not (CREDIT_AUDIT_AGENT_ENABLED and FINANCIAL_LLM_EXTRACTION and configured_financial_llm()):
        return _fallback_plan(manifests, 'credit_audit_agent_or_financial_llm_not_configured')
    policy = '''你是企业信审的“证据审查规划Agent”。你只能规划审查任务，不能给授信额度、账期、评分、审批结论或虚构材料事实。
根据客户案件和材料清单，决定需要核验哪些证据、优先查哪份材料，并为每项任务写一个具体的检索Query。可以识别材料疑点、主体/期间/币种/审计口径问题并提出补件。评分可使用的事实字段仅限：revenue, prior_revenue, current_assets, quick_assets, current_liabilities, total_assets, total_liabilities, net_profit, prior_net_profit, operating_cashflow, external_rating, audit_opinion。
返回严格JSON：{"material_assessment":"", "tasks":[{"objective":"", "query":"", "target_facts":[""], "document_ids":[""], "priority":"high|medium|low", "required":true}], "manual_review_items":[""]}。
任务总数不超过8。任务必须面向原始证据，Query 应要求期间、主体、币种、单位、口径或来源定位（适用时），不得只写字段名。'''
    payload = {
        'customer_name': case.get('customer_name'), 'business_type': case.get('business_type'),
        'requested_conditions': case.get('conditions') or {}, 'materials': manifests,
    }
    try:
        llm = get_financial_llm(json_mode=True, temperature=0, max_tokens=1800, timeout=35, max_retries=0)
        response = invoke_remote(llm, [SystemMessage(content=policy), HumanMessage(content=json.dumps(payload, ensure_ascii=False))], completion_tokens=1800)
        data = _json_object(response.content)
        valid_ids = {str(item.get('document_id') or '') for item in manifests}
        tasks = []
        for raw in data.get('tasks') or []:
            task = _validate_task(raw, len(tasks) + 1, valid_ids)
            if task:
                tasks.append(task)
            if len(tasks) >= CREDIT_AUDIT_AGENT_MAX_TASKS:
                break
        if not tasks:
            raise ValueError('Agent 未规划有效任务')
        covered = {field for task in tasks for field in task['target_facts']}
        essential = {'revenue', 'current_assets', 'current_liabilities', 'total_assets', 'total_liabilities', 'net_profit', 'operating_cashflow'}
        if not (covered & essential):
            # This is a safety guardrail, not a replacement for the Agent's
            # plan: a credit score cannot be computed from only narrative work.
            tasks.append(_fallback_plan(manifests, 'coverage_guardrail')['tasks'][0] | {'task_id': f'T{len(tasks) + 1}'})
        return {
            'mode': 'llm_planned', 'material_assessment': str(data.get('material_assessment') or '')[:1000],
            'tasks': tasks, 'manual_review_items': [str(item)[:500] for item in data.get('manual_review_items', []) if str(item).strip()][:12],
        }
    except Exception as exc:
        return _fallback_plan(manifests, f'planning_failed:{type(exc).__name__}')


def retrieve_task_evidence(plan: dict[str, Any], chunks: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Execute the Agent-written queries through local recall and optional rerank."""
    evidence: dict[str, list[dict[str, Any]]] = {}
    trace: list[dict[str, Any]] = []
    for task in plan.get('tasks') or []:
        allowed = set(task.get('document_ids') or [])
        pool = [item for item in chunks if not allowed or item.get('document_id') in allowed]
        result = rerank(task.get('query') or task.get('objective') or '', pool)
        selected = result.get('results') or []
        evidence[task['task_id']] = selected
        trace.append({
            'category': 'credit_audit_retrieval', 'field': task['task_id'],
            'value': {'objective': task.get('objective'), 'mode': result.get('mode'), 'candidate_count': result.get('candidate_count'),
                      'selected_chunk_ids': [item.get('chunk_id') for item in selected], 'request_id': result.get('request_id', ''),
                      'fallback_reason': result.get('fallback_reason', '')},
            'document_id': '', 'source_ref': '', 'confidence': None,
        })
    return evidence, trace


def _normal(value: str) -> str:
    return re.sub(r'\s+', '', str(value or '')).lower()


def _quote_in_chunks(quote: str, chunks: list[dict[str, Any]]) -> bool:
    probe = _normal(quote)
    # Ratings such as "AAA" can have a short but still meaningful quote. The
    # quote must nevertheless be an actual contiguous source fragment.
    return len(probe) >= 3 and any(probe in _normal(item.get('text') or '') for item in chunks)


def _number_in_chunks(value: float, chunks: list[dict[str, Any]]) -> bool:
    for chunk in chunks:
        for raw in _NUMBER.findall(str(chunk.get('text') or '')):
            try:
                number = float(raw.strip('()').replace(',', ''))
                if raw.startswith('(') and raw.endswith(')'):
                    number = -number
                if abs(number - value) <= max(.0001, abs(value) * 1e-8):
                    return True
            except ValueError:
                continue
    return False


def extract_task_facts(task: dict[str, Any], chunks: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Use the Agent as a cited reader; reject facts whose quote/value is absent."""
    if not chunks:
        return {}, [], {'task_id': task.get('task_id'), 'status': 'insufficient', 'reason': 'no_retrieved_evidence'}
    if not (CREDIT_AUDIT_AGENT_ENABLED and FINANCIAL_LLM_EXTRACTION and configured_financial_llm()):
        return {}, [], {'task_id': task.get('task_id'), 'status': 'not_run', 'reason': 'financial_llm_not_configured'}
    prompt = '''你是企业信审的证据审计Agent。只能从提供的证据块读取，不得猜测、计算、合并不同来源的金额或给出授信结论。
审查任务会指定可抽取字段。每个数字必须保留材料显示的原始数值和原始单位；每个结论必须给出证据块ID及其中连续出现的原文证据短句。无法直接证明就不要输出该事实。
返回严格JSON：{"status":"verified|insufficient|conflict", "findings":[{"field":"允许字段", "value":数字或文本, "prior_value":数字或null, "currency":"CNY|HKD|USD|unknown", "source_unit":"base|thousand|million|billion|unknown", "evidence_id":"", "evidence_quote":"", "confidence":0到1}], "observations":[{"category":"entity|period|document_quality|risk_signal|other", "summary":"", "evidence_id":"", "evidence_quote":""}], "missing_information":[""], "conflicts":[""]}。'''
    payload = {
        'task': task,
        'evidence_chunks': [{'id': item.get('chunk_id'), 'source_ref': item.get('source_ref'), 'text': item.get('text')} for item in chunks],
    }
    try:
        llm = get_financial_llm(json_mode=True, temperature=0, max_tokens=1400, timeout=35, max_retries=0)
        response = invoke_remote(llm, [SystemMessage(content=prompt), HumanMessage(content=json.dumps(payload, ensure_ascii=False))], completion_tokens=1400)
        data = _json_object(response.content)
    except Exception as exc:
        return {}, [], {'task_id': task.get('task_id'), 'status': 'failed', 'reason': f'{type(exc).__name__}: {str(exc)[:160]}'}

    by_id = {str(item.get('chunk_id')): item for item in chunks}
    facts: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    observations: list[dict[str, str]] = []
    allowed = set(task.get('target_facts') or KNOWN_FACTS)
    for item in data.get('findings') or []:
        if not isinstance(item, dict):
            continue
        field = str(item.get('field') or '')
        evidence_id = str(item.get('evidence_id') or '')
        chunk = by_id.get(evidence_id)
        quote = str(item.get('evidence_quote') or '')
        if field not in KNOWN_FACTS or field not in allowed or not chunk or not _quote_in_chunks(quote, [chunk]) or field in facts:
            continue
        value = item.get('value')
        currency = str(item.get('currency') or '').upper()
        source_unit = str(item.get('source_unit') or '').lower()
        if field in NUMERIC_FACTS:
            try:
                raw = float(str(value).replace(',', ''))
            except (TypeError, ValueError):
                continue
            multiplier = _UNIT_MULTIPLIER.get(source_unit)
            if currency not in {'CNY', 'HKD', 'USD'} or multiplier is None or not _number_in_chunks(raw, [chunk]):
                continue
            normalized = raw * multiplier
            facts[field] = normalized
            prior = item.get('prior_value')
            if field == 'revenue' and prior is not None:
                try:
                    prior_raw = float(str(prior).replace(',', ''))
                    if _number_in_chunks(prior_raw, [chunk]):
                        facts.setdefault('prior_revenue', prior_raw * multiplier)
                except (TypeError, ValueError):
                    pass
            if field == 'net_profit' and prior is not None:
                try:
                    prior_raw = float(str(prior).replace(',', ''))
                    if _number_in_chunks(prior_raw, [chunk]):
                        facts.setdefault('prior_net_profit', prior_raw * multiplier)
                except (TypeError, ValueError):
                    pass
        else:
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > 100:
                continue
            normalized = value.strip()
            facts[field] = normalized
        try:
            confidence = min(.92, max(.5, float(item.get('confidence') or .75)))
        except (TypeError, ValueError):
            confidence = .75
        evidence.append({
            'category': 'agent_audited_fact', 'field': field, 'value': normalized,
            'document_id': chunk.get('document_id'), 'source_ref': chunk.get('source_ref'), 'confidence': confidence,
            'task_id': task.get('task_id'), 'task_objective': task.get('objective'), 'source_quote': quote,
            'source_chunk_id': evidence_id, 'currency': currency if field in NUMERIC_FACTS else '',
            'source_unit': source_unit if field in NUMERIC_FACTS else '', 'extraction_method': 'llm_audit_agent',
        })
        if field in NUMERIC_FACTS:
            facts.setdefault('financial_currency', currency)
            facts.setdefault('financial_unit', currency)
            facts.setdefault('financial_source_unit', source_unit)
            facts.setdefault('financial_source', 'llm_audit_agent')
    for item in data.get('observations') or []:
        if not isinstance(item, dict) or len(observations) >= 12:
            continue
        evidence_id = str(item.get('evidence_id') or '')
        quote = str(item.get('evidence_quote') or '')
        chunk = by_id.get(evidence_id)
        category = str(item.get('category') or 'other').lower()
        summary = str(item.get('summary') or '').strip()
        if not chunk or not summary or not _quote_in_chunks(quote, [chunk]):
            continue
        observations.append({
            'category': category if category in {'entity', 'period', 'document_quality', 'risk_signal', 'other'} else 'other',
            'summary': summary[:500], 'source_ref': str(chunk.get('source_ref') or ''),
            'source_chunk_id': evidence_id, 'source_quote': quote[:500],
        })
    status = str(data.get('status') or 'insufficient')
    if task.get('target_facts') and not any(field in facts for field in task.get('target_facts') or []):
        status = 'insufficient'
    return facts, evidence, {
        'task_id': task.get('task_id'), 'status': status if status in {'verified', 'insufficient', 'conflict'} else 'insufficient',
        'accepted_facts': list(facts), 'missing_information': [str(item)[:300] for item in data.get('missing_information', [])][:8],
        'conflicts': [str(item)[:300] for item in data.get('conflicts', [])][:8], 'observations': observations,
    }
