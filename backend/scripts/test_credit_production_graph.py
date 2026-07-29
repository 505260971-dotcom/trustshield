"""Integration regression for the production-only ReAct credit graph.

The test deliberately stubs the remote Agent boundary.  It proves graph routing
and fail-closed policy behaviour; it is not a substitute for a live LLM or
DashScope validation.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.graph import credit_graph as graph
from app.services.credit_model import DEFAULT_MODEL_CONFIG


CORE_FACTS = {
    'revenue': 20_000_000, 'current_assets': 12_000_000,
    'current_liabilities': 6_000_000, 'total_assets': 30_000_000,
    'total_liabilities': 12_000_000, 'net_profit': 1_600_000,
    'operating_cashflow': 2_400_000, 'financial_currency': 'CNY',
    'financial_source': 'react_verified_claims',
}


def _case():
    return {
        'case_id': 'production-graph-test', 'customer_name': '生产图测试客户',
        'version': 1, 'business_type': 'TKP', 'updated_at': time.time(),
        'conditions': {'max_credit_amount': 1_000_000, 'currency': 'CNY',
                       'max_payment_days': 120, 'min_prepayment_ratio': 20,
                       'allowed_payment_methods': ['bank_transfer']},
    }


def _audit(status='ready_for_policy'):
    if status != 'ready_for_policy':
        return {'status': status, 'facts': {}, 'claims': [], 'trace': [{'step': 1, 'action': 'tool'}],
                'material_requests': ['缺少可验证的审计财报和 ERP/CRM 敞口快照。']}
    return {'status': status, 'facts': dict(CORE_FACTS),
            'claims': [{'claim_id': key, 'type': 'financial_metric', 'metric': key,
                        'value': value, 'source_ref': 'mock-source'}
                       for key, value in CORE_FACTS.items() if isinstance(value, (int, float))],
            'trace': [{'step': 1, 'action': 'search_evidence'}, {'step': 2, 'action': 'submit_claims'}],
            'material_requests': []}


def main():
    original = (graph.run_react_credit_audit, graph._records_for_document,
                graph._extract_from_document, graph.configured_llm)
    try:
        graph._records_for_document = lambda _document: []
        graph._extract_from_document = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('legacy extraction must not run in production'))
        graph.configured_llm = lambda: False
        document = {'document_id': 'D1', 'document_type': 'financial_report', 'original_name': 'actual-format.pdf'}
        exposure = {'current_receivables': 100_000, 'booked_order_amount': 200_000, 'overdue_amount': 0,
                    'overdue_days': 0, 'currency': 'CNY', 'as_of': time.time()}
        model = {'version': 'test-production-policy', 'config': dict(DEFAULT_MODEL_CONFIG)}

        graph.run_react_credit_audit = lambda *_args, **_kwargs: _audit()
        report, evidence = graph.run_credit_assessment(_case(), [document], exposure, model)
        assert report['runtime_mode'] == 'production'
        assert report['audit_runtime']['status'] == 'ready_for_policy'
        assert report['assessment']['model_status'] == 'ready_for_reviewer'
        assert report['assessment']['scorecard']['coverage'] == 1.0
        assert all(row['category'] != 'credit_fact' for row in evidence), evidence

        graph.run_react_credit_audit = lambda *_args, **_kwargs: _audit('execution_failed')
        failed_report, _ = graph.run_credit_assessment(_case(), [document], exposure, model)
        assert failed_report['assessment']['credit_grade'] == 'UNASSESSABLE'
        assert failed_report['assessment']['recommendation']['max_credit_amount'] == 0
        assert failed_report['assessment']['risk_flags'][0]['code'] == 'AGENT_EXECUTION_FAILED'
    finally:
        (graph.run_react_credit_audit, graph._records_for_document,
         graph._extract_from_document, graph.configured_llm) = original
    print('production graph consumes only ReAct Claims and fails closed')


if __name__ == '__main__':
    main()
