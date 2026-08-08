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


def approved_credit(reviewer, director, cfo, days=45):
    item = store.create_credit_case('测试客户甲', {
        'max_credit_amount': 100000,
        'currency': 'CNY',
        'max_payment_days': days,
        'min_prepayment_ratio': 30,
        'allowed_payment_methods': ['bank_transfer'],
        'allow_vmi_jit': False,
    }, '回归测试信审', reviewer)
    # A credit version needs an attributable production assessment basis before
    # the credit reviewer can make it effective.
    task = store.start_credit_assessment(item['case_id'], reviewer)
    report = {
        'runtime_mode': 'production', 'audit_runtime': {'status': 'ready_for_policy'},
        'assessment': {'model_status': 'ready_for_reviewer', 'risk_flags': [],
                       'business_type': '一般', 'recommendation': item['conditions']},
        'external_due_diligence': {'status': 'review_required', 'findings': [{
            'finding_id': 'EXA-CONTRACT-GUARD', 'code': 'EXTERNAL_ADVERSE_LEAD', 'severity': 'mid',
            'title': '公开合同纠纷线索', 'summary': '用于验证合同审批可见性。',
            'source': {'url': 'https://example.test/external-risk'},
        }]},
    }
    assessment = store.finish_credit_assessment(task['assessment_id'], report, [])
    item = store.record_credit_reviewer_decision(item['case_id'], assessment, item['conditions'], '', 'agent_recommended', reviewer,
                                                 external_decisions=[{'finding_id': 'EXA-CONTRACT-GUARD', 'decision': 'included',
                                                                      'note': '主体和案件事实已核验，纳入本次信用判断。'}])
    approved = store.submit_credit_case(item['case_id'], reviewer)
    assert approved['status'] == 'approved'
    return approved


