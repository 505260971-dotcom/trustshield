"""No-network workflow test for RBAC, encrypted persistence and human actions.

Run with: python scripts/test_security_workflow.py
It uses a temporary SQLite database and never invokes an LLM.
"""
import os, sys, tempfile
from cryptography.fernet import Fernet

tmp=tempfile.mkdtemp(prefix='contractguard-test-')
os.environ.update({
    'CONTRACTGUARD_DATA_DIR':tmp,
    'AUTH_SECRET':'unit-test-auth-secret-long-enough',
    'DATA_ENCRYPTION_KEY':Fernet.generate_key().decode(),
    'INITIAL_ADMIN_USERNAME':'admin',
    'INITIAL_ADMIN_PASSWORD':'AdminPassword2026!',
})
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'..'))
from app import store
from app.services.security import decrypt_json, issue_token

store.init_db()
admin=store.authenticate('admin','AdminPassword2026!')
assert admin and admin['role']=='admin' and issue_token(admin)
reviewer = store.create_user('reviewer', '信用审核专员', 'reviewer', 'ReviewerPassword2026!')
director = store.create_user('director', '财务审批主管', 'director', 'DirectorPassword2026!')
credit = store.create_credit_case('测试客户', {'max_credit_amount': 1000000, 'max_payment_days': 60, 'min_prepayment_ratio': 30, 'allowed_payment_methods': ['bank_transfer']}, '单元测试信审', reviewer)
assessment_task = store.start_credit_assessment(credit['case_id'], reviewer)
assessment = store.finish_credit_assessment(assessment_task['assessment_id'], {
    'runtime_mode': 'production', 'audit_runtime': {'status': 'ready_for_policy'},
    'assessment': {'model_status': 'ready_for_reviewer', 'risk_flags': [], 'business_type': '一般', 'recommendation': credit['conditions']},
}, [])
credit = store.record_credit_reviewer_decision(credit['case_id'], assessment, credit['conditions'], '', 'agent_recommended', reviewer)
store.submit_credit_case(credit['case_id'], reviewer)
credit = store.decide_credit_case(credit['case_id'], 'approved', '主管复核', director)
assert credit['status'] == 'pending_final'
credit = store.decide_credit_case(credit['case_id'], 'approved', '最终批核', admin)
store.create_pending('review-1','sample.docx','',admin, credit_case=credit)
report={'filename':'sample.docx','summary':{'n_clauses':1,'n_risks':1,'high':1,'mid':0,'low':0,'overall_level':'阻断'},
        'contract_fields':{},'masked_entities':1,'clauses':[],'steps':[],
        'risks':[{'clause_id':'C1','page':1,'rule_id':'R04','rule_baseline':'no joint liability','severity':'high','level':'阻断','evidence':'e','numeric_note':'','suggestion':'s','decision_source':'test'}]}
store.save_review('review-1',report,actor=admin,mapping={'<MASK-COMPANY-1>':'Sensitive Co.'})
row=store.get_review('review-1'); assert row['report']['filename']=='sample.docx'
finding=store.list_findings('review-1')[0]
updated=store.record_finding_action('review-1',finding['finding_id'],'adopt','unit-test',admin)
assert updated['action_status']=='adopted'
print('security workflow checks passed')
