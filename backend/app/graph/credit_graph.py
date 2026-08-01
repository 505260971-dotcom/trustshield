"""LangGraph workflow for evidence-led quantitative customer credit assessment."""
from __future__ import annotations

import json
import re
from typing import Any, Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from .. import store
from ..config import FINANCIAL_LLM_EXTRACTION, FINANCIAL_LLM_MODEL, configured_financial_llm, configured_llm, financial_llm_mode
from ..services.credit_audit_agent import (
    build_document_manifest, build_evidence_chunks, extract_task_facts,
    plan_credit_audit, retrieve_task_evidence,
)
from ..services.credit_react_agent import run_react_credit_audit
from ..services.credit_model import recommend_conditions
from ..services.llm import get_financial_llm, get_llm, invoke_remote
from ..services.parse import PARSER_VERSION, read_paragraphs, text_asset_status


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
    evidence_chunks: list[dict[str, Any]]
    audit_plan: dict[str, Any]
    audit_trace: list[dict[str, Any]]
    audit_task_results: list[dict[str, Any]]
    agent_followups: list[dict[str, str]]
    fact_provenance: dict[str, dict[str, Any]]
    react_audit: dict[str, Any]
    on_event: Any
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
_FINANCIAL_FIELDS = frozenset((*_FACT_PATTERNS, 'external_rating', 'audit_opinion'))
_RETRIEVAL_TERMS = {
    'revenue': ('营业收入', '主营业务收入', 'revenue', 'turnover'),
    'current_assets': ('流动资产', 'current assets'),
    'current_liabilities': ('流动负债', 'current liabilities'),
    'total_assets': ('资产总额', '资产合计', 'total assets'),
    'total_liabilities': ('负债总额', '负债合计', 'total liabilities'),
    'net_profit': ('净利润', 'profit for the year', 'net profit'),
    'operating_cashflow': ('经营现金流', '经营活动产生的现金流量净额', 'net cash generated from', 'operating cash flow'),
    'external_rating': ('主体评级', '信用评级', 'credit rating'),
    'audit_opinion': ('审计意见', 'audit opinion', '无保留意见', 'qualified opinion'),
}
_UNIT_MULTIPLIER = {'base': 1, 'thousand': 1_000, 'million': 1_000_000, 'billion': 1_000_000_000}


def _table_numbers(value: str) -> list[float]:
    """Read amounts from one extracted annual-report row, preserving parentheses."""
    raw = re.findall(r'\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|\(?-?\d+(?:\.\d+)?\)?', value or '')
    result = []
    for item in raw:
        negative = item.startswith('(') and item.endswith(')')
        try:
            number = float(item.strip('()').replace(',', ''))
            result.append(-number if negative else number)
        except ValueError:
            continue
    return result


def _statement_currency_and_unit(pages: dict[int, list[str]]) -> tuple[str, int, str] | None:
    """Read the declared statement currency/unit instead of assuming a report locale.

    Audited statements normally repeat a column heading such as ``HK$'000`` on
    every statement page.  Returning ``None`` when that heading cannot be read
    is intentional: an unknown monetary scale must go to manual review, rather
    than silently being treated as HKD.
    """
    text = '\n'.join(line for lines in pages.values() for line in lines)
    currency = None
    if re.search(r'(?:HK\$|HKD|港元)', text, re.I):
        currency = 'HKD'
    elif re.search(r'(?:US\$|USD|美元)', text, re.I):
        currency = 'USD'
    elif re.search(r'(?:RMB|CNY|人民幣|人民币)', text, re.I):
        currency = 'CNY'
    if not currency:
        return None

    if re.search(r"(?:['’]\s*000|\bthousand\b|\b'000\b|千元)", text, re.I):
        return currency, 1_000, f'{currency} thousand'
    if re.search(r'(?:\bmillion\b|百萬元|百万元)', text, re.I):
        return currency, 1_000_000, f'{currency} million'
    if re.search(r'(?:\bunit:\s*(?:HK\$|US\$|RMB|CNY|HKD|USD)|單位[：:]?\s*(?:港元|美元|人民幣|人民币|元))', text, re.I):
        return currency, 1, currency
    return None


