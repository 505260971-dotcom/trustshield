"""Regression for Agent recommendation, accountable reviewer changes and approval gating."""
import os
import sys
import tempfile

from cryptography.fernet import Fernet

runtime = tempfile.mkdtemp(prefix='contractguard-credit-reviewer-flow-')
os.environ.update({
    'CONTRACTGUARD_DATA_DIR': runtime,
    'AUTH_SECRET': 'unit-test-auth-secret-long-enough',
    'DATA_ENCRYPTION_KEY': Fernet.generate_key().decode(),
    'INITIAL_ADMIN_USERNAME': 'admin',
    'INITIAL_ADMIN_PASSWORD': 'AdminPassword2026!',
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import store


def conditions(limit=1_000_000, days=90):
    return {'max_credit_amount': limit, 'currency': 'CNY', 'max_payment_days': days,
            'min_prepayment_ratio': 20, 'allowed_payment_methods': ['bank_transfer'], 'allow_vmi_jit': False}


def ready_assessment(case_id, actor, proposed):
    task = store.start_credit_assessment(case_id, actor)
    return store.finish_credit_assessment(task['assessment_id'], {
        'runtime_mode': 'production', 'audit_runtime': {'status': 'ready_for_policy'},
        'assessment': {'model_status': 'ready_for_reviewer', 'risk_flags': [],
                       'business_type': 'TKP', 'recommendation': proposed},
    }, [])


def main():
    store.init_db()
    admin = store.authenticate('admin', 'AdminPassword2026!')
    reviewer = store.create_user('reviewer', '信用审核专员', 'reviewer', 'ReviewerPassword2026!')
    director = store.create_user('director', '财务审批主管', 'director', 'DirectorPassword2026!')
    business = store.create_user('business', '业务申请人', 'business', 'BusinessPassword2026!')

    case = store.create_credit_case('人工修订测试客户', conditions(), '测试人工修订', reviewer, 'TKP')
    try:
        store.submit_credit_case(case['case_id'], reviewer)
        raise AssertionError('没有评估依据的草稿不得报送')
    except ValueError as exc:
        assert 'Agent/模型建议' in str(exc)

    assessment = ready_assessment(case['case_id'], reviewer, conditions(1_000_000, 90))
    final_terms = conditions(800_000, 60)
    reviewed = store.record_credit_reviewer_decision(
        case['case_id'], assessment, final_terms,
        '新客户首年合作，采用更保守的额度和账期。', 'reviewer_adjusted', reviewer, 'TKP')
    assert reviewed['review_mode'] == 'reviewer_adjusted'
    assert reviewed['conditions']['max_credit_amount'] == 800_000
    assert reviewed['assessment_snapshot']['recommendation']['max_credit_amount'] == 1_000_000
    store.submit_credit_case(case['case_id'], reviewer)
    returned = store.decide_credit_case(case['case_id'], 'returned_to_reviewer', '请补充额度调整的回款证据。', director)
    assert returned['status'] == 'returned_to_reviewer'
    assert returned['return_target'] == 'reviewer'
    assert '回款证据' in returned['return_note']
    assert any(item['source_type'] == 'credit' and item['case_id'] == case['case_id'] for item in store.my_work_items(reviewer))
    store.record_credit_reviewer_decision(case['case_id'], assessment, final_terms, '已补充客户回款记录并维持保守条件。', 'reviewer_adjusted', reviewer, 'TKP')
    store.submit_credit_case(case['case_id'], reviewer)
    assert store.decide_credit_case(case['case_id'], 'approved', '复核通过', director)['status'] == 'pending_final'
    assert store.decide_credit_case(case['case_id'], 'approved', '最终批准', admin)['status'] == 'approved'

    # Published credit-route versions control whether a supervisor decision
    # ends the case or must be escalated.  The route snapshot stays on the
    # case, so a later policy publication cannot rewrite this decision path.
    route = store.create_credit_route_draft(admin)
    direct_config = {**route['config'], 'final_threshold_amount': 10_000_000, 'final_threshold_payment_days': 365,
                     'final_threshold_prepayment_ratio': 0, 'final_on_manual_override': False,
                     'final_on_acceptance_bill': False, 'final_on_vmi_jit': False}
    store.update_credit_route_version(route['version'], direct_config, admin)
    published_route = store.publish_credit_route_version(route['version'], admin)
    direct_case = store.create_credit_case('主管结案路由测试客户', conditions(500_000, 30), '测试可由主管结案的路由', reviewer, 'TKP')
    direct_assessment = ready_assessment(direct_case['case_id'], reviewer, conditions(500_000, 30))
    store.record_credit_reviewer_decision(direct_case['case_id'], direct_assessment, conditions(500_000, 30), '', 'agent_recommended', reviewer, 'TKP')
    submitted_direct = store.submit_credit_case(direct_case['case_id'], reviewer)
    assert submitted_direct['route_snapshot']['version'] == published_route['version']
    assert submitted_direct['route_snapshot']['requires_final'] is False
    assert store.decide_credit_case(direct_case['case_id'], 'approved', '主管按路由批准', director)['status'] == 'approved'

    material_case = store.create_credit_case('补材料闭环测试客户', conditions(), '业务申请补材料闭环', business, 'TKP')
    material_assessment = ready_assessment(material_case['case_id'], reviewer, conditions())
    store.record_credit_reviewer_decision(material_case['case_id'], material_assessment, conditions(), '', 'agent_recommended', reviewer, 'TKP')
    store.submit_credit_case(material_case['case_id'], reviewer)
    returned = store.decide_credit_case(material_case['case_id'], 'returned_to_business', '请补充最近一期财报和第三方信用报告。', director)
    assert returned['status'] == 'returned_to_business'
    assert any(item['source_type'] == 'credit' and item['case_id'] == material_case['case_id'] for item in store.my_work_items(business))
    resubmitted = store.resubmit_credit_case(material_case['case_id'], business)
    assert resubmitted['status'] == 'draft'

    fallback = store.create_credit_case('Agent异常测试客户', conditions(), '测试人工兜底', reviewer, 'TKP')
    failed_task = store.start_credit_assessment(fallback['case_id'], reviewer)
    failed = store.finish_credit_assessment(failed_task['assessment_id'], None, [], 'Agent unavailable')
    fallback = store.record_credit_reviewer_decision(
        fallback['case_id'], failed, conditions(300_000, 30),
        'Agent 服务异常；已依据客户盖章财报及线下回款记录人工核验。', 'manual_override', reviewer, 'TKP')
    assert fallback['review_mode'] == 'manual_override'
    assert fallback['assessment_snapshot']['assessment_status'] == 'error'
    store.submit_credit_case(fallback['case_id'], reviewer)
    print('credit reviewer recommendation, adjustment and fallback gates passed')


if __name__ == '__main__':
    main()
