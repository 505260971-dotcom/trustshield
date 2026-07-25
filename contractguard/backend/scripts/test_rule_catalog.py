"""No-network regression for versioned, publish-gated rule catalog behavior."""
import os
import sys
import tempfile
from cryptography.fernet import Fernet

tmp = tempfile.mkdtemp(prefix='contractguard-rules-')
os.environ.update({
    'CONTRACTGUARD_DATA_DIR': tmp,
    'AUTH_SECRET': 'unit-test-auth-secret-long-enough',
    'DATA_ENCRYPTION_KEY': Fernet.generate_key().decode(),
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app import store


def main():
    actor = {'id': 'admin-test', 'role': 'admin'}
    store.init_db()
    initial = store.get_rule_version()
    assert initial['version'] == 'contract-v1' and len(initial['rules']) == 16
    draft = store.create_rule_draft(actor)
    assert draft['version'] == 'contract-v2'
    updated = store.update_rule_definition(draft['version'], 'R06', {
        'template': '客户取消订单须赔偿已发生且不可转移的全部成本。',
        'applies_to': ['全部'], 'severity': 'high',
    }, actor)
    assert next(rule for rule in updated['rules'] if rule['id'] == 'R06')['severity'] == 'high'
    published = store.publish_rule_version(draft['version'], actor)
    assert published['version'] == 'contract-v2'
    assert store.get_rule_version()['version'] == 'contract-v2'
    try:
        store.update_rule_definition('contract-v2', 'R06', {'template': 'should fail'}, actor)
    except ValueError:
        pass
    else:
        raise AssertionError('published version must be immutable')
    print('rule catalog versioning checks passed')


if __name__ == '__main__':
    main()
