"""Regression checks for the quantitative credit-assessment Agent."""
import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

runtime = tempfile.mkdtemp(prefix='contractguard-credit-assessment-')
os.environ.update({
    'CONTRACTGUARD_DATA_DIR': runtime,
    'AUTH_SECRET': 'unit-test-auth-secret-long-enough',
    'DATA_ENCRYPTION_KEY': Fernet.generate_key().decode(),
    'INITIAL_ADMIN_USERNAME': 'admin',
    'INITIAL_ADMIN_PASSWORD': 'AdminPassword2026!',
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import store
from app.graph import credit_graph
from app.graph.credit_graph import run_credit_assessment
from app.services.credit import assess_credit_compliance


def main():
    store.init_db()
    admin = store.authenticate('admin', 'AdminPassword2026!')
    case = store.create_credit_case('量化测试客户', {
        'max_credit_amount': 1_000_000, 'currency': 'CNY', 'max_payment_days': 120,
        'min_prepayment_ratio': 20, 'allowed_payment_methods': ['bank_transfer'], 'allow_vmi_jit': False,
    }, '量化信审回归测试', admin, 'TKP')
    assert case['business_type'] == 'TKP'

    report_path = Path(runtime) / 'customer_financial.txt'
    report_path.write_text('\n'.join([
        '营业收入 20000000 元', '流动资产 12000000 元', '流动负债 6000000 元',
        '资产总额 30000000 元', '负债总额 12000000 元', '净利润 1600000 元',
        '经营现金流 2400000 元', '信用评级 AA+', '审计意见：无保留意见',
    ]), encoding='utf-8')
    document = store.add_credit_document(case['case_id'], 'financial_report', report_path.name, str(report_path), admin)
    snapshot = store.save_credit_exposure_snapshot(case['case_id'], {
        'current_receivables': 100_000, 'booked_order_amount': 200_000,
        'overdue_amount': 0, 'overdue_days': 0, 'currency': 'CNY',
    }, admin)
    raw_document = store.get_credit_document(case['case_id'], document['document_id'])
    # The business graph has no alternate mode.  Mock only the remote ReAct
    # boundary so this offline regression can exercise the production policy
    # path deterministically.
    original_audit = credit_graph.run_react_credit_audit
    try:
        facts = {'revenue': 20_000_000, 'current_assets': 12_000_000, 'current_liabilities': 6_000_000,
                 'total_assets': 30_000_000, 'total_liabilities': 12_000_000, 'net_profit': 1_600_000,
                 'operating_cashflow': 2_400_000, 'financial_currency': 'CNY',
                 'financial_source': 'react_verified_claims'}
        claims = [{'claim_id': key, 'type': 'financial_metric', 'metric': key, 'value': value,
                   'document_id': document['document_id'], 'source_ref': 'offline-react-mock'}
                  for key, value in facts.items() if isinstance(value, (int, float))]
        credit_graph.run_react_credit_audit = lambda *_args, **_kwargs: {
            'status': 'ready_for_policy', 'facts': facts, 'claims': claims, 'trace': [], 'material_requests': []}
        report, evidence = run_credit_assessment(store.get_credit_case(case['case_id']), [raw_document], snapshot['payload'], store.get_credit_model())
    finally:
        credit_graph.run_react_credit_audit = original_audit
    assert report['assessment']['credit_grade'] == 'A'
    assert report['assessment']['recommendation']['max_payment_days'] == 90
    assert report['assessment']['recommendation']['max_credit_amount'] == 1_000_000
    assert len(evidence) >= 7
    assert all(row['category'] == 'react_verified_claim' for row in evidence)

    task = store.start_credit_assessment(case['case_id'], admin)
    stored = store.finish_credit_assessment(task['assessment_id'], report, evidence)
    assert stored['status'] == 'done'
    assert stored['report']['assessment']['scorecard']['coverage'] >= .9
    assert len(stored['evidence']) == len(evidence)

    # Contract enforcement must consider outstanding exposure, not only the
    # face value of the newly uploaded contract.
    findings = assess_credit_compliance([{'text': '合同金额 900000 元，交付前支付20%预付款，货物交付后30天付款。'}], case['conditions'], {
        'current_receivables': 200_000, 'booked_order_amount': 300_000, 'overdue_days': 31, 'currency': 'CNY',
    })
    assert {item['rule_id'] for item in findings} == {'CREDIT_EXPOSURE', 'CREDIT_OVERDUE_LOCK'}
    print('OK: quantitative credit assessment checks passed')


if __name__ == '__main__':
    main()