def _annual_report_facts(records: list[dict[str, Any]], document_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Extract audited statement rows before attempting loose narrative matching.

    Listed-company reports contain many occurrences of words such as ``revenue``
    in ratios, segment commentary and note numbers.  The former first-match
    strategy could therefore select a percentage or an unrelated note number.
    This parser only accepts the paired current/prior columns on consolidated
    statement pages and keeps their page/period/unit in the evidence object.
    """
    pages: dict[int, list[str]] = {}
    for record in records:
        page = int(record.get('start_page') or 0)
        if page:
            pages.setdefault(page, []).append(str(record.get('text') or ''))

    facts: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []

    # Financial ratios are scale-invariant, but credit limits are not: normalize
    # all stored monetary facts to their base currency before comparing them with
    # a limit.  Do not infer either currency or scale from the company name.
    statement_unit = _statement_currency_and_unit(pages)
    if not statement_unit:
        return {}, []
    currency, unit_multiplier, source_unit = statement_unit

    def add(field: str, current: float, prior: float | None, page: int, row: str, statement: str):
        # Losses and negative operating cash flow are material credit signals,
        # not missing values.  Only a literal zero is ignored here because it
        # is commonly a PDF/table extraction artifact; accounting-relationship
        # checks below still reject impossible balance-sheet totals.
        if current == 0 or field in facts:
            return
        normalized_current = current * unit_multiplier
        normalized_prior = prior * unit_multiplier if prior is not None else None
        facts[field] = normalized_current
        prior_field = {'revenue': 'prior_revenue', 'net_profit': 'prior_net_profit'}.get(field)
        if prior_field and normalized_prior is not None and normalized_prior > 0:
            facts[prior_field] = normalized_prior
        evidence.append({
            'category': 'audited_financial_statement', 'field': field, 'value': normalized_current,
            'document_id': document_id, 'source_ref': f'第{page}页 · {statement}', 'confidence': .96,
            'period': 'current', 'prior_value': normalized_prior, 'currency': currency, 'unit': currency,
            'source_value': current, 'source_prior_value': prior, 'source_unit': source_unit,
            'source_row': row[:240],
        })

    income_pages = [(page, lines) for page, lines in pages.items()
                    if any('CONSOLIDATED STATEMENT OF COMPREHENSIVE INCOME' in line.upper() for line in lines)]
    for page, lines in income_pages:
        for line in lines:
            values = _table_numbers(line)
            if re.search(r'^\s*Revenue\b', line, re.I) and len(values) >= 2:
                add('revenue', values[-2], values[-1], page, line, '合并综合收益表')
            elif re.search(r'^\s*Profit for the year\b', line, re.I) and len(values) >= 2:
                add('net_profit', values[-2], values[-1], page, line, '合并综合收益表')

    balance_header_pages = {page for page, lines in pages.items()
                            if any('CONSOLIDATED BALANCE SHEET' in line.upper() for line in lines)}
    # Statements frequently continue on the immediately following PDF page.
    balance_pages = [(page, lines) for page, lines in pages.items()
                     if page in balance_header_pages or page - 1 in balance_header_pages]

    def subtotal(lines: list[str], begin: str, end: str) -> tuple[float, float] | None:
        start = next((index for index, line in enumerate(lines) if re.search(begin, line, re.I)), None)
        if start is None:
            return None
        stop = next((index for index in range(start + 1, len(lines)) if re.search(end, lines[index], re.I)), len(lines))
        for line in reversed(lines[start + 1:stop]):
            values = _table_numbers(line)
            # Totals in extracted statements are a standalone two-column row.
            if len(values) == 2:
                return values[0], values[1]
        return None

    for page, lines in balance_pages:
        for line in lines:
            values = _table_numbers(line)
            if re.search(r'^\s*Total assets\b', line, re.I) and len(values) >= 2:
                add('total_assets', values[-2], values[-1], page, line, '合并资产负债表')
            elif re.search(r'^\s*Total liabilities\b', line, re.I) and len(values) >= 2:
                add('total_liabilities', values[-2], values[-1], page, line, '合并资产负债表')
        current_assets = subtotal(lines, r'^\s*Current assets\b', r'^\s*Total assets\b')
        if current_assets:
            add('current_assets', current_assets[0], current_assets[1], page, 'Current assets subtotal', '合并资产负债表')
        current_liabilities = subtotal(lines, r'^\s*Current liabilities\b', r'^\s*Total liabilities\b')
        if current_liabilities:
            add('current_liabilities', current_liabilities[0], current_liabilities[1], page, 'Current liabilities subtotal', '合并资产负债表')

    cash_pages = [(page, lines) for page, lines in pages.items()
                  if any('CONSOLIDATED STATEMENT OF CASH FLOWS' in line.upper() for line in lines)]
    for page, lines in cash_pages:
        for index, line in enumerate(lines):
            if re.search(r'Net cash generated from', line, re.I):
                values = _table_numbers(' '.join(lines[index:index + 3]))
                if len(values) >= 2:
                    add('operating_cashflow', values[-2], values[-1], page, ' '.join(lines[index:index + 3]), '合并现金流量表')

    # Only retain a table extraction when its basic accounting relationships
    # hold.  A failed validation leaves fields absent and forces manual review.
    assets, liabilities = facts.get('total_assets'), facts.get('total_liabilities')
    current_assets, current_liabilities = facts.get('current_assets'), facts.get('current_liabilities')
    valid = ((assets is None or liabilities is None or assets >= liabilities > 0)
             and (assets is None or current_assets is None or assets >= current_assets > 0)
             and (liabilities is None or current_liabilities is None or liabilities >= current_liabilities > 0))
    if not valid:
        return {}, []
    if facts:
        facts['financial_currency'] = currency
        facts['financial_unit'] = currency
        facts['financial_source_unit'] = source_unit
        facts['financial_source'] = 'audited_consolidated_statement'
    return facts, evidence


def _retrieve_financial_evidence(records: list[dict[str, Any]], limit: int = 18) -> list[dict[str, Any]]:
    """Return a small, source-addressable context for the financial LLM.

    This is the retrieval half of the financial-report RAG flow.  It is
    deliberately lexical at this stage: statement labels and accounting terms
    are high-precision retrieval keys, work without another service, and leave
    every returned chunk tied to its page/table source.  An embedding retriever
    can later be added as a second ranker without changing the extraction
    schema or evidence contract.
    """
    scored: list[tuple[int, int, dict[str, Any]]] = []
    page_scores: dict[int, int] = {}
    for index, record in enumerate(records):
        text = str(record.get('text') or '')
        lowered = text.lower()
        score = sum(3 for terms in _RETRIEVAL_TERMS.values() for term in terms if term.lower() in lowered)
        if 'consolidated statement' in lowered or '合并' in text:
            score += 2
        if record.get('source_kind') in {'table', 'sheet'}:
            score += 1
        page = int(record.get('start_page') or 0)
        if score and page:
            page_scores[page] = page_scores.get(page, 0) + score
        scored.append((score, index, record))

    # A statement heading often scores while its numeric total is on a nearby
    # line.  Propagate a bounded page score so both are available to the model.
    ranked = []
    for score, index, record in scored:
        page = int(record.get('start_page') or 0)
        adjacent_score = min(4, page_scores.get(page, 0)) if page else 0
        total = score * 10 + adjacent_score
        if total:
            ranked.append((total, index, record))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    chunks = []
    for _, _, record in ranked[:limit]:
        text = str(record.get('text') or '').strip()
        if not text:
            continue
        chunks.append({
            'id': f'E{len(chunks) + 1}',
            'page': int(record.get('start_page') or 0),
            'source_ref': str(record.get('source_ref') or ''),
            'source_kind': str(record.get('source_kind') or 'text'),
            'text': text[:700],
        })
    return chunks


def _json_object(content: Any) -> dict[str, Any]:
    """Accept a strict JSON object, tolerating only harmless markdown fences."""
    text = str(content or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find('{'), text.rfind('}')
        if start < 0 or end <= start:
            raise
        data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError('模型返回的财务抽取结果不是 JSON 对象')
    return data


def _facts_relationships_valid(facts: dict[str, Any]) -> bool:
    def number(name: str) -> float | None:
        try:
            return float(facts[name]) if name in facts else None
        except (TypeError, ValueError):
            return None
    assets, liabilities = number('total_assets'), number('total_liabilities')
    current_assets, current_liabilities = number('current_assets'), number('current_liabilities')
    return ((assets is None or liabilities is None or assets >= liabilities)
            and (assets is None or current_assets is None or assets >= current_assets)
            and (liabilities is None or current_liabilities is None or liabilities >= current_liabilities))


def _llm_financial_facts(records: list[dict[str, Any]], document_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Extract only cited facts from retrieved evidence, never a model calculation.

    The model receives at most 18 source-bound chunks, returns a constrained
    schema, and every accepted number must cite one of those chunk identifiers.
    This makes the LLM a format-adaptive reader rather than an unbounded source
    of financial facts; deterministic accounting checks remain the final gate.
    """
    if not (FINANCIAL_LLM_EXTRACTION and configured_financial_llm()):
        return {}, []
    chunks = _retrieve_financial_evidence(records)
    if not chunks:
        return {}, []
    prompt = '''你是财务报表结构化抽取Agent。只能从提供的证据块抽取，禁止猜测、补全、计算或改写金额。
返回严格 JSON：
{"currency":"CNY|HKD|USD|unknown","source_unit":"base|thousand|million|billion|unknown","facts":[{"field":"revenue|current_assets|current_liabilities|total_assets|total_liabilities|net_profit|operating_cashflow|external_rating|audit_opinion","value":数字或文本,"prior_value":数字或null,"evidence_ids":["E1"],"confidence":0到1}]}
货币金额的 value 必须保持报表原始显示单位，source_unit 表示该单位的倍率；不要把千元转换为元。external_rating 和 audit_opinion 的 source_unit 填 unknown，且 value 只写原文明确支持的结果。一个事实没有证据时不要输出。'''
    run_evidence = {'category': 'financial_llm_run', 'field': 'financial_llm_extraction', 'value': 'attempted',
                    'document_id': document_id, 'source_ref': f'RAG 检索 {len(chunks)} 个证据块', 'confidence': 0,
                    'retrieval': 'lexical_rag', 'model': FINANCIAL_LLM_MODEL}
    try:
        llm = get_financial_llm(json_mode=True, temperature=0, max_tokens=1800, timeout=45, max_retries=0)
        response = invoke_remote(llm, [SystemMessage(content=prompt), HumanMessage(content=json.dumps({'evidence_chunks': chunks}, ensure_ascii=False))], completion_tokens=1800)
        data = _json_object(response.content)
    except Exception as exc:
        run_evidence.update({'value': 'failed', 'error': str(exc)[:300]})
        return {}, [run_evidence]

    currency = str(data.get('currency') or '').upper()
    source_unit = str(data.get('source_unit') or '').lower()
    multiplier = _UNIT_MULTIPLIER.get(source_unit)
    evidence_by_id = {chunk['id']: chunk for chunk in chunks}
    facts: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    for item in data.get('facts') or []:
        if not isinstance(item, dict):
            continue
        field = str(item.get('field') or '')
        cited = [str(item_id) for item_id in (item.get('evidence_ids') or []) if str(item_id) in evidence_by_id]
        if field not in _FINANCIAL_FIELDS or not cited or field in facts:
            continue
        value = item.get('value')
        if field in {'external_rating', 'audit_opinion'}:
            if not isinstance(value, str) or len(value.strip()) > 80:
                continue
            normalized = value.strip()
            source_value = normalized
        else:
            if currency not in {'CNY', 'HKD', 'USD'} or multiplier is None:
                continue
            try:
                source_value = float(str(value).replace(',', ''))
            except (TypeError, ValueError):
                continue
            if not source_value:
                continue
            normalized = source_value * multiplier
        facts[field] = normalized
        primary = evidence_by_id[cited[0]]
        evidence.append({
            'category': 'llm_financial_fact', 'field': field, 'value': normalized, 'document_id': document_id,
            'source_ref': primary['source_ref'], 'confidence': min(.9, max(.5, float(item.get('confidence') or .75))),
            'source_evidence_ids': cited, 'source_row': primary['text'], 'source_value': source_value,
            'currency': currency if field not in {'external_rating', 'audit_opinion'} else '',
            'unit': currency if field not in {'external_rating', 'audit_opinion'} else '',
            'source_unit': source_unit, 'extraction_method': 'rag_llm_structured',
        })
    if not _facts_relationships_valid(facts):
        run_evidence.update({'value': 'rejected_accounting_validation'})
        return {}, [run_evidence]
    if any(field not in {'external_rating', 'audit_opinion'} for field in facts):
        facts['financial_currency'] = currency
        facts['financial_unit'] = currency
        facts['financial_source_unit'] = source_unit
        facts['financial_source'] = 'rag_llm_structured'
    run_evidence.update({'value': 'success', 'accepted_facts': len(facts)})
    return facts, [run_evidence, *evidence]


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


def _extract_from_document(document: dict[str, Any], records: list[dict[str, Any]] | None = None,
                           enable_llm: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    facts: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    records = records if records is not None else _records_for_document(document)
    annual_facts, annual_evidence = _annual_report_facts(records, document['document_id'])
    facts.update(annual_facts)
    evidence.extend(annual_evidence)
    # The bounded RAG + LLM route is format-adaptive.  Audited table facts win
    # on conflicts; LLM facts fill the gaps before the legacy regex fallback.
    if enable_llm:
        llm_facts, llm_evidence = _llm_financial_facts(records, document['document_id'])
        for field, value in llm_facts.items():
            facts.setdefault(field, value)
        evidence.extend(llm_evidence)
    # Regex is now only an offline/last-mile fallback for compact statements or
    # a failed model call.  Its lower-confidence evidence makes this visible to
    # the reviewer instead of presenting it as an audited/LLM extraction.
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


def node_prepare_audit(state: CreditState) -> CreditState:
    """Parse every material once, then give the planning Agent bounded manifests.

    This replaces the former implicit assumption that every uploaded document is
    a financial statement.  The Agent sees declared type *and* actual preview,
    while parsing failures remain explicit audit evidence.
    """
    records_by_document: dict[str, list[dict[str, Any]]] = {}
    manifests: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    for document in state.get('documents') or []:
        document_id = str(document.get('document_id') or '')
        try:
            records = _records_for_document(document)
            records_by_document[document_id] = records
            manifests.append(build_document_manifest(document, records))
            chunks.extend(build_evidence_chunks(document, records))
        except Exception as exc:
            trace.append({'category': 'parse_error', 'field': 'document_parse', 'value': str(exc)[:300],
                          'document_id': document_id, 'source_ref': '', 'confidence': 0})
    state['records_by_document'] = records_by_document
    state['evidence_chunks'] = chunks
    state['audit_trace'] = trace
    state['_audit_manifests'] = manifests
    state['steps'] = [f'材料画像Agent: 已解析 {len(manifests)}/{len(state.get("documents") or [])} 份材料，形成 {len(chunks)} 个可追溯证据块']
    return state


def node_plan_audit(state: CreditState) -> CreditState:
    """Let the LLM choose evidence tasks and task-specific retrieval queries."""
    plan = plan_credit_audit(state.get('case') or {}, state.get('_audit_manifests') or [])
    trace = list(state.get('audit_trace') or [])
    trace.append({'category': 'credit_audit_plan', 'field': 'audit_plan',
                  'value': {'mode': plan.get('mode'), 'material_assessment': plan.get('material_assessment'),
                            'tasks': [{key: task.get(key) for key in ('task_id', 'objective', 'target_facts', 'priority', 'required')}
                                      for task in plan.get('tasks') or []],
                            'manual_review_items': plan.get('manual_review_items') or []},
                  'document_id': '', 'source_ref': '', 'confidence': None})
    state['audit_plan'] = plan
    state['audit_trace'] = trace
    state['steps'] = [f'信审规划Agent: {plan.get("mode")}；基于实际材料规划 {len(plan.get("tasks") or [])} 项证据审查任务']
    return state


def node_retrieve_audit_evidence(state: CreditState) -> CreditState:
    task_evidence, retrieval_trace = retrieve_task_evidence(state.get('audit_plan') or {}, state.get('evidence_chunks') or [])
    state['task_evidence'] = task_evidence
    state['audit_trace'] = [*(state.get('audit_trace') or []), *retrieval_trace]
    qwen_count = sum(1 for item in retrieval_trace if (item.get('value') or {}).get('mode') == 'qwen3-rerank')
    fallback_count = sum(1 for item in retrieval_trace if (item.get('value') or {}).get('mode') == 'lexical_fallback')
    state['steps'] = [f'证据检索Agent: 执行 {len(task_evidence)} 个动态任务，qwen3-rerank {qwen_count} 项，本地回退 {fallback_count} 项']
    return state


def _fact_rank(document: dict[str, Any], evidence: dict[str, Any] | None, field: str) -> int:
    """Resolve conflicts by authority, never upload order."""
    category = str((evidence or {}).get('category') or '')
    document_type = str(document.get('document_type') or 'other')
    score = {
        'audited_financial_statement': 100,
        'agent_audited_fact': 82,
        'llm_financial_fact': 76,
        'credit_report': 64,
        'financial_fact': 50,
    }.get(category, 20)
    if field in {'external_rating', 'audit_opinion'} and document_type == 'credit_report':
        score += 22
    elif field in _FINANCIAL_FIELDS and document_type == 'financial_report':
        score += 16
    return score


def _merge_fact(merged: dict[str, Any], provenance: dict[str, dict[str, Any]], field: str, value: Any,
                document: dict[str, Any], evidence: dict[str, Any] | None) -> None:
    if field.startswith('financial_'):
        # Metadata belongs to the accepted monetary source; it is set together
        # with its fact and must not be overwritten by a weaker document.
        if field not in merged:
            merged[field] = value
        return
    candidate_rank = _fact_rank(document, evidence, field)
    previous = provenance.get(field)
    if previous and candidate_rank < int(previous.get('rank') or 0):
        return
    if previous and candidate_rank == int(previous.get('rank') or 0) and previous.get('value') != value:
        previous['conflict'] = True
        return
    merged[field] = value
    provenance[field] = {
        'rank': candidate_rank, 'value': value, 'document_id': document.get('document_id'),
        'source_ref': (evidence or {}).get('source_ref', ''), 'category': (evidence or {}).get('category', ''),
    }


def node_extract_facts(state: CreditState) -> CreditState:
    merged: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    provenance: dict[str, dict[str, Any]] = {}
    parsed = 0
    for document in state.get('documents') or []:
        try:
            records = (state.get('records_by_document') or {}).get(str(document.get('document_id') or ''))
            # In LLM-planned mode the old all-fields lexical RAG path is not
            # used.  The Agent's task-specific retrieved evidence drives LLM
            # extraction below; audited table parsing and conservative regex
            # remain independent validation/fallback routes.
            planned_mode = (state.get('audit_plan') or {}).get('mode') == 'llm_planned'
            facts, rows = _extract_from_document(document, records=records, enable_llm=not planned_mode)
            rows_by_field = {str(item.get('field') or ''): item for item in rows if item.get('field')}
            for field, value in facts.items():
                _merge_fact(merged, provenance, field, value, document, rows_by_field.get(field))
            evidence.extend(rows)
            parsed += 1
        except Exception as exc:
            evidence.append({'category': 'parse_error', 'field': 'document_parse', 'value': str(exc)[:300],
                             'document_id': document.get('document_id'), 'source_ref': '', 'confidence': 0})

    task_results: list[dict[str, Any]] = []
    if (state.get('audit_plan') or {}).get('mode') == 'llm_planned':
        documents_by_id = {str(item.get('document_id') or ''): item for item in state.get('documents') or []}
        for task in (state.get('audit_plan') or {}).get('tasks') or []:
            facts, rows, result = extract_task_facts(task, (state.get('task_evidence') or {}).get(task.get('task_id'), []))
            task_results.append(result)
            rows_by_field = {str(item.get('field') or ''): item for item in rows if item.get('field')}
            for field, value in facts.items():
                source_document = documents_by_id.get(str((rows_by_field.get(field) or {}).get('document_id') or ''), {'document_type': 'other'})
                _merge_fact(merged, provenance, field, value, source_document, rows_by_field.get(field))
            evidence.extend(rows)
    state['audit_task_results'] = task_results
    state['facts'] = merged
    state['fact_provenance'] = provenance
    state['evidence'] = [*(state.get('audit_trace') or []), *evidence]
    llm_runs = [row for row in evidence if row.get('category') == 'financial_llm_run']
    llm_successes = sum(1 for row in llm_runs if row.get('value') == 'success')
    model_label = '本地/内网模型' if financial_llm_mode() == 'local_or_intranet' else '模型（远端替代）'
    agent_verified = sum(1 for item in task_results if item.get('status') == 'verified')
    state['steps'] = [
        f'财务事实审计Agent(RAG+{model_label}): 解析 {parsed} 份材料，动态任务核验 {agent_verified}/{len(task_results)}，'
        f'旧式RAG+LLM 成功 {llm_successes}/{len(llm_runs)}，提取 {len(merged)} 个结构化事实、{len(state["evidence"])} 条审计证据'
    ]
    return state


def node_measure(state: CreditState) -> CreditState:
    case = state['case']
    result = recommend_conditions(case.get('conditions') or {}, state.get('facts') or {}, state.get('exposure') or {},
                                  case.get('business_type') or '一般', (state.get('model') or {}).get('config'))
    # A planned task that the Agent marks insufficient/conflicted is never a
    # silent success.  It cannot itself alter arithmetic, but it blocks auto-
    # application until a reviewer supplies/verifies the missing evidence.
    followups: list[dict[str, str]] = []
    for field, source in (state.get('fact_provenance') or {}).items():
        if source.get('conflict'):
            result['risk_flags'].append({'code': 'FACT_SOURCE_CONFLICT', 'level': 'high',
                                         'message': f'事实 {field} 存在同等权威来源的不同取值，须人工核验后才能应用建议。'})
            followups.append({'type': 'fact_conflict', 'title': f'核验事实 {field} 的来源冲突',
                              'detail': '系统未自动选择冲突取值；请确认主体、期间、口径、币种和权威来源。'})
    for task in state.get('audit_task_results') or []:
        task_id = str(task.get('task_id') or '')
        if task.get('status') == 'conflict':
            result['risk_flags'].append({'code': 'AGENT_EVIDENCE_CONFLICT', 'level': 'high',
                                         'message': f'证据审查任务 {task_id} 发现来源冲突，须人工确认后才能应用建议。'})
            followups.append({'type': 'evidence_conflict', 'title': f'核验任务 {task_id} 的冲突证据',
                              'detail': '请确认主体、期间、口径和权威来源，不能由模型自动择一。'})
        elif task.get('status') in {'insufficient', 'failed'}:
            details = '；'.join(task.get('missing_information') or []) or str(task.get('reason') or '未获得可验证的原始证据')
            followups.append({'type': 'agent_evidence', 'title': f'补充或核验任务 {task_id} 的证据', 'detail': details[:500]})
            # Only required tasks block automatic application. Optional risk
            # exploration remains visible without converting every unknown into
            # a high-risk finding.
            planned = next((item for item in (state.get('audit_plan') or {}).get('tasks') or [] if item.get('task_id') == task_id), {})
            if planned.get('required'):
                result['risk_flags'].append({'code': 'AGENT_EVIDENCE_INSUFFICIENT', 'level': 'high',
                                             'message': f'必需证据审查任务 {task_id} 未取得可验证证据，不能自动应用授信建议。'})
    if any(item.get('level') == 'high' for item in result.get('risk_flags') or []):
        result['model_status'] = 'needs_material_or_manual_review'
    state['agent_followups'] = followups
    state['missing_materials'] = [*(state.get('missing_materials') or []), *followups]
    state['assessment'] = result
    state['steps'] = [f"量化模型Agent: 模型评分 {result['scorecard']['score']}/100，信用等级 {result['credit_grade']}，材料覆盖率 {result['scorecard']['coverage']:.0%}，Agent 待核验 {len(followups)} 项"]
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
        'audit_plan': state.get('audit_plan') or {}, 'audit_task_results': state.get('audit_task_results') or [],
        'fact_provenance': state.get('fact_provenance') or {},
        'audit_runtime': state.get('react_audit') or {'status': 'execution_failed', 'reason': 'react_audit_missing'},
        # An audit report is always labelled with the sole runtime available to
        # business APIs.  This is provenance, not a selectable mode.
        'runtime_mode': 'production',
    }
    state['steps'] = ['信审汇总结论Agent: 已形成带模型版本、证据与待补项的审批建议快照']
    return state


def node_production_materials(state: CreditState) -> CreditState:
    """Production only parses source files; it does not infer financial facts."""
    records_by_document: dict[str, list[dict[str, Any]]] = {}
    parse_errors = []
    for document in state.get('documents') or []:
        document_id = str(document.get('document_id') or '')
        try:
            records_by_document[document_id] = _records_for_document(document)
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
    state['missing_materials'] = [{'type': 'react_agent', 'title': '补充或人工核验信审证据', 'detail': str(item)[:500]}
                                  for item in audit.get('material_requests') or []]
    state['steps'] = [f"ReAct 信审Agent: 状态 {audit.get('status')}；已验证 Claim {len(audit.get('claims') or [])} 条；"
                      f"Agent 工具轮次 {len(audit.get('trace') or [])}"]
    return state


def _not_assessable_result(audit: dict[str, Any], exposure: dict[str, Any] | None) -> dict[str, Any]:
    status = str(audit.get('status') or 'not_assessable')
    code = 'AGENT_EXECUTION_FAILED' if status == 'execution_failed' else 'AGENT_EVIDENCE_INSUFFICIENT'
    reason = str(audit.get('reason') or '')
    if status == 'execution_failed' and reason.startswith('agent_call_failed:APITimeoutError'):
        message = '主审查模型调用超时，系统已自动重试 1 次仍未完成；系统未采用固定匹配替代。'
    elif status == 'execution_failed' and reason.startswith('agent_call_failed:'):
        message = '主审查模型调用失败，系统已自动重试 1 次仍未完成；系统未采用固定匹配替代。'
    elif status == 'execution_failed':
        message = '生产信审Agent或强制重排服务未能执行，系统未采用固定匹配替代。'
    else:
        message = '核心主体、期间、口径或财务事实未形成经验证Claim，系统不能给出授信建议。'
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
    state['steps'] = [f"生产政策引擎: {result['model_status']}；只有 verified Claim 齐全时才执行评分与额度计算"]
    return state


def build_credit_graph():
    """Production ReAct graph: no legacy matcher participates in facts."""
    graph = StateGraph(CreditState)
    for name, handler in [('production_materials', node_production_materials), ('react_audit', node_react_audit),
                          ('production_measure', node_production_measure), ('explain', node_explain), ('report', node_report)]:
        graph.add_node(name, handler)
    graph.add_edge(START, 'production_materials')
    graph.add_edge('production_materials', 'react_audit')
    graph.add_edge('react_audit', 'production_measure')
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