def main():
    store.init_db()
    admin = store.authenticate('admin', 'AdminPassword2026!')
    reviewer = store.create_user('reviewer', '信用审核专员', 'reviewer', 'ReviewerPassword2026!')
    director = store.create_user('director', '财务审批主管', 'director', 'DirectorPassword2026!')
    final = store.create_user('final', '集团财务总监', 'final_approver', 'FinalPassword2026!')
    business = store.create_user('business', '业务申请人', 'business', 'BusinessPassword2026!')
    credit_v1 = approved_credit(reviewer, director, final)
    assert store.require_active_credit_case(credit_v1['case_id'])['version'] == 1

    clauses = [{'id': 'C1', 'text': '货物交付后60天付款，交付前支付20%预付款，付款方式为银行承兑汇票，并采用VMI模式。'}]
    findings = assess_credit_compliance(clauses, credit_v1['conditions'])
    assert {item['rule_id'] for item in findings} == {'CREDIT_TERM', 'CREDIT_PREPAYMENT', 'CREDIT_PAYMENT_METHOD', 'CREDIT_DELIVERY_MODE'}
    assert assess_customer_binding({'our_party': '乙方', 'parties': {'甲方': '测试客户甲有限公司'}}, '测试客户甲') == []
    assert assess_customer_binding({'our_party': '乙方', 'parties': {'甲方': '另一家客户'}}, '测试客户甲')[0]['rule_id'] == 'CREDIT_CUSTOMER_MISMATCH'
    negated = assess_credit_compliance([{'id': 'C2', 'text': '双方采用普通送货方式，不采用 VMI、JIT、供应商管理库存或准时制交付模式。'}], credit_v1['conditions'])
    assert 'CREDIT_DELIVERY_MODE' not in {item['rule_id'] for item in negated}, '明确禁止 VMI/JIT 不应触发信审阻断'

    contract = store.create_case_center('测试客户甲', '一般', '合同回归测试', business, credit_v1['case_id'])
    store.create_pending('credit-review-1', 'sample.docx', '', business, credit_case=credit_v1, case_id=contract['case_id'])
    bound_snapshot = store.contract_credit_binding('credit-review-1')
    assert bound_snapshot['external_reviews'][0]['title'] == '公开合同纠纷线索'
    assert bound_snapshot['external_reviews'][0]['decision'] == 'included'
    # A durable but unbound draft can be safely recovered at upload time only
    # with an approved credit case for the very same customer.
    recovered = store.create_case_center('测试客户甲', '一般', '上传重试回归测试', business)
    rebound = store.bind_case_center_credit(recovered['case_id'], credit_v1['case_id'], business)
    assert rebound['case_id'] == credit_v1['case_id']
    assert store.get_case_center(recovered['case_id'], business)['credit_case_id'] == credit_v1['case_id']
    report = {'filename': 'sample.docx', 'summary': {'n_clauses': 1, 'n_risks': len(findings), 'high': len(findings), 'mid': 0, 'low': 0, 'overall_level': '信审阻断'},
              'contract_fields': {}, 'masked_entities': 0, 'clauses': clauses, 'steps': [], 'risks': findings}
    store.save_review('credit-review-1', report, actor=reviewer)
    finding = store.list_findings('credit-review-1')[0]
    try:
        store.record_finding_action('credit-review-1', finding['finding_id'], 'ignore', '想在合同端放行', reviewer)
        raise AssertionError('不符合信用审核条件的问题不应允许在合同端忽略')
    except ValueError as exc:
        assert '不符合信用审核条件' in str(exc)
    assert store.contract_credit_binding('credit-review-1')['version'] == 1
    # The same credit package is not approved a second time.  It is visible in
    # contract review; the later contract approver can reject the contract
    # itself with a reason if the package is not acceptable.
    submitted_contract = store.transition_case(contract['case_id'], 'submit_approval', reviewer, '已核对合同与已纳入外部公开信息。')
    assert submitted_contract['current_stage'] == 'approval'
    rejected_contract = store.transition_case(contract['case_id'], 'reject', director, '合同风险与本次商业安排不匹配，驳回。')
    assert rejected_contract['current_stage'] == 'cancelled'

    # A commercial relaxation must produce a new credit version.  The old
    # contract binding becomes invalid and must be re-reviewed.
    credit_v2 = approved_credit(reviewer, director, final, days=60)
    assert credit_v2['version'] == 2
    try:
        store.contract_credit_binding('credit-review-1', require_current=True)
        raise AssertionError('旧信审版本不能在新版本生效后继续用于合同导出')
    except ValueError as exc:
        assert '尚未生效' in str(exc)
    # 页面预检：案件详情应能提前看到“绑定版本已不是当前生效版本”，
    # 而不是等到导出时才由后端报错。
    case_center = store.get_case_center(contract['case_id'], business)
    binding = case_center['credit_binding']
    assert binding is not None and binding['version'] == 1 and binding['stale'] is True
    assert any('不再生效' in reason or 'V2' in reason for reason in binding['reasons'])

    # TKM（模具制作）三段式字段与合规检查：走模后尾款放账比例/信用期独立
    # 约束；首期款采购豁免时不再要求交付前最低收款比例；TKP 不启用这些字段。
    from app.services.credit import normalize_conditions
    tkm_conditions = normalize_conditions({**credit_v1['conditions'],
                                           'first_payment_exempt': False, 'tail_payment_ratio': 40, 'tail_payment_days': 30})
    assert tkm_conditions['tail_payment_ratio'] == 40 and tkm_conditions['tail_payment_days'] == 30
    assert tkm_conditions['first_payment_exempt'] is False
    tail_ratio = assess_credit_compliance([{'id': 'T1', 'text': '模具交付前支付60%，走模后支付尾款50%。'}], tkm_conditions, None, 'TKM')
    assert {item['rule_id'] for item in tail_ratio} == {'CREDIT_TAIL_PAYMENT_RATIO'}
    tail_term = assess_credit_compliance([{'id': 'T2', 'text': '走模后60天付清尾款。'}], tkm_conditions, None, 'TKM')
    assert 'CREDIT_TAIL_PAYMENT_TERM' in {item['rule_id'] for item in tail_term}
    tkm_exempt = dict(tkm_conditions); tkm_exempt['first_payment_exempt'] = True
    exempt = assess_credit_compliance([{'id': 'T3', 'text': '双方约定交货后30天内付款。'}], tkm_exempt, None, 'TKM')
    assert {item['rule_id'] for item in exempt} == set(), '首期款采购豁免后不应再要求交付前最低收款比例'
    non_exempt = assess_credit_compliance([{'id': 'T5', 'text': '双方约定交货后30天内付款。'}], tkm_conditions, None, 'TKM')
    assert 'CREDIT_PREPAYMENT' in {item['rule_id'] for item in non_exempt}
    tkp_ignored = assess_credit_compliance([{'id': 'T4', 'text': '走模后支付尾款50%。'}], tkm_conditions, None, 'TKP')
    assert 'CREDIT_TAIL_PAYMENT_RATIO' not in {item['rule_id'] for item in tkp_ignored}, 'TKP 不适用 TKM 尾款规则'
    print('OK: credit-first contract guard checks passed')


if __name__ == '__main__':
    main()
