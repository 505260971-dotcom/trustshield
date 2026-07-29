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
    print('administrator user CRUD, password reset and deletion safeguards passed')


if __name__ == '__main__':
    main()
