"""Regression for production ReAct credit audit: no fallback facts are allowed."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services import credit_react_agent as react


class _Response:
    def __init__(self, content): self.content = content


def _records():
    return [
        {'text': '测试客户 合并口径 2025年度 单位：人民币千元', 'source_ref': '第1页', 'source_kind': 'pdf', 'start_page': 1},
        {'text': '营业收入 120,000', 'source_ref': '第2页 · 表格1第1行', 'source_kind': 'table', 'start_page': 2},
        {'text': '流动资产 80,000', 'source_ref': '第2页 · 表格1第2行', 'source_kind': 'table', 'start_page': 2},
        {'text': '流动负债 40,000', 'source_ref': '第2页 · 表格1第3行', 'source_kind': 'table', 'start_page': 2},
        {'text': '资产总额 180,000', 'source_ref': '第2页 · 表格1第4行', 'source_kind': 'table', 'start_page': 2},
        {'text': '负债总额 70,000', 'source_ref': '第2页 · 表格1第5行', 'source_kind': 'table', 'start_page': 2},
        {'text': '净利润 10,000', 'source_ref': '第3页 · 表格1第1行', 'source_kind': 'table', 'start_page': 3},
        {'text': '经营活动产生的现金流量净额 13,000', 'source_ref': '第3页 · 表格1第2行', 'source_kind': 'table', 'start_page': 3},
    ]


def _claims():
    rows = [{'claim_id': 'entity', 'type': 'identity', 'entity_name': '测试客户', 'evidence_id': 'DOC:R1', 'evidence_quote': '测试客户 合并口径 2025年度 单位：人民币千元'},
            {'claim_id': 'ctx', 'type': 'financial_context', 'entity_name': '测试客户', 'period': '2025年度', 'scope': 'consolidated', 'currency': 'CNY', 'source_unit': 'thousand', 'evidence_id': 'DOC:R1', 'evidence_quote': '测试客户 合并口径 2025年度 单位：人民币千元'}]
    mapping = [('revenue', 120000), ('current_assets', 80000), ('current_liabilities', 40000), ('total_assets', 180000), ('total_liabilities', 70000), ('net_profit', 10000), ('operating_cashflow', 13000)]
    for index, (metric, value) in enumerate(mapping, 2):
        rows.append({'claim_id': metric, 'type': 'financial_metric', 'metric': metric, 'value': value, 'context_id': 'ctx',
                     'evidence_id': f'DOC:R{index}', 'evidence_quote': _records()[index - 1]['text']})
    return rows


def main():
    assert react._claim_kind({'entity_name': '测试客户'}) == 'identity'
    assert react._claim_kind({'period': '2025年度', 'scope': '合并口径', 'currency': '人民币', 'source_unit': '元'}) == 'financial_context'
    assert react._claim_kind({'metric': '营业收入', 'value': 1}) == 'financial_metric'
    # Page context must not discard the financial body merely because a DOCX
    # stores it as ordinary paragraphs after a long report header.
    prose_page = [{'chunk_id': f'DOC:R{i}', 'source_kind': 'text', 'text': str(i)} for i in range(1, 27)]
    selected_ids = [item['chunk_id'] for item in react._page_context_selection(prose_page)]
    assert len(selected_ids) == 24 and 'DOC:R1' in selected_ids and 'DOC:R14' in selected_ids and 'DOC:R21' in selected_ids
    controller = react._controller_instruction({'verified_claim_count': 2, 'identity_verified': True,
                                                 'financial_context_verified': True, 'verified_metrics': [],
                                                 'missing_metrics': sorted(react.CORE_METRICS)}, 10, 16, 0)
    assert '已可见的同页来源块' in controller
    split_header_chunks = {
        'DOC:H1': {'text': '测试客户 2025年度合并财务报表', 'document_id': 'DOC', 'source_ref': '第1页 · 页眉', 'page': 1},
        'DOC:H2': {'text': '财务数据币种：CNY；金额单位：人民币元', 'document_id': 'DOC', 'source_ref': '第1页 · 口径', 'page': 1},
        'DOC:H3': {'text': '财务数据币种：CNY；金额单位：人民币元', 'document_id': 'DOC', 'source_ref': '第2页 · 口径', 'page': 2},
    }
    split_context = {'claim_id': 'split_ctx', 'type': 'financial_context', 'entity_name': '测试客户', 'period': '2025年度',
                     'scope': 'consolidated', 'currency': 'CNY', 'source_unit': 'base',
                     'evidence_refs': [{'evidence_id': 'DOC:H1', 'evidence_quote': '测试客户 2025年度合并财务报表'},
                                       {'evidence_id': 'DOC:H2', 'evidence_quote': '财务数据币种：CNY；金额单位：人民币元'}]}
    valid, rejected, _ = react._validate_claims([split_context], split_header_chunks, {'customer_name': '测试客户'}, {})
    assert len(valid) == 1 and not rejected and len(valid[0]['evidence_refs']) == 2
    split_context['evidence_refs'][1]['evidence_id'] = 'DOC:H3'
    _, rejected, _ = react._validate_claims([split_context], split_header_chunks, {'customer_name': '测试客户'}, {})
    assert rejected and '同一文档同一页' in rejected[0]['reason']
    document = {'document_id': 'DOC', 'document_type': 'financial_report', 'original_name': 'unknown-format.pdf'}
    old = react.configured_financial_llm, react.get_financial_llm, react.invoke_remote, react.rerank_required
    try:
        react.configured_financial_llm = lambda: True
        react.get_financial_llm = lambda **_: object()
        turns = []

        def invoke(_llm, _messages, **_kwargs):
            turns.append(1)
            if len(turns) in {1, 2}:
                return _Response(json.dumps({'reason_summary': '先检索财务报表原始证据', 'action': 'tool', 'tool': 'search_evidence',
                                               'arguments': {'query': '测试客户 2025年度 合并财务报表核心指标', 'document_ids': ['DOC']}, 'claims': [], 'material_requests': []}, ensure_ascii=False))
            return _Response(json.dumps({'reason_summary': '证据完整，提交可验证Claim', 'action': 'submit_claims', 'tool': '',
                                           'arguments': {}, 'claims': _claims(), 'material_requests': []}, ensure_ascii=False))

        react.invoke_remote = invoke
        rerank_calls = []
        def rerank(_query, pool):
            rerank_calls.append(_query)
            return {'mode': 'qwen3-rerank', 'request_id': 'mock-rerank', 'results': pool}
        react.rerank_required = rerank
        result = react.run_react_credit_audit({'customer_name': '测试客户', 'conditions': {}}, [document], {'DOC': _records()},
                                              {'current_receivables': 0, 'booked_order_amount': 0, 'overdue_days': 0, 'currency': 'CNY', 'as_of': time.time()})
        assert result['status'] == 'ready_for_policy', result
        assert result['facts']['revenue'] == 120_000_000
        assert len(result['trace']) == 3
        assert result['trace'][0]['tool'] == 'search_evidence'
        assert result['trace'][0]['result_summary'].startswith('search_evidence：返回')
        assert result['trace'][1]['observation']['error'] == 'duplicate_tool_call'
        assert len(rerank_calls) == 1, '重复工具调用不得再次触发远程重排'
        assert result['trace'][-1]['progress_after']['verified_metrics'] == sorted(react.CORE_METRICS)
        assert len(result['claims']) == 9
    finally:
        react.configured_financial_llm, react.get_financial_llm, react.invoke_remote, react.rerank_required = old

    # Missing Agent configuration is an execution failure, not a fixture path.
    old = react.configured_financial_llm
    try:
        react.configured_financial_llm = lambda: False
        failed = react.run_react_credit_audit({'customer_name': '测试客户'}, [document], {'DOC': _records()}, {})
        assert failed['status'] == 'execution_failed' and not failed['facts']
    finally:
        react.configured_financial_llm = old

    # A transient provider timeout gets exactly one retry; no local fact path is used.
    old = react.get_financial_llm, react.invoke_remote, react.time.sleep
    try:
        calls = []
        react.get_financial_llm = lambda **_: object()
        react.time.sleep = lambda _: None
        def retry_once(_llm, _messages, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError('simulated timeout')
            return _Response('{"action":"finish"}')
        react.invoke_remote = retry_once
        _, retry_count = react._invoke_agent_with_one_retry([])
        assert retry_count == 1 and len(calls) == 2
    finally:
        react.get_financial_llm, react.invoke_remote, react.time.sleep = old
    print('production ReAct audit fails closed and accepts only verified Claims')


if __name__ == '__main__':
    main()
