"""Full HTTP acceptance test for quantitative credit -> contract control.

The fixture is intentionally fictional and de-identified.  This test does not
need a remote LLM: the graph uses its deterministic fallback and still verifies
the published credit snapshot plus the downstream exposure block.
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
        response = client.get(f'/api/jobs/{job_id}', headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        if body['status'] != 'running':
            return body
        time.sleep(.15)
    raise AssertionError('合同审查超时')


def main():
    assert FIXTURE.is_file(), f'缺少测试样本: {FIXTURE}'
    with TestClient(app) as client:
        # The application seeds admin at startup; create the required second
        # approval role directly in this isolated test database.
        store.create_user('director', '财务审批主管', 'director', 'DirectorPassword2026!')
        admin = _login(client, 'admin', 'AdminPassword2026!')
        director = _login(client, 'director', 'DirectorPassword2026!')

        created = client.post('/api/credit/cases', headers=admin, json={
            'customer_name': '测试制造客户（脱敏）', 'business_type': 'TKP', 'request_note': '端到端验收',
            'conditions': {
                'max_credit_amount': 1_000_000, 'currency': 'CNY', 'max_payment_days': 120,
                'min_prepayment_ratio': 20, 'allowed_payment_methods': ['bank_transfer'], 'allow_vmi_jit': False,
            },
        })
        assert created.status_code == 200, created.text
        case_id = created.json()['case_id']

        uploaded = client.post(f'/api/credit/cases/{case_id}/documents', headers=admin,
                               data={'document_type': 'financial_report'},
                               files={'file': (FIXTURE.name, FIXTURE.read_bytes(), 'text/plain')})
        assert uploaded.status_code == 200, uploaded.text
        exposure = client.post(f'/api/credit/cases/{case_id}/exposure', headers=admin, json={
            'source': 'crm_mock', 'current_receivables': 100_000, 'booked_order_amount': 200_000,
            'overdue_amount': 0, 'overdue_days': 0, 'currency': 'CNY',
        })
        assert exposure.status_code == 200, exposure.text

        started = client.post(f'/api/credit/cases/{case_id}/assessments', headers=admin, json={})
        assert started.status_code == 200, started.text
        assessment_id = started.json()['assessment_id']
        assessment_status = _wait_credit(client, admin, case_id, assessment_id)
        assert assessment_status['status'] == 'done', assessment_status
        assessment = client.get(f'/api/credit/cases/{case_id}/assessments/latest', headers=admin)
        assert assessment.status_code == 200, assessment.text
        report = assessment.json()['report']
        assert report['assessment']['credit_grade'] == 'A', report
        assert report['assessment']['recommendation']['max_payment_days'] == 90, report

        applied = client.post(f'/api/credit/cases/{case_id}/assessments/{assessment_id}/apply', headers=admin)
        assert applied.status_code == 200, applied.text
        assert applied.json()['conditions']['max_payment_days'] == 90
        submitted = client.post(f'/api/credit/cases/{case_id}/submit', headers=admin)
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()['status'] == 'pending_director'
        reviewed = client.post(f'/api/credit/cases/{case_id}/decision', headers=director, json={'decision': 'approved', 'note': '主管复核通过'})
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()['status'] == 'pending_final'
        approved = client.post(f'/api/credit/cases/{case_id}/decision', headers=admin, json={'decision': 'approved', 'note': '最终批核通过'})
        assert approved.status_code == 200, approved.text
        assert approved.json()['status'] == 'approved'

        # Existing exposure (300k) plus this contract (900k) exceeds the
        # approved 1m limit.  The downstream contract workflow must preserve
        # the CREDIT_EXPOSURE blocker even though the credit version is valid.
        contract = '甲方：测试制造客户（脱敏）\n乙方：东江集团\n合同金额 900000 元，交付前支付20%预付款，货物交付后30天付款。'
        review = client.post('/api/review', headers=admin, data={'business_type': 'TKP', 'credit_case_id': case_id},
                             files={'file': ('credit_exposure_contract.txt', contract.encode('utf-8'), 'text/plain')})
        assert review.status_code == 200, review.text
        job = _wait_review(client, admin, review.json()['job_id'])
        assert job['status'] == 'done', job
        history = client.get(f"/api/history/{review.json()['job_id']}", headers=admin)
        assert history.status_code == 200, history.text
        risk_ids = {item['rule_id'] for item in history.json()['report']['risks']}
        assert 'CREDIT_EXPOSURE' in risk_ids, risk_ids
        print('OK: full credit assessment, approval, and contract-exposure workflow passed')


if __name__ == '__main__':
    main()
