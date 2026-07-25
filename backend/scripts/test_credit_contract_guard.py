"""Regression checks for the 'credit first, contract second' control boundary."""
import os
import sys
import tempfile

from cryptography.fernet import Fernet

tmp = tempfile.mkdtemp(prefix='contractguard-credit-test-')
os.environ.update({
    'CONTRACTGUARD_DATA_DIR': tmp,
    'AUTH_SECRET': 'unit-test-auth-secret-long-enough',
    'DATA_ENCRYPTION_KEY': Fernet.generate_key().decode(),
    'INITIAL_ADMIN_USERNAME': 'admin',
    'INITIAL_ADMIN_PASSWORD': 'AdminPassword2026!',
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import store
from app.services.credit import assess_credit_compliance, assess_customer_binding


def approved_credit(admin, days=45):
    item = store.create_credit_case('测试客户甲', {
        'max_credit_amount': 100000,
        'currency': 'CNY',
        'max_payment_days': days,
        'min_prepayment_ratio': 30,
        'allowed_payment_methods': ['bank_transfer'],
        'allow_vmi_jit': False,
    }, '回归测试信审', admin)
    store.submit_credit_case(item['case_id'], admin)
    return store.decide_credit_case(item['case_id'], 'approved', '信审批准', admin)


def main():
    store.init_db()
    admin = store.authenticate('admin', 'AdminPassword2026!')
    credit_v1 = approved_credit(admin)
    assert store.require_active_credit_case(credit_v1['case_id'])['version'] == 1

    clauses = [{'id': 'C1', 'text': '货物交付后60天付款，交付前支付20%预付款，付款方式为银行承兑汇票，并采用VMI模式。'}]
    findings = assess_credit_compliance(clauses, credit_v1['conditions'])
    assert {item['rule_id'] for item in findings} == {'CREDIT_TERM', 'CREDIT_PREPAYMENT', 'CREDIT_PAYMENT_METHOD', 'CREDIT_DELIVERY_MODE'}
    assert assess_customer_binding({'our_party': '乙方', 'parties': {'甲方': '测试客户甲有限公司'}}, '测试客户甲') == []
    assert assess_customer_binding({'our_party': '乙方', 'parties': {'甲方': '另一家客户'}}, '测试客户甲')[0]['rule_id'] == 'CREDIT_CUSTOMER_MISMATCH'

    store.create_pending('credit-review-1', 'sample.docx', '', admin, credit_case=credit_v1)
    report = {'filename': 'sample.docx', 'summary': {'n_clauses': 1, 'n_risks': len(findings), 'high': len(findings), 'mid': 0, 'low': 0, 'overall_level': '信审阻断'},
              'contract_fields': {}, 'masked_entities': 0, 'clauses': clauses, 'steps': [], 'risks': findings}
    store.save_review('credit-review-1', report, actor=admin)
    finding = store.list_findings('credit-review-1')[0]
    try:
        store.record_finding_action('credit-review-1', finding['finding_id'], 'ignore', '想在合同端放行', admin)
        raise AssertionError('信审越界不应允许在合同端忽略')
    except ValueError as exc:
        assert '信审越界' in str(exc)
    assert store.contract_credit_binding('credit-review-1')['version'] == 1

    # A commercial relaxation must produce a new credit version.  The old
    # contract binding becomes invalid and must be re-reviewed.
    credit_v2 = approved_credit(admin, days=60)
    assert credit_v2['version'] == 2
    try:
        store.contract_credit_binding('credit-review-1', require_current=True)
        raise AssertionError('旧信审版本不能在新版本生效后继续用于合同导出')
    except ValueError as exc:
        assert '尚未生效' in str(exc)
    print('OK: credit-first contract guard checks passed')


if __name__ == '__main__':
    main()
