"""HTTP regression for administrator user CRUD and account safety guardrails."""
import os
import sys
import tempfile

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

runtime = tempfile.mkdtemp(prefix='contractguard-admin-users-')
os.environ.update({
    'CONTRACTGUARD_DATA_DIR': runtime,
    'AUTH_SECRET': 'admin-user-test-auth-secret',
    'DATA_ENCRYPTION_KEY': Fernet.generate_key().decode(),
    'INITIAL_ADMIN_USERNAME': 'admin',
    'INITIAL_ADMIN_PASSWORD': 'AdminPassword2026!',
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.main import app


def login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def main():
    with TestClient(app) as client:
        admin = login(client, 'admin', 'AdminPassword2026!')
        me = client.get('/api/auth/me', headers=admin)
        assert me.status_code == 200 and '*' not in me.json()['permissions']
        assert 'admin:users' in me.json()['permissions'] and 'credit:create' not in me.json()['permissions']
        # A system administrator can manage identities but is not a business
        # approver or credit-case creator.
        assert client.post('/api/credit/cases', headers=admin, json={'customer_name': '越权拦截测试'}).status_code == 403
        for username, display_name, role, password in [
            ('rule_reviewer', '风险条款起草专员', 'reviewer', 'ReviewerPass2026!'),
            ('rule_director', '风险条款发布主管', 'director', 'DirectorPass2026!'),
            ('final_approver', '集团财务总监', 'final_approver', 'FinalPass2026!'),
        ]:
            created_role = client.post('/api/admin/users', headers=admin, json={
                'username': username, 'display_name': display_name, 'role': role, 'password': password,
            })
            assert created_role.status_code == 200, created_role.text
        reviewer_headers = login(client, 'rule_reviewer', 'ReviewerPass2026!')
        director_headers = login(client, 'rule_director', 'DirectorPass2026!')
        final_headers = login(client, 'final_approver', 'FinalPass2026!')
        draft = client.post('/api/admin/rule-versions', headers=reviewer_headers)
        assert draft.status_code == 200, draft.text
        assert client.post('/api/admin/rule-versions/' + draft.json()['version'] + '/publish', headers=director_headers).status_code == 200
        assert client.post('/api/admin/rule-versions', headers=final_headers).status_code == 403
        assert client.get('/api/admin/credit-route-versions', headers=final_headers).status_code == 403
        created = client.post('/api/admin/users', headers=admin, json={
            'username': 'risk_reviewer', 'display_name': '风险审核专员',
            'role': 'reviewer', 'password': 'ReviewerPass2026!',
        })
        assert created.status_code == 200, created.text
        reviewer = created.json()
        assert reviewer['role'] == 'reviewer'

        changed = client.patch('/api/admin/users/' + reviewer['id'], headers=admin, json={
            'display_name': '信用审核专员', 'role': 'director', 'active': True,
            'password': 'DirectorPass2026!',
        })
        assert changed.status_code == 200, changed.text
        assert changed.json()['role'] == 'director'
        login(client, 'risk_reviewer', 'DirectorPass2026!')

        deleted = client.delete('/api/admin/users/' + reviewer['id'], headers=admin)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()['deleted'] is True
        denied_login = client.post('/api/auth/login', json={'username': 'risk_reviewer', 'password': 'DirectorPass2026!'})
        assert denied_login.status_code == 401

        admin_id = client.get('/api/auth/me', headers=admin).json()['user']['id']
        assert client.delete('/api/admin/users/' + admin_id, headers=admin).status_code == 400
        assert client.patch('/api/admin/users/' + admin_id, headers=admin, json={'role': 'reviewer'}).status_code == 400
    print('role split, rule dual-control, administrator CRUD and account safeguards passed')


if __name__ == '__main__':
    main()
