"""Offline regression for the source-cited RAG + LLM financial extractor."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import app.graph.credit_graph as graph


class _Response:
    content = '''{
      "currency":"CNY", "source_unit":"thousand",
      "facts":[
        {"field":"revenue","value":120000,"prior_value":100000,"evidence_ids":["E1"],"confidence":0.91},
        {"field":"current_assets","value":70000,"evidence_ids":["E2"],"confidence":0.9},
        {"field":"current_liabilities","value":30000,"evidence_ids":["E3"],"confidence":0.9},
        {"field":"total_assets","value":150000,"evidence_ids":["E4"],"confidence":0.9},
        {"field":"total_liabilities","value":60000,"evidence_ids":["E5"],"confidence":0.9},
        {"field":"net_profit","value":9000,"evidence_ids":["E6"],"confidence":0.9},
        {"field":"operating_cashflow","value":12000,"evidence_ids":["E7"],"confidence":0.9}
      ]
    }'''


def main():
    # This test intentionally replaces the provider call.  It verifies that a
    # model answer is only accepted when evidence ids, scale and accounting
    # relationships pass the deterministic gate, without requiring credentials.
    old = graph.get_financial_llm, graph.invoke_remote, graph.configured_financial_llm, graph.FINANCIAL_LLM_EXTRACTION
    try:
        graph.get_financial_llm = lambda **_: object()
        graph.invoke_remote = lambda *_args, **_kwargs: _Response()
        graph.configured_financial_llm = lambda: True
        graph.FINANCIAL_LLM_EXTRACTION = True
        records = [
            {'text': '合并利润表 单位：人民币千元 营业收入 120,000 100,000 净利润 9,000', 'start_page': 10, 'source_ref': '第10页', 'source_kind': 'pdf'},
            {'text': '流动资产合计 70,000', 'start_page': 11, 'source_ref': '第11页', 'source_kind': 'pdf'},
            {'text': '流动负债合计 30,000', 'start_page': 11, 'source_ref': '第11页', 'source_kind': 'pdf'},
            {'text': '资产总额 150,000', 'start_page': 11, 'source_ref': '第11页', 'source_kind': 'pdf'},
            {'text': '负债总额 60,000', 'start_page': 11, 'source_ref': '第11页', 'source_kind': 'pdf'},
            {'text': '经营活动产生的现金流量净额 12,000', 'start_page': 12, 'source_ref': '第12页', 'source_kind': 'pdf'},
            {'text': '审计意见：无保留意见', 'start_page': 13, 'source_ref': '第13页', 'source_kind': 'pdf'},
        ]
        facts, evidence = graph._llm_financial_facts(records, 'test-report')
        assert facts['revenue'] == 120_000_000
        assert facts['total_assets'] == 150_000_000
        assert facts['financial_currency'] == 'CNY'
        assert facts['financial_source'] == 'rag_llm_structured'
        assert evidence[0]['value'] == 'success'
        fact_rows = [row for row in evidence if row.get('category') == 'llm_financial_fact']
        assert len(fact_rows) == 7 and all(row['source_evidence_ids'] for row in fact_rows)
        print('financial RAG + LLM extraction gate passed')
    finally:
        graph.get_financial_llm, graph.invoke_remote, graph.configured_financial_llm, graph.FINANCIAL_LLM_EXTRACTION = old


if __name__ == '__main__':
    main()
