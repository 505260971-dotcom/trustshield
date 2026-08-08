"""Production LangGraph workflow for evidence-led quantitative credit assessment.

The only registered graph is the ReAct audit graph: parse materials, run the
bounded ReAct evidence auditor, apply the deterministic policy engine, phrase
the structured result, and build the report.  No legacy matcher, regex fact
path or audit-plan pipeline participates in production facts.
"""
from __future__ import annotations

import json
from typing import Any, Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from .. import store
from ..config import configured_llm
from ..services.credit_evidence import build_document_manifest, build_evidence_chunks
from ..services.credit_react_agent import run_react_credit_audit
from ..services.credit_model import recommend_conditions
from ..services.exa_mcp import run_external_due_diligence
from ..services.llm import get_llm, invoke_remote
from ..services.parse import PARSER_VERSION, read_paragraphs, text_asset_status
from ..services.smart_mask import restore_text


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
    records_by_document: dict[str, list[dict[str, Any]]]
    react_audit: dict[str, Any]
    external_due_diligence: dict[str, Any]
    on_event: Any
    steps: Annotated[list[str], lambda left, right: left + right]


def _records_for_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Reuse the encrypted normalized text asset when the file hash is unchanged."""
    document_id = str(document.get('document_id') or '')
    content_hash = str(document.get('content_hash') or '')
    if document_id and content_hash:
        try:
            asset = store.get_credit_document_text_asset(document_id, content_hash)
            # A partial asset contains native text plus explicit OCR gaps.  Do
            # not cache it forever: after an operator installs/fixes Tesseract,
            # the next assessment retries those pages and upgrades the asset.
            if asset and asset.get('status') == 'ready' and asset.get('parser_version') == PARSER_VERSION:
                records = asset.get('records') or []
                if isinstance(records, list) and records:
                    return records
        except Exception:
            # A transient cache read must never hide a source-document parse.
            pass
    try:
        records = read_paragraphs(document['stored_path'])
    except Exception as exc:
        if document_id and content_hash:
            try:
                store.save_credit_document_text_asset(document_id, content_hash, None, PARSER_VERSION, 'failed', str(exc))
            except Exception:
                pass
        raise
    if document_id and content_hash:
        try:
            store.save_credit_document_text_asset(document_id, content_hash, records, PARSER_VERSION, text_asset_status(records))
        except Exception:
            # The raw source and in-memory records still permit the assessment;
            # persistence failure is reported in evidence by the caller if it
            # prevents a later run from reusing the asset.
            pass
    return records


# 超大材料（如整份年报 PDF）可解析出上万条记录。全量送本地脱敏模型
# 会串行数百次 LLM 调用，让评估等待数十分钟。按页保留代表性记录：
# 每页保留头部、尾部与均匀采样，覆盖“页首身份信息 + 页尾财务摘要”。
# 被裁剪的记录不会进入脱敏与检索环节，因此也不会外发，安全边界不变。
RECORD_BUDGET_PER_DOCUMENT = 900
RECORD_BUDGET_PER_PAGE = 32


def _budgeted_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(records) <= RECORD_BUDGET_PER_DOCUMENT:
        return records
    pages: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        page = str(record.get('start_page') or record.get('page') or 0)
        pages.setdefault(page, []).append(record)
    per_page_limit = max(12, min(RECORD_BUDGET_PER_PAGE, RECORD_BUDGET_PER_DOCUMENT // max(1, len(pages))))
    out: list[dict[str, Any]] = []
    for items in pages.values():
        if len(items) <= per_page_limit:
            out.extend(items)
            continue
        keep: list[dict[str, Any]] = []
        head = items[:3]
        tail = items[-3:]
        keep.extend(head)
        step = (len(items) - 6) / (per_page_limit - 6) if per_page_limit > 6 else len(items)
        for k in range(per_page_limit - 6):
            index = 3 + int(round(k * step))
            if index < len(items) - 3 and items[index] not in keep:
                keep.append(items[index])
        keep.extend(tail)
        out.extend(keep)
    return out[:RECORD_BUDGET_PER_DOCUMENT]


def node_production_materials(state: CreditState) -> CreditState:
    """Production only parses source files; it does not infer financial facts."""
    records_by_document: dict[str, list[dict[str, Any]]] = {}
    parse_errors = []
    for document in state.get('documents') or []:
        document_id = str(document.get('document_id') or '')
        try:
            records_by_document[document_id] = _budgeted_records(_records_for_document(document))
        except Exception as exc:
            parse_errors.append({'document_id': document_id, 'error': str(exc)[:300]})
    state['records_by_document'] = records_by_document
    state['evidence'] = [{'category': 'production_parse_error', 'field': 'document_parse', 'value': item['error'],
                          'document_id': item['document_id'], 'source_ref': '', 'confidence': 0} for item in parse_errors]
    state['steps'] = [f'生产材料工具: 成功解析 {len(records_by_document)}/{len(state.get("documents") or [])} 份材料；不执行固定字段匹配']
    return state


def node_react_audit(state: CreditState) -> CreditState:
    audit = run_react_credit_audit(
        state.get('case') or {}, state.get('documents') or [], state.get('records_by_document') or {}, state.get('exposure') or {},
        on_event=state.get('on_event'),
    )
    # The model only ever saw masked evidence; restore quotes and entities to
    # the original text for the local report before the mapping is discarded.
    mask_mapping = audit.pop('mask_mapping', {}) or {}
    for claim in audit.get('claims') or []:
        if claim.get('entity_name'):
            claim['entity_name'] = restore_text(claim['entity_name'], mask_mapping)
        if claim.get('evidence_quote'):
            claim['evidence_quote'] = restore_text(claim['evidence_quote'], mask_mapping)
        for ref in claim.get('evidence_refs') or []:
            if ref.get('evidence_quote'):
                ref['evidence_quote'] = restore_text(ref['evidence_quote'], mask_mapping)
    for item in audit.get('observations') or []:
        if item.get('summary'):
            item['summary'] = restore_text(item['summary'], mask_mapping)
        if item.get('evidence_quote'):
            item['evidence_quote'] = restore_text(item['evidence_quote'], mask_mapping)
    # The Agent trace and every verified Claim are persisted in the encrypted
    # assessment report/evidence table, allowing a reviewer to reproduce why a
    # recommendation was or was not possible.
    claim_evidence = [{'category': 'react_verified_claim', 'field': str(item.get('type') or ''), 'value': item,
                       'document_id': item.get('document_id'), 'source_ref': item.get('source_ref', ''), 'confidence': 1.0}
                      for item in audit.get('claims') or []]
    state['react_audit'] = audit
    state['facts'] = audit.get('facts') or {}
    # The full ReAct trace is already embedded in ``audit_runtime`` and has a
    # dedicated frontend step view.  Do not duplicate opaque trace objects in
    # the source-evidence list, where browsers previously rendered them as
    # "[object Object]" and obscured the actual verified Claims.
    state['evidence'] = [*(state.get('evidence') or []), *claim_evidence]
    state['missing_materials'] = [{'type': 'react_agent', 'title': '补充或人工核验信用审核依据', 'detail': str(item)[:500]}
                                  for item in audit.get('material_requests') or []]
    state['steps'] = [f"Agent 审查：状态 {audit.get('status')}；已核验事实 {len(audit.get('claims') or [])} 条；"
                      f"处理步骤 {len(audit.get('trace') or [])}"]
    return state


def node_external_due_diligence(state: CreditState) -> CreditState:
    """Add public-web signals as reviewable evidence, never as financial facts."""
    result = run_external_due_diligence(state.get('case') or {}, on_event=state.get('on_event'))
    state['external_due_diligence'] = result
    external_evidence = [
        {'category': 'external_due_diligence', 'field': str(item.get('source_type') or 'public_web'),
         'value': item, 'source_ref': str(item.get('url') or item.get('title') or ''), 'confidence': 0.6}
        for item in result.get('sources') or []
    ]
    state['evidence'] = [*(state.get('evidence') or []), *external_evidence]
    findings = result.get('findings') or []
    if findings:
        state['missing_materials'] = [*(state.get('missing_materials') or []), {
            'type': 'external_due_diligence', 'title': '核验 Exa 公开风险线索',
            'detail': f'发现 {len(findings)} 条公开风险线索，须由信用审核专员逐条确认主体匹配和处理结论。',
        }]
    elif result.get('status') in {'unavailable', 'rate_limited'}:
        state['missing_materials'] = [*(state.get('missing_materials') or []), {
            'type': 'external_due_diligence', 'title': 'Exa 公开尽调暂不可用',
            'detail': '未能获得外部公开信息结果；请人工核验或稍后重试，不能将此状态解读为客户无风险。',
        }]
    state['steps'] = [f"外部公开尽调：{result.get('message') or result.get('status')}"]
    return state


def _not_assessable_result(audit: dict[str, Any], exposure: dict[str, Any] | None) -> dict[str, Any]:
    status = str(audit.get('status') or 'not_assessable')
    code = 'AGENT_EXECUTION_FAILED' if status == 'execution_failed' else 'AGENT_EVIDENCE_INSUFFICIENT'
    reason = str(audit.get('reason') or '')
    if status == 'execution_failed' and reason.startswith('agent_call_failed:APITimeoutError'):
        message = 'Agent 审查模型调用超时，系统已自动重试 1 次仍未完成；未采用固定匹配替代。'
    elif status == 'execution_failed' and reason.startswith('agent_call_failed:'):
        message = 'Agent 审查模型调用失败，系统已自动重试 1 次仍未完成；未采用固定匹配替代。'
    elif status == 'execution_failed':
        message = 'Agent 审查或强制依据排序服务未能执行，未采用固定匹配替代。'
    else:
        message = '核心主体、期间、口径或财务事实未完成核验，系统不能给出授信建议。'
    return {
        'business_type': '一般', 'model_status': 'execution_failed' if status == 'execution_failed' else 'not_assessable',
        'credit_grade': 'UNASSESSABLE',
        'scorecard': {'score': None, 'coverage': 0, 'ratios': {}, 'trends': {}, 'breakdown': {}, 'missing_fields': audit.get('material_requests') or []},
        'risk_flags': [{'code': code, 'level': 'high', 'message': message}], 'policy_exceptions': [],
        'recommendation': {'max_credit_amount': 0, 'available_credit_amount': 0,
                           'currency': str((exposure or {}).get('currency') or 'CNY').upper(), 'max_payment_days': 0,
                           'min_prepayment_ratio': 100, 'allowed_payment_methods': [], 'allow_vmi_jit': False,
                           'exposure_at_assessment': 0},
    }


def node_production_measure(state: CreditState) -> CreditState:
    audit = state.get('react_audit') or {}
    if audit.get('status') == 'ready_for_policy':
        case = state['case']
        result = recommend_conditions(case.get('conditions') or {}, state.get('facts') or {}, state.get('exposure') or {},
                                      case.get('business_type') or '一般', (state.get('model') or {}).get('config'))
    else:
        result = _not_assessable_result(audit, state.get('exposure'))
    state['assessment'] = result
    state['steps'] = [f"政策检查：{result['model_status']}；只有关键事实全部核验通过时才执行评分与额度计算"]
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
        state['steps'] = ['Agent 意见生成：Agent 模型未配置，使用确定性说明模板']
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
        state['steps'] = ['Agent 意见生成：根据 Agent 评估结果生成审查摘要']
    except Exception:
        state['narrative'] = fallback
        state['steps'] = ['Agent 意见生成：模型调用失败，使用确定性说明模板']
    return state


def node_report(state: CreditState) -> CreditState:
    state['report'] = {
        'case_id': state['case']['case_id'], 'customer_name': state['case']['customer_name'],
        'case_version': state['case']['version'], 'business_type': state['assessment']['business_type'],
        'model_version': state['model']['version'], 'policy_version': 'dongjiang-credit-policy-v1',
        'created_at': state['case'].get('updated_at'), 'materials': [{key: value for key, value in document.items() if key != 'stored_path'} for document in state.get('documents') or []],
        'facts': state.get('facts') or {}, 'assessment': state['assessment'], 'narrative': state['narrative'],
        'external_due_diligence': state.get('external_due_diligence') or {},
        'missing_materials': state.get('missing_materials') or [], 'steps': state.get('steps') or [],
        'audit_runtime': state.get('react_audit') or {'status': 'execution_failed', 'reason': 'react_audit_missing'},
        # An audit report is always labelled with the sole runtime available to
        # business APIs.  This is provenance, not a selectable mode.
        'runtime_mode': 'production',
    }
    state['steps'] = ['信用审核总结：已形成带模型版本、依据与待补项的审批建议记录']
    return state


def build_credit_graph():
    """Production ReAct graph: no legacy matcher participates in facts."""
    graph = StateGraph(CreditState)
    for name, handler in [('production_materials', node_production_materials), ('react_audit', node_react_audit), ('external_due_diligence', node_external_due_diligence),
                          ('production_measure', node_production_measure), ('explain', node_explain), ('report', node_report)]:
        graph.add_node(name, handler)
    graph.add_edge(START, 'production_materials')
    graph.add_edge('production_materials', 'react_audit')
    graph.add_edge('react_audit', 'external_due_diligence')
    graph.add_edge('external_due_diligence', 'production_measure')
    graph.add_edge('production_measure', 'explain')
    graph.add_edge('explain', 'report')
    graph.add_edge('report', END)
    return graph.compile()


def run_credit_assessment(case: dict[str, Any], documents: list[dict[str, Any]], exposure: dict[str, Any] | None,
                          model: dict[str, Any], on_step=None, on_event=None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run synchronously inside a worker and return report plus persisted evidence.

    Stream graph values rather than reporting every step only after ``invoke``
    returns.  A ReAct tool round can take tens of seconds, so the UI needs the
    completed node milestones while the background worker is still running.
    """
    graph = build_credit_graph()
    result: dict[str, Any] = {}
    emitted_steps = 0
    initial = {'case': case, 'documents': documents, 'exposure': exposure or {}, 'model': model, 'steps': [], 'on_event': on_event}
    for state in graph.stream(initial, stream_mode='values'):
        result = state
        steps = state.get('steps') or []
        for step in steps[emitted_steps:]:
            if on_step:
                on_step(step)
        emitted_steps = len(steps)
    return result['report'], result.get('evidence') or []
