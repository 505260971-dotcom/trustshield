"""Regression for Exa public-web due diligence and its credit-approval guard."""
import os
import sys
import tempfile
from unittest.mock import patch

from cryptography.fernet import Fernet

runtime = tempfile.mkdtemp(prefix='contractguard-exa-dd-')
os.environ.update({
    'CONTRACTGUARD_DATA_DIR': runtime,
    'AUTH_SECRET': 'external-due-diligence-test-secret',
    'DATA_ENCRYPTION_KEY': Fernet.generate_key().decode(),
    'INITIAL_ADMIN_USERNAME': 'admin',
    'INITIAL_ADMIN_PASSWORD': 'AdminPassword2026!',
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import store
from app.services import exa_mcp


def external_payload(url: str, title: str, text: str) -> dict:
    return {'content': [{'type': 'text', 'text': {
        'results': [{'url': url, 'title': title, 'text': text, 'publishedDate': '2026-07-01'}],
    }}]}


def report_for(case_id: str, external: dict) -> dict:
    conditions = {'max_credit_amount': 100_000, 'currency': 'CNY', 'max_payment_days': 30,
                  'min_prepayment_ratio': 60, 'allowed_payment_methods': ['bank_transfer'], 'allow_vmi_jit': False}
    return {
        'case_id': case_id, 'runtime_mode': 'production',
        'audit_runtime': {'status': 'ready_for_policy'}, 'external_due_diligence': external,
        'assessment': {'model_status': 'ready_for_reviewer', 'risk_flags': [], 'business_type': 'TKP',
                       'recommendation': conditions},
    }


def main():
    store.init_db()
    reviewer = store.create_user('reviewer', '信用审核专员', 'reviewer', 'ReviewerPassword2026!')
    store.create_user('director', '财务审批主管', 'director', 'DirectorPassword2026!')
    store.create_user('final', '集团财务总监', 'final_approver', 'FinalPassword2026!')
    conditions = {'max_credit_amount': 100_000, 'currency': 'CNY', 'max_payment_days': 30,
                  'min_prepayment_ratio': 60, 'allowed_payment_methods': ['bank_transfer'], 'allow_vmi_jit': False}
    case = store.create_credit_case('测试制造有限公司', conditions, 'Exa 外部尽调回归', reviewer, 'TKP', '91310000123456789X', '上海市')

    responses = iter([
        external_payload('https://court.example/case/1', '测试制造有限公司被执行案件公告', '公开执行信息：测试制造有限公司列为被执行人。'),
        external_payload('https://rating.example/report/1', '测试制造有限公司第三方信用报告', '公开第三方信用报告：评级展望稳定。'),
        external_payload('https://news.example/report/1', '测试制造有限公司近期经营新闻', '该企业近期经营情况报道。'),
    ])
    with patch.object(exa_mcp, '_search', side_effect=lambda _args: next(responses)):
        external = exa_mcp.run_external_due_diligence(case)
    assert external['status'] == 'review_required'
    assert external['identity_confidence'] == 'strong'
    assert len(external['sources']) == 3 and len(external['findings']) == 1
    assert {item['kind'] for item in external['queries']} == {'adverse', 'credit_profile', 'business'}
    assert {item['source_type'] for item in external['sources']} == {'adverse', 'credit_profile', 'business'}
    finding = external['findings'][0]
    assert finding['severity'] == 'high' and finding['status'] == 'pending_reviewer'

    task = store.start_credit_assessment(case['case_id'], reviewer)
    assessment = store.finish_credit_assessment(task['assessment_id'], report_for(case['case_id'], external), [])
    try:
        store.record_credit_reviewer_decision(case['case_id'], assessment, conditions, '', 'agent_recommended', reviewer)
        raise AssertionError('Exa 待核验线索不应允许直接采用 Agent 建议')
    except ValueError as exc:
        assert 'Exa' in str(exc)

    reviewed = store.record_credit_reviewer_decision(
        case['case_id'], assessment, conditions, '已核验公开执行信息，升级至最终审批。', 'manual_override', reviewer,
        'TKP', [{'finding_id': finding['finding_id'], 'decision': 'included', 'note': '主体代码与公开公告一致，纳入本次信审评判。'}],
    )
    assert reviewed['external_reviews'][0]['decision'] == 'included'
    submitted = store.submit_credit_case(case['case_id'], reviewer)
    assert submitted['status'] == 'approved'
    assert submitted['route_snapshot']['requires_final'] is False
    assert submitted['external_reviews'][0]['decision'] == 'included'

    excluded_case = store.create_credit_case('同名排除测试有限公司', conditions, 'Exa 排除线索回归', reviewer, 'TKP', '91310000987654321X', '上海市')
    excluded_task = store.start_credit_assessment(excluded_case['case_id'], reviewer)
    excluded_assessment = store.finish_credit_assessment(excluded_task['assessment_id'], report_for(excluded_case['case_id'], external), [])
    excluded = store.record_credit_reviewer_decision(
        excluded_case['case_id'], excluded_assessment, conditions, '', 'agent_recommended', reviewer, 'TKP',
        [{'finding_id': finding['finding_id'], 'decision': 'excluded', 'note': '统一社会信用代码与公开公告不一致，属于同名主体。'}],
    )
    assert excluded['review_mode'] == 'agent_recommended'
    assert store.submit_credit_case(excluded_case['case_id'], reviewer)['status'] == 'approved'

    with patch.object(exa_mcp, '_search', side_effect=exa_mcp.ExaMcpError("You've hit Exa's free MCP rate limit")):
        limited = exa_mcp.run_external_due_diligence(case)
    assert limited['status'] == 'rate_limited'
    print('Exa external due diligence and credit escalation checks passed')


if __name__ == '__main__':
    main()
