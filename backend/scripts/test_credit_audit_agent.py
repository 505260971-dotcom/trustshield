"""Offline regression for the constrained LLM-planned credit-audit path.

No provider credentials are required.  The test mocks planning/extraction and
asserts that only facts with an exact source quote and an observed number enter
the scoreable fact set; it also verifies qwen rerank index remapping.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services import credit_audit_agent as agent
from app.services import rerank as rerank_service
from app.services.credit_model import recommend_conditions


class _Response:
    def __init__(self, content):
        self.content = content


def _credit_agent_checks():
    document = {'document_id': 'DOC-1', 'document_type': 'financial_report', 'original_name': '客户财报.txt'}
    records = [
        {'text': '合并利润表 单位：人民币千元', 'source_ref': '第10页', 'source_kind': 'pdf', 'start_page': 10},
        {'text': '营业收入 120,000 100,000', 'source_ref': '第10页 · 表格1第4行', 'source_kind': 'table', 'start_page': 10},
        {'text': '管理层预计明年收入将增长', 'source_ref': '第11页', 'source_kind': 'pdf', 'start_page': 11},
    ]
    manifest = agent.build_document_manifest(document, records)
    chunks = agent.build_evidence_chunks(document, records)
    old = agent.configured_financial_llm, agent.get_financial_llm, agent.invoke_remote
    calls = []
    try:
        agent.configured_financial_llm = lambda: True
        agent.get_financial_llm = lambda **_: object()

        def invoke(_llm, _messages, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                return _Response(json.dumps({
                    'material_assessment': '财报可用于核验收入，但仍需核验主体和期间。',
                    'tasks': [{
                        'objective': '核验合并口径营业收入及其单位。',
                        'query': '寻找包含营业收入、币种、单位和财务期间的原始利润表行。',
                        'target_facts': ['revenue'], 'document_ids': ['DOC-1'], 'priority': 'high', 'required': True,
                    }], 'manual_review_items': ['确认报表主体与申请客户一致。'],
                }, ensure_ascii=False))
            return _Response(json.dumps({
                'status': 'verified',
                'findings': [{
                    'field': 'revenue', 'value': 120000, 'prior_value': 100000,
                    'currency': 'CNY', 'source_unit': 'thousand',
                    'evidence_id': next(item['chunk_id'] for item in chunks if '营业收入 120,000' in item['text']),
                    'evidence_quote': '营业收入 120,000 100,000', 'confidence': .9,
                }, {
                    # This must be rejected: quoted text and value are not in
                    # the selected source, even though it looks plausible.
                    'field': 'net_profit', 'value': 9000, 'currency': 'CNY', 'source_unit': 'thousand',
                    'evidence_id': chunks[0]['chunk_id'], 'evidence_quote': '净利润 9,000', 'confidence': .9,
                }], 'missing_information': [], 'conflicts': [],
            }, ensure_ascii=False))

        agent.invoke_remote = invoke
        plan = agent.plan_credit_audit({'customer_name': '测试客户', 'conditions': {}}, [manifest])
        assert plan['mode'] == 'llm_planned' and plan['tasks'][0]['target_facts'] == ['revenue']
        evidence, trace = agent.retrieve_task_evidence(plan, chunks)
        assert trace[0]['value']['mode'] == 'lexical_fallback'
        facts, rows, result = agent.extract_task_facts(plan['tasks'][0], evidence['T1'])
        assert facts['revenue'] == 120_000_000 and facts['prior_revenue'] == 100_000_000
        assert 'net_profit' not in facts
        assert result['status'] == 'verified' and rows[0]['source_quote'] == '营业收入 120,000 100,000'
    finally:
        agent.configured_financial_llm, agent.get_financial_llm, agent.invoke_remote = old


def _rerank_index_checks():
    candidates = [
        {'chunk_id': 'C1', 'text': '营业收入 100', 'source_ref': '第1页', 'source_kind': 'table'},
        {'chunk_id': 'C2', 'text': '营业收入 200', 'source_ref': '第2页', 'source_kind': 'table'},
    ]
    old_configured, old_urlopen, old_base = rerank_service.configured_rerank, rerank_service.urlopen, rerank_service.RERANK_BASE_URL
    try:
        rerank_service.configured_rerank = lambda: True
        rerank_service.RERANK_BASE_URL = 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-api/v1'

        class _HttpResponse:
            def read(self):
                return b'{"id":"request-test","results":[{"index":1,"relevance_score":0.9},{"index":0,"relevance_score":0.4}]}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        rerank_service.urlopen = lambda request, timeout: _HttpResponse()
        result = rerank_service.rerank('查找营业收入', candidates, top_n=2)
        assert result['mode'] == 'qwen3-rerank'
        assert [item['chunk_id'] for item in result['results']] == ['C2', 'C1']
        assert result['request_id'] == 'request-test'
    finally:
        rerank_service.configured_rerank, rerank_service.urlopen, rerank_service.RERANK_BASE_URL = old_configured, old_urlopen, old_base


def _currency_guard_checks():
    facts = {'revenue': 100_000_000, 'current_assets': 60_000_000, 'current_liabilities': 30_000_000,
             'total_assets': 140_000_000, 'total_liabilities': 50_000_000, 'net_profit': 8_000_000,
             'operating_cashflow': 10_000_000, 'financial_currency': 'CNY'}
    result = recommend_conditions({'max_credit_amount': 1_000_000, 'currency': 'CNY', 'max_payment_days': 60}, facts,
                                  {'current_receivables': 10, 'booked_order_amount': 20, 'overdue_days': 0, 'currency': 'HKD'}, '一般')
    assert any(item['code'] == 'EXPOSURE_CURRENCY_MISMATCH' for item in result['risk_flags'])
    assert result['model_status'] == 'needs_material_or_manual_review'


def main():
    _credit_agent_checks()
    _rerank_index_checks()
    _currency_guard_checks()
    print('credit audit planner, evidence validation and rerank adapter passed')


if __name__ == '__main__':
    main()
