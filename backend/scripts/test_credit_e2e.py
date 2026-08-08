"""Full HTTP acceptance test for quantitative credit -> contract control.

The fixture is intentionally fictional and de-identified.  This test does not
need a remote LLM: it verifies that the production API fails closed rather than
using a deterministic extraction fallback.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

from cryptography.fernet import Fernet

runtime = tempfile.mkdtemp(prefix='contractguard-credit-e2e-')
os.environ.update({
    'CONTRACTGUARD_DATA_DIR': runtime,
    'AUTH_SECRET': 'e2e-test-auth-secret-long-enough',
    'DATA_ENCRYPTION_KEY': Fernet.generate_key().decode(),
    'INITIAL_ADMIN_USERNAME': 'admin',
    'INITIAL_ADMIN_PASSWORD': 'AdminPassword2026!',
    # Preserve the local deterministic route in a CI/dev environment.
    'LLM_API_BASE': '', 'LLM_API_KEY': '', 'LLM_MODEL': '',
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi.testclient import TestClient
from app import store
from app.main import app

FIXTURE = Path(__file__).parent / 'fixtures' / 'credit_customer_financial_sample.txt'


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def _wait_credit(client: TestClient, headers: dict[str, str], case_id: str, assessment_id: str) -> dict:
    for _ in range(60):
        response = client.get(f'/api/credit/cases/{case_id}/assessments/{assessment_id}/status', headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        if body['status'] != 'running':
            return body
        time.sleep(.15)
    raise AssertionError('量化信审评估超时')


def _wait_review(client: TestClient, headers: dict[str, str], job_id: str) -> dict:
    for _ in range(80):
        response = client.get(f'/api/reviews/{job_id}/status', headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        if body['status'] != 'running':
            return body
        time.sleep(.15)
    raise AssertionError('合同审查超时')


def main():
    assert FIXTURE.is_file(), f'缺少测试样本: {FIXTURE}'
    with TestClient(app) as client:
        # The application seeds a system administrator at startup.  Business
        # credit operations are executed by the dedicated reviewer role.
        store.create_user('reviewer', '信用审核专员', 'reviewer', 'ReviewerPassword2026!')
        store.create_user('director', '财务审批主管', 'director', 'DirectorPassword2026!')
        store.create_user('final', '集团财务总监', 'final_approver', 'FinalPassword2026!')
        admin = _login(client, 'admin', 'AdminPassword2026!')
        reviewer = _login(client, 'reviewer', 'ReviewerPassword2026!')
        director = _login(client, 'director', 'DirectorPassword2026!')

        created = client.post('/api/credit/cases', headers=reviewer, json={
            'customer_name': '测试制造客户（脱敏）', 'business_type': 'TKP', 'request_note': '端到端验收',
            'conditions': {
                'max_credit_amount': 1_000_000, 'currency': 'CNY', 'max_payment_days': 120,
                'min_prepayment_ratio': 20, 'allowed_payment_methods': ['bank_transfer'], 'allow_vmi_jit': False,
            },
        })
        assert created.status_code == 200, created.text
        case_id = created.json()['case_id']

        uploaded = client.post(f'/api/credit/cases/{case_id}/documents', headers=reviewer,
                               data={'document_type': 'financial_report'},
                               files={'file': (FIXTURE.name, FIXTURE.read_bytes(), 'text/plain')})
        assert uploaded.status_code == 200, uploaded.text
        exposure = client.post(f'/api/credit/cases/{case_id}/exposure', headers=reviewer, json={
            'source': 'crm_mock', 'current_receivables': 100_000, 'booked_order_amount': 200_000,
            'overdue_amount': 0, 'overdue_days': 0, 'currency': 'CNY',
        })
        assert exposure.status_code == 200, exposure.text

        started = client.post(f'/api/credit/cases/{case_id}/assessments', headers=reviewer, json={})
        assert started.status_code == 200, started.text
        assessment_id = started.json()['assessment_id']
        assessment_status = _wait_credit(client, reviewer, case_id, assessment_id)
        assert assessment_status['status'] == 'done', assessment_status
        assessment = client.get(f'/api/credit/cases/{case_id}/assessments/latest', headers=reviewer)
        assert assessment.status_code == 200, assessment.text
        report = assessment.json()['report']
        assert report['runtime_mode'] == 'production', report
        assert report['assessment']['credit_grade'] == 'UNASSESSABLE', report
        assert report['assessment']['recommendation']['max_credit_amount'] == 0, report

        applied = client.post(f'/api/credit/cases/{case_id}/assessments/{assessment_id}/apply', headers=reviewer)
        # Without a real Agent/reranker, production must fail closed and must
        # never create a credit version or enter the contract workflow.
        assert applied.status_code == 409, applied.text
        assert ('材料缺失或高风险阻断' in applied.json()['detail']
                or 'Exa 公开尽调' in applied.json()['detail'])
        print('OK: production credit assessment fails closed without Agent/reranker')


if __name__ == '__main__':
    main()
