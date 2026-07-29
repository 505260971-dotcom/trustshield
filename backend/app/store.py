"""SQLite repository for the single-node contract review workspace."""
from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import threading
import time
import uuid
from typing import Any

from .config import DATA_DIR, DATA_ENCRYPTION_KEY, INITIAL_ADMIN_NAME, INITIAL_ADMIN_PASSWORD, INITIAL_ADMIN_USERNAME
from .services.security import ROLES, decrypt_json, encrypt_json, password_hash, verify_password

DB_PATH = os.path.join(DATA_DIR, 'contractguard.db')
_lock = threading.Lock()

def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _columns(c, table: str) -> set[str]:
    return {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}

def _add_column(c, table: str, definition: str):
    name = definition.split()[0]
    if name not in _columns(c, table): c.execute(f'ALTER TABLE {table} ADD COLUMN {definition}')

def init_db():
    with _lock, _conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS reviews (
          id TEXT PRIMARY KEY, filename TEXT, status TEXT, created_at REAL, finished_at REAL,
          overall_level TEXT, n_clauses INTEGER, n_risks INTEGER, high INTEGER, mid INTEGER, low INTEGER,
          masked_entities INTEGER, our_party TEXT, business_type TEXT, report_encrypted BLOB, file_path TEXT
        );
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
          role TEXT NOT NULL, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS contract_cases (
          case_id TEXT PRIMARY KEY, job_id TEXT UNIQUE, business_type TEXT,
          status TEXT NOT NULL, created_by TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
          assigned_to TEXT, priority TEXT NOT NULL DEFAULT 'normal', due_at REAL, request_note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS review_findings (
          finding_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, clause_id TEXT, page INTEGER, rule_id TEXT,
          rule_version TEXT NOT NULL DEFAULT 'contract-v1', severity TEXT, level TEXT, baseline TEXT,
          evidence TEXT, numeric_note TEXT, suggestion TEXT, decision_source TEXT,
          action_status TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS review_actions (
          action_id TEXT PRIMARY KEY, finding_id TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
          edited_suggestion TEXT, actor_id TEXT NOT NULL, actor_role TEXT NOT NULL, created_at REAL NOT NULL,
          FOREIGN KEY(finding_id) REFERENCES review_findings(finding_id)
        );
        CREATE TABLE IF NOT EXISTS mask_mappings (
          task_id TEXT PRIMARY KEY, encrypted_mapping BLOB NOT NULL, expires_at REAL NOT NULL,
          created_by TEXT, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
          event_id TEXT PRIMARY KEY, actor_id TEXT, actor_role TEXT, action TEXT NOT NULL,
          resource_type TEXT, resource_id TEXT, metadata_json TEXT NOT NULL DEFAULT '{}', ip TEXT, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS finding_approvals (
          approval_id TEXT PRIMARY KEY, finding_id TEXT NOT NULL, job_id TEXT NOT NULL,
          required_role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          decision_note TEXT NOT NULL DEFAULT '', actor_id TEXT, created_at REAL NOT NULL, decided_at REAL
        );
        CREATE TABLE IF NOT EXISTS material_requests (
          request_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, finding_id TEXT, title TEXT NOT NULL,
          detail TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', requested_by TEXT, resolved_by TEXT,
          created_at REAL NOT NULL, resolved_at REAL
        );
        CREATE TABLE IF NOT EXISTS material_files (
          file_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, job_id TEXT NOT NULL,
          original_name TEXT NOT NULL, stored_path TEXT NOT NULL, uploaded_by TEXT,
          created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS contract_versions (
          job_id TEXT PRIMARY KEY, parent_job_id TEXT, version_label TEXT NOT NULL DEFAULT 'V1',
          compare_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clause_knowledge (
          case_id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, business_type TEXT, source_clause TEXT NOT NULL,
          source_ref TEXT, evidence TEXT, suggested_text TEXT, outcome TEXT NOT NULL, created_by TEXT, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS export_snapshots (
          export_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, mode TEXT NOT NULL, output_path TEXT NOT NULL,
          approvals_json TEXT NOT NULL, findings_json TEXT NOT NULL, exported_by TEXT, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rule_versions (
          version TEXT PRIMARY KEY, status TEXT NOT NULL, created_by TEXT, created_at REAL NOT NULL, published_at REAL
        );
        CREATE TABLE IF NOT EXISTS rule_definitions (
          version TEXT NOT NULL, rule_id TEXT NOT NULL, dim TEXT NOT NULL, baseline TEXT NOT NULL, rule_check TEXT NOT NULL,
          severity TEXT NOT NULL, applies_json TEXT NOT NULL, approval_role TEXT NOT NULL DEFAULT '', template TEXT NOT NULL DEFAULT '',
          updated_by TEXT, updated_at REAL NOT NULL, PRIMARY KEY(version, rule_id)
        );
        CREATE TABLE IF NOT EXISTS credit_cases (
          case_id TEXT PRIMARY KEY, customer_key TEXT NOT NULL, customer_name TEXT NOT NULL,
          version INTEGER NOT NULL, status TEXT NOT NULL, conditions_json TEXT NOT NULL,
          request_note TEXT NOT NULL DEFAULT '', decision_note TEXT NOT NULL DEFAULT '',
          created_by TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
          submitted_at REAL, decided_by TEXT, decided_at REAL,
          UNIQUE(customer_key, version)
        );
        /* Credit-assessment artifacts are deliberately separate from the
           approved commercial snapshot in credit_cases.  An assessment is a
           recommendation with its evidence; it never becomes effective until
           the existing approval workflow publishes the case version. */
        CREATE TABLE IF NOT EXISTS credit_documents (
          document_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, document_type TEXT NOT NULL,
          original_name TEXT NOT NULL, stored_path TEXT NOT NULL, content_hash TEXT NOT NULL,
          uploaded_by TEXT, created_at REAL NOT NULL
        );
        /* Source documents stay on disk unchanged.  Their normalized text,
           table rows and OCR records are encrypted separately so retrieval is
           reproducible without turning the original into an editable artifact. */
        CREATE TABLE IF NOT EXISTS credit_document_text_assets (
          document_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, parser_version TEXT NOT NULL,
          status TEXT NOT NULL, records_encrypted BLOB, error TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS credit_exposure_snapshots (
          snapshot_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, source TEXT NOT NULL,
          payload_encrypted BLOB NOT NULL, captured_at REAL NOT NULL, created_by TEXT,
          created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS credit_model_versions (
          version TEXT PRIMARY KEY, status TEXT NOT NULL, config_json TEXT NOT NULL,
          created_by TEXT, created_at REAL NOT NULL, published_at REAL
        );
        CREATE TABLE IF NOT EXISTS credit_route_versions (
          version TEXT PRIMARY KEY, status TEXT NOT NULL, config_json TEXT NOT NULL,
          created_by TEXT, created_at REAL NOT NULL, published_at REAL
        );
        CREATE TABLE IF NOT EXISTS credit_assessments (
          assessment_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, status TEXT NOT NULL,
          model_version TEXT NOT NULL, policy_version TEXT NOT NULL,
          report_encrypted BLOB, error TEXT NOT NULL DEFAULT '', created_by TEXT,
          created_at REAL NOT NULL, completed_at REAL
        );
        CREATE TABLE IF NOT EXISTS credit_evidence (
          evidence_id TEXT PRIMARY KEY, assessment_id TEXT NOT NULL, category TEXT NOT NULL,
          field_name TEXT NOT NULL, value_encrypted BLOB NOT NULL, source_document_id TEXT,
          source_ref TEXT NOT NULL DEFAULT '', confidence REAL, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS translations (
          job_id TEXT NOT NULL, target_lang TEXT NOT NULL, status TEXT NOT NULL,
          result_encrypted BLOB, error TEXT NOT NULL DEFAULT '',
          created_by TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
          PRIMARY KEY(job_id, target_lang)
        );
        CREATE TABLE IF NOT EXISTS case_attachments (
          file_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, original_name TEXT NOT NULL,
          stored_path TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'annex',
          preview_json TEXT NOT NULL DEFAULT '[]', uploaded_by TEXT,
          created_at REAL NOT NULL
        );
        /* Case-centre tables.  contract_cases is retained for backwards
           compatibility with the original one-upload-one-case prototype. */
        CREATE TABLE IF NOT EXISTS case_documents (
          document_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, job_id TEXT UNIQUE,
          original_name TEXT NOT NULL, document_role TEXT NOT NULL DEFAULT 'main',
          version_label TEXT NOT NULL DEFAULT 'V1', source_document_id TEXT,
          created_by TEXT, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workflow_tasks (
          task_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, task_type TEXT NOT NULL,
          title TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
          assignee_id TEXT, created_by TEXT, completed_by TEXT, due_at REAL,
          payload_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, completed_at REAL
        );
        CREATE TABLE IF NOT EXISTS case_events (
          event_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, event_type TEXT NOT NULL,
          message TEXT NOT NULL, actor_id TEXT, payload_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_created ON reviews(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_findings_job ON review_findings(job_id);
        CREATE INDEX IF NOT EXISTS idx_approvals_job ON finding_approvals(job_id);
        CREATE INDEX IF NOT EXISTS idx_materials_job ON material_requests(job_id);
        CREATE INDEX IF NOT EXISTS idx_material_files_request ON material_files(request_id);
        CREATE INDEX IF NOT EXISTS idx_knowledge_rule ON clause_knowledge(rule_id);
        CREATE INDEX IF NOT EXISTS idx_export_snapshots_job ON export_snapshots(job_id);
        CREATE INDEX IF NOT EXISTS idx_rule_definitions_version ON rule_definitions(version);
        CREATE INDEX IF NOT EXISTS idx_credit_customer ON credit_cases(customer_key, status, version DESC);
        CREATE INDEX IF NOT EXISTS idx_credit_documents_case ON credit_documents(case_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_credit_document_text_status ON credit_document_text_assets(status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_credit_exposure_case ON credit_exposure_snapshots(case_id, captured_at DESC);
        CREATE INDEX IF NOT EXISTS idx_credit_assessments_case ON credit_assessments(case_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_credit_route_versions_status ON credit_route_versions(status, published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_credit_evidence_assessment ON credit_evidence(assessment_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_translations_job ON translations(job_id);
        CREATE INDEX IF NOT EXISTS idx_attachments_job ON case_attachments(job_id);
        CREATE INDEX IF NOT EXISTS idx_case_documents_case ON case_documents(case_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_workflow_tasks_case ON workflow_tasks(case_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_workflow_tasks_assignee ON workflow_tasks(assignee_id, status, due_at);
        CREATE INDEX IF NOT EXISTS idx_case_events_case ON case_events(case_id, created_at DESC);
        ''')
        _add_column(c, 'reviews', 'report_encrypted BLOB')
        _add_column(c, 'reviews', 'case_id TEXT')
        _add_column(c, 'reviews', 'created_by TEXT')
        _add_column(c, 'reviews', 'rule_version TEXT')
        _add_column(c, 'reviews', 'credit_case_id TEXT')
        _add_column(c, 'reviews', 'credit_version INTEGER')
        _add_column(c, 'reviews', "credit_snapshot_json TEXT NOT NULL DEFAULT '{}'")
        _add_column(c, 'credit_cases', "director_note TEXT NOT NULL DEFAULT ''")
        _add_column(c, 'credit_cases', 'director_by TEXT')
        _add_column(c, 'credit_cases', 'director_at REAL')
        _add_column(c, 'credit_cases', "business_type TEXT NOT NULL DEFAULT '一般'")
        # A published credit decision must retain both the Agent/model basis
        # and the reviewer's final commercial terms.  This prevents a manual
        # edit from silently disconnecting an approval from its evidence.
        _add_column(c, 'credit_cases', "assessment_id TEXT NOT NULL DEFAULT ''")
        _add_column(c, 'credit_cases', "assessment_snapshot_json TEXT NOT NULL DEFAULT '{}'")
        _add_column(c, 'credit_cases', "review_mode TEXT NOT NULL DEFAULT ''")
        _add_column(c, 'credit_cases', "reviewer_note TEXT NOT NULL DEFAULT ''")
        _add_column(c, 'credit_cases', 'reviewed_by TEXT')
        _add_column(c, 'credit_cases', 'reviewed_at REAL')
        # Credit approval is a closed loop.  A supervisor or final approver
        # can return an application to the business requester or reviewer
        # without destroying its assessment, evidence, or approval history.
        _add_column(c, 'credit_cases', "return_note TEXT NOT NULL DEFAULT ''")
        _add_column(c, 'credit_cases', "return_target TEXT NOT NULL DEFAULT ''")
        _add_column(c, 'credit_cases', 'returned_by TEXT')
        _add_column(c, 'credit_cases', 'returned_at REAL')
        _add_column(c, 'credit_cases', "route_version TEXT NOT NULL DEFAULT ''")
        _add_column(c, 'credit_cases', "route_snapshot_json TEXT NOT NULL DEFAULT '{}'")
        for definition in ('assigned_to TEXT', "priority TEXT NOT NULL DEFAULT 'normal'", 'due_at REAL', "request_note TEXT NOT NULL DEFAULT ''"):
            _add_column(c, 'contract_cases', definition)
        for definition in ("customer_name TEXT NOT NULL DEFAULT ''", "current_stage TEXT NOT NULL DEFAULT 'draft'", "credit_case_id TEXT NOT NULL DEFAULT ''", 'closed_at REAL'):
            _add_column(c, 'contract_cases', definition)
        # Runtime model configuration now has one home: backend/data/config.json.
        # This old table contained only provider settings and no business data.
        c.execute('DROP TABLE IF EXISTS runtime_settings')
        # Role-model migration (v4): the original credit/legal/CEO demo
        # roles are consolidated into the Dongjiang approval hierarchy.  This
        # runs idempotently on startup so existing local accounts, pending
        # approvals and historic audit rows remain usable.
        for old_role, new_role in {'credit': 'reviewer', 'legal': 'reviewer', 'ceo': 'admin'}.items():
            c.execute('UPDATE users SET role=?,updated_at=? WHERE role=?', (new_role, time.time(), old_role))
            c.execute('UPDATE review_actions SET actor_role=? WHERE actor_role=?', (new_role, old_role))
            c.execute('UPDATE audit_events SET actor_role=? WHERE actor_role=?', (new_role, old_role))
            c.execute('UPDATE finding_approvals SET required_role=? WHERE required_role=?', (new_role, old_role))
            c.execute('UPDATE rule_definitions SET approval_role=? WHERE approval_role=?', (new_role, old_role))
        # v5 introduces the documented two-step credit decision: finance
        # manager review first, Group CFO final approval second.  A legacy
        # pending item has not recorded either decision, therefore it restarts
        # at the finance-manager queue rather than being silently finalised.
        c.execute("UPDATE credit_cases SET status='pending_director',updated_at=? WHERE status='pending_approval'", (time.time(),))
        # Refresh only the legacy demo wording while preserving any unrelated
        # administrator edits to the rule catalogue.
        c.execute("UPDATE rule_definitions SET baseline=REPLACE(baseline,'CEO','集团财务总监'), rule_check=REPLACE(rule_check,'CEO','最终审批人'), template=REPLACE(template,'CEO','集团财务总监') WHERE approval_role='admin' AND (baseline LIKE '%CEO%' OR rule_check LIKE '%CEO%' OR template LIKE '%CEO%')")
        c.execute("UPDATE rule_definitions SET baseline=REPLACE(baseline,'总监','财务审批主管'), rule_check=REPLACE(rule_check,'总监','主管'), template=REPLACE(template,'总监','财务审批主管') WHERE approval_role='director' AND (baseline LIKE '%总监%' OR rule_check LIKE '%总监%' OR template LIKE '%总监%')")
        # Existing demo data remains accessible after the case-centre upgrade:
        # every historical primary review becomes the first document of its case.
        legacy = c.execute("SELECT case_id,job_id,created_by,created_at FROM contract_cases WHERE job_id IS NOT NULL AND job_id<>''").fetchall()
        for row in legacy:
            exists = c.execute('SELECT 1 FROM case_documents WHERE job_id=?', (row['job_id'],)).fetchone()
            if not exists:
                review = c.execute('SELECT filename FROM reviews WHERE id=?', (row['job_id'],)).fetchone()
                c.execute('INSERT INTO case_documents VALUES (?,?,?,?,?,?,?,?,?)',
                          ('DOC-' + uuid.uuid4().hex[:16].upper(), row['case_id'], row['job_id'],
                           (review['filename'] if review else '历史合同'), 'main', 'V1', None,
                           row['created_by'], row['created_at']))
            c.execute("UPDATE contract_cases SET current_stage=CASE status WHEN 'running' THEN 'ai_review' WHEN 'pending_review' THEN 'legal_review' WHEN 'in_review' THEN 'legal_review' WHEN 'returned' THEN 'awaiting_business' WHEN 'approved' THEN 'ready_to_sign' WHEN 'closed' THEN 'archived' ELSE current_stage END WHERE case_id=?", (row['case_id'],))
    _seed_initial_admin()
    _seed_rule_catalog()
    _seed_credit_model()
    _seed_credit_route_catalog()

def _seed_rule_catalog():
    """Migrate the original immutable source list into the first published catalog."""
    from .services.rules import RULES
    with _lock, _conn() as c:
        found = c.execute('SELECT version FROM rule_versions WHERE version=?', ('contract-v1',)).fetchone()
        if found:
            return
        now = time.time()
        c.execute('INSERT INTO rule_versions VALUES (?,?,?,?,?)', ('contract-v1', 'published', None, now, now))
        for rule in RULES:
            severity = 'high' if rule['id'] in {'R01','R02','R04','R10','R12','R16'} else 'mid'
            c.execute('INSERT INTO rule_definitions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                      ('contract-v1', rule['id'], rule['dim'], rule['baseline'], rule['check'], severity,
                       json.dumps(rule.get('applies_to', ['全部']), ensure_ascii=False), rule.get('approval_role', ''),
                       rule.get('template', ''), None, now))


DEFAULT_CREDIT_ROUTE_CONFIG = {
    'director_required': True,
    'final_threshold_amount': 3_000_000,
    'final_threshold_payment_days': 60,
    'final_threshold_prepayment_ratio': 50,
    'final_on_manual_override': True,
    'final_on_acceptance_bill': True,
    'final_on_vmi_jit': True,
}


def _seed_credit_route_catalog():
    """Seed a separately versioned, publish-only credit approval route."""
    with _lock, _conn() as c:
        found = c.execute("SELECT 1 FROM credit_route_versions WHERE version='credit-route-v1'").fetchone()
        if not found:
            now = time.time()
            c.execute('INSERT INTO credit_route_versions VALUES (?,?,?,?,?,?)', (
                'credit-route-v1', 'published', json.dumps(DEFAULT_CREDIT_ROUTE_CONFIG, ensure_ascii=False), None, now, now,
            ))


def _seed_credit_model():
    """Seed an explainable scorecard, not a black-box approval model.

    The values are intentionally stored as a versioned configuration so the
    enterprise can calibrate them from real historical payment data later.
    """
    from .services.credit_model import DEFAULT_MODEL_CONFIG, DEFAULT_MODEL_VERSION
    with _lock, _conn() as c:
        found = c.execute('SELECT version FROM credit_model_versions WHERE version=?', (DEFAULT_MODEL_VERSION,)).fetchone()
        if found:
            return
        now = time.time()
        c.execute('INSERT INTO credit_model_versions VALUES (?,?,?,?,?,?)',
                  (DEFAULT_MODEL_VERSION, 'published', json.dumps(DEFAULT_MODEL_CONFIG, ensure_ascii=False), None, now, now))


def _normalize_credit_route_config(raw: dict | None) -> dict:
    value = {**DEFAULT_CREDIT_ROUTE_CONFIG, **(raw or {})}
    try:
        value['final_threshold_amount'] = max(0.0, float(value['final_threshold_amount']))
        value['final_threshold_payment_days'] = max(0, int(value['final_threshold_payment_days']))
        value['final_threshold_prepayment_ratio'] = min(100.0, max(0.0, float(value['final_threshold_prepayment_ratio'])))
    except (TypeError, ValueError) as exc:
        raise ValueError('信审批核阈值必须是有效数字') from exc
    for key in ('director_required', 'final_on_manual_override', 'final_on_acceptance_bill', 'final_on_vmi_jit'):
        value[key] = bool(value[key])
    return value


def list_credit_route_versions():
    init_db()
    with _lock, _conn() as c:
        return [dict(row) for row in c.execute('SELECT version,status,created_by,created_at,published_at FROM credit_route_versions ORDER BY created_at DESC')]


def get_credit_route_version(version: str='') -> dict:
    init_db()
    with _lock, _conn() as c:
        if not version:
            row = c.execute("SELECT * FROM credit_route_versions WHERE status='published' ORDER BY published_at DESC LIMIT 1").fetchone()
        else:
            row = c.execute('SELECT * FROM credit_route_versions WHERE version=?', (version,)).fetchone()
    if not row:
        return {'version': '', 'status': '', 'config': dict(DEFAULT_CREDIT_ROUTE_CONFIG)}
    item = dict(row); item['config'] = _normalize_credit_route_config(json.loads(item.pop('config_json') or '{}'))
    return item


def create_credit_route_draft(actor: dict) -> dict:
    current = get_credit_route_version()
    with _lock, _conn() as c:
        n = c.execute('SELECT COUNT(*) AS n FROM credit_route_versions').fetchone()['n']
        version = f'credit-route-v{n + 1}'; now = time.time()
        c.execute('INSERT INTO credit_route_versions VALUES (?,?,?,?,?,?)', (
            version, 'draft', json.dumps(current['config'], ensure_ascii=False), actor.get('id'), now, None,
        ))
    return get_credit_route_version(version)


def update_credit_route_version(version: str, config: dict, actor: dict) -> dict:
    normalized = _normalize_credit_route_config(config)
    with _lock, _conn() as c:
        row = c.execute('SELECT status FROM credit_route_versions WHERE version=?', (version,)).fetchone()
        if not row:
            raise ValueError('信审批核路由版本不存在')
        if row['status'] != 'draft':
            raise ValueError('已发布信审批核路由不可编辑，请先创建草稿')
        c.execute('UPDATE credit_route_versions SET config_json=? WHERE version=?', (json.dumps(normalized, ensure_ascii=False), version))
    return get_credit_route_version(version)


def publish_credit_route_version(version: str, actor: dict) -> dict:
    with _lock, _conn() as c:
        row = c.execute('SELECT status,config_json FROM credit_route_versions WHERE version=?', (version,)).fetchone()
        if not row or row['status'] != 'draft':
            raise ValueError('仅草稿信审批核路由可发布')
        _normalize_credit_route_config(json.loads(row['config_json'] or '{}'))
        now = time.time()
        c.execute("UPDATE credit_route_versions SET status='archived' WHERE status='published'")
        c.execute("UPDATE credit_route_versions SET status='published',published_at=? WHERE version=?", (now, version))
    return get_credit_route_version(version)


def _evaluate_credit_route(route: dict, conditions: dict, review_mode: str='') -> dict:
    config = route['config']; reasons: list[str] = []
    if not config['director_required']:
        raise ValueError('当前信审批核路由未要求主管复核，配置无效')
    if float(conditions.get('max_credit_amount') or 0) >= config['final_threshold_amount']:
        reasons.append(f"额度≥{config['final_threshold_amount']:g}")
    if int(conditions.get('max_payment_days') or 0) >= config['final_threshold_payment_days']:
        reasons.append(f"账期≥{config['final_threshold_payment_days']}天")
    if float(conditions.get('min_prepayment_ratio') or 0) <= config['final_threshold_prepayment_ratio']:
        reasons.append(f"预付款≤{config['final_threshold_prepayment_ratio']:g}%")
    methods = set(conditions.get('allowed_payment_methods') or [])
    if config['final_on_acceptance_bill'] and 'acceptance_bill' in methods:
        reasons.append('包含承兑汇票')
    if config['final_on_vmi_jit'] and bool(conditions.get('allow_vmi_jit')):
        reasons.append('允许 VMI/JIT')
    if config['final_on_manual_override'] and review_mode in {'reviewer_adjusted', 'manual_override'}:
        reasons.append('人工修订/兜底报送')
    return {'version': route['version'], 'config': config, 'requires_final': bool(reasons), 'reasons': reasons}


def credit_route_for_case(conditions: dict, review_mode: str='', assessment_snapshot: dict | None=None) -> dict:
    return _evaluate_credit_route(get_credit_route_version(), conditions, review_mode)

def _rule_rows(version: str):
    with _lock, _conn() as c:
        rows = c.execute('SELECT * FROM rule_definitions WHERE version=? ORDER BY rule_id', (version,)).fetchall()
    return [{**dict(row), 'id': row['rule_id'], 'check': row['rule_check'], 'applies_to': json.loads(row['applies_json'] or '[]')} for row in rows]

def list_rule_versions():
    init_db()
    with _lock, _conn() as c:
        return [dict(row) for row in c.execute('SELECT * FROM rule_versions ORDER BY created_at DESC')]

def get_rule_version(version: str=''):
    init_db()
    if not version:
        with _lock, _conn() as c:
            row = c.execute("SELECT version FROM rule_versions WHERE status='published' ORDER BY published_at DESC LIMIT 1").fetchone()
        version = row['version'] if row else 'contract-v1'
    return {'version': version, 'rules': _rule_rows(version)}

def create_rule_draft(actor: dict):
    current = get_rule_version()
    with _lock, _conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM rule_versions").fetchone()['n']
        version = f'contract-v{n + 1}'
        now = time.time()
        c.execute('INSERT INTO rule_versions VALUES (?,?,?,?,?)', (version, 'draft', actor.get('id'), now, None))
        for rule in current['rules']:
            c.execute('INSERT INTO rule_definitions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                      (version, rule['id'], rule['dim'], rule['baseline'], rule['check'], rule['severity'],
                       json.dumps(rule['applies_to'], ensure_ascii=False), rule.get('approval_role', ''), rule.get('template', ''), actor.get('id'), now))
    return get_rule_version(version)

def update_rule_definition(version: str, rule_id: str, body: dict, actor: dict):
    allowed = {'baseline', 'check', 'severity', 'applies_to', 'approval_role', 'template'}
    values = {key: body[key] for key in allowed if key in body}
    if not values:
        raise ValueError('未提供可更新的规则字段')
    if values.get('severity') not in {None, 'high', 'mid', 'low'}:
        raise ValueError('风险等级无效')
    if 'applies_to' in values and (not isinstance(values['applies_to'], list) or not values['applies_to']):
        raise ValueError('适用业务类型必须为非空数组')
    with _lock, _conn() as c:
        status = c.execute('SELECT status FROM rule_versions WHERE version=?', (version,)).fetchone()
        if not status:
            raise ValueError('规则版本不存在')
        if status['status'] != 'draft':
            raise ValueError('已发布版本不可编辑，请先创建草稿')
        row = c.execute('SELECT rule_id FROM rule_definitions WHERE version=? AND rule_id=?', (version, rule_id)).fetchone()
        if not row:
            raise ValueError('规则不存在')
        fields=[]; args=[]
        for key, value in values.items():
            column = 'rule_check' if key == 'check' else ('applies_json' if key == 'applies_to' else key)
            fields.append(f'{column}=?'); args.append(json.dumps(value, ensure_ascii=False) if key == 'applies_to' else value)
        fields.extend(['updated_by=?', 'updated_at=?']); args.extend([actor.get('id'), time.time(), version, rule_id])
        c.execute(f'UPDATE rule_definitions SET {", ".join(fields)} WHERE version=? AND rule_id=?', args)
    return get_rule_version(version)

def publish_rule_version(version: str, actor: dict):
    with _lock, _conn() as c:
        rows = c.execute('SELECT rule_id,dim FROM rule_definitions WHERE version=?', (version,)).fetchall()
        if len(rows) != 16 or len({row['rule_id'] for row in rows}) != 16 or len({row['dim'] for row in rows}) != 16:
            raise ValueError('发布版本必须包含完整且唯一的 16 条底线规则')
        current = c.execute('SELECT status FROM rule_versions WHERE version=?', (version,)).fetchone()
        if not current or current['status'] != 'draft':
            raise ValueError('仅草稿版本可发布')
        now = time.time()
        c.execute("UPDATE rule_versions SET status='archived' WHERE status='published'")
        c.execute("UPDATE rule_versions SET status='published', published_at=? WHERE version=?", (now, version))
    return get_rule_version(version)

# ---- credit review: the only source of customer commercial conditions ----
def _credit_case(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item['conditions'] = json.loads(item.pop('conditions_json') or '{}')
    item['assessment_snapshot'] = json.loads(item.pop('assessment_snapshot_json', '') or '{}')
    item['route_snapshot'] = json.loads(item.pop('route_snapshot_json', '') or '{}')
    return item

def _customer_key(customer_name: str) -> str:
    key = ''.join((customer_name or '').strip().lower().split())
    if len(key) < 2:
        raise ValueError('客户名称至少需要 2 个字符')
    return key[:200]

def list_credit_cases(customer: str='', active_only: bool=False, created_by: str='') -> list[dict]:
    init_db()
    sql = 'SELECT * FROM credit_cases'
    args: list[Any] = []
    where = []
    if customer.strip():
        where.append('customer_name LIKE ?'); args.append(f'%{customer.strip()}%')
    if created_by:
        where.append('created_by=?'); args.append(created_by)
    if active_only:
        now = time.time()
        where.append("status='approved'")
        # valid_to lives inside the immutable JSON snapshot; filter exact validity below.
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY customer_name, version DESC'
    with _lock, _conn() as c:
        items = [_credit_case(row) for row in c.execute(sql, args).fetchall()]
    if active_only:
        now = time.time()
        items = [item for item in items if not item['conditions'].get('valid_from') or item['conditions']['valid_from'] <= now]
        items = [item for item in items if not item['conditions'].get('valid_to') or item['conditions']['valid_to'] >= now]
    return items

def get_credit_case(case_id: str) -> dict | None:
    init_db()
    with _lock, _conn() as c:
        return _credit_case(c.execute('SELECT * FROM credit_cases WHERE case_id=?', (case_id,)).fetchone())

def create_credit_case(customer_name: str, conditions: dict, request_note: str, actor: dict, business_type: str='一般') -> dict:
    from .services.credit import normalize_conditions
    customer_name = (customer_name or '').strip()
    if actor.get('role') not in {'business', 'reviewer', 'admin'}:
        raise ValueError('当前角色不能发起信审申请')
    key = _customer_key(customer_name)
    normal = normalize_conditions(conditions)
    business_type = str(business_type or '一般').strip()[:40]
    now = time.time(); case_id = 'CREDIT-' + uuid.uuid4().hex[:12].upper()
    with _lock, _conn() as c:
        row = c.execute('SELECT COALESCE(MAX(version), 0) AS v FROM credit_cases WHERE customer_key=?', (key,)).fetchone()
        version = int(row['v']) + 1
        c.execute('''INSERT INTO credit_cases(case_id,customer_key,customer_name,version,status,conditions_json,request_note,decision_note,created_by,created_at,updated_at,business_type)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (case_id, key, customer_name, version, 'draft', json.dumps(normal, ensure_ascii=False),
                    (request_note or '').strip()[:2000], '', actor.get('id'), now, now, business_type))
    return get_credit_case(case_id)

def update_credit_case(case_id: str, conditions: dict, request_note: str, actor: dict, reviewer_note: str='') -> dict:
    from .services.credit import normalize_conditions
    if actor.get('role') not in {'reviewer', 'admin'}:
        raise ValueError('仅信用审核专员可评估并修改信审条件')
    normal = normalize_conditions(conditions)
    with _lock, _conn() as c:
        row = c.execute('SELECT status,assessment_snapshot_json,review_mode FROM credit_cases WHERE case_id=?', (case_id,)).fetchone()
        if not row:
            raise ValueError('信审案件不存在')
        if row['status'] not in {'draft', 'returned_to_reviewer'}:
            raise ValueError('仅草稿或退回审核专员的信审案件可修改；放宽已生效条件请新建信审版本')
        snapshot = json.loads(row['assessment_snapshot_json'] or '{}')
        recommended = snapshot.get('recommendation') or {}
        adjusted = bool(recommended and normal != normalize_conditions(recommended))
        if adjusted and not (reviewer_note or '').strip():
            raise ValueError('调整 Agent/模型建议条件时，必须填写审核专员修订依据')
        mode = 'reviewer_adjusted' if adjusted else row['review_mode']
        c.execute('''UPDATE credit_cases SET status='draft',conditions_json=?,request_note=?,review_mode=?,reviewer_note=?,reviewed_by=?,reviewed_at=?,return_note='',return_target='',returned_by=NULL,returned_at=NULL,updated_at=? WHERE case_id=?''',
                  (json.dumps(normal, ensure_ascii=False), (request_note or '').strip()[:2000], mode,
                   (reviewer_note or '').strip()[:2000] if adjusted else '', actor.get('id') if adjusted else None,
                   time.time() if adjusted else None, time.time(), case_id))
    return get_credit_case(case_id)


def set_credit_business_type(case_id: str, business_type: str, actor: dict) -> dict:
    if actor.get('role') not in {'reviewer', 'admin'}:
        raise ValueError('仅信用审核专员可调整信审业务类型')
    value = str(business_type or '一般').strip()[:40]
    if value not in {'TKM', 'TKP', '模具制作', '注塑组件制造', '一般'}:
        raise ValueError('业务类型仅支持 TKM、TKP、模具制作、注塑组件制造或一般')
    with _lock, _conn() as c:
        row = c.execute('SELECT status FROM credit_cases WHERE case_id=?', (case_id,)).fetchone()
        if not row:
            raise ValueError('信审案件不存在')
        if row['status'] not in {'draft', 'returned_to_reviewer'}:
            raise ValueError('仅草稿或退回审核专员的信审案件可调整业务类型')
        c.execute('UPDATE credit_cases SET business_type=?,updated_at=? WHERE case_id=?', (value, time.time(), case_id))
    return get_credit_case(case_id)

def _assessment_snapshot(assessment: dict) -> dict:
    """Keep a concise, immutable approval basis rather than a mutable latest report."""
    report = assessment.get('report') or {}
    analysis = report.get('assessment') or {}
    audit = report.get('audit_runtime') or {}
    return {
        'assessment_id': assessment.get('assessment_id'), 'assessment_status': assessment.get('status'),
        'model_version': assessment.get('model_version'), 'policy_version': assessment.get('policy_version'),
        'runtime_mode': report.get('runtime_mode'), 'agent_status': audit.get('status'),
        'model_status': analysis.get('model_status'), 'recommendation': analysis.get('recommendation') or {},
        'risk_flags': analysis.get('risk_flags') or [], 'completed_at': assessment.get('completed_at'),
    }


def record_credit_reviewer_decision(case_id: str, assessment: dict, conditions: dict, reviewer_note: str,
                                    mode: str, actor: dict, business_type: str='') -> dict:
    """Record how a reviewer adopted or overrode a production assessment.

    ``agent_recommended`` is allowed only for a complete, non-blocked production
    result.  An ``reviewer_adjusted`` or ``manual_override`` always retains the
    assessment snapshot and requires an explicit accountable reason.
    """
    from .services.credit import normalize_conditions
    if actor.get('role') not in {'reviewer', 'admin'}:
        raise ValueError('仅信用审核专员可确认或修订信审建议')
    if mode not in {'agent_recommended', 'reviewer_adjusted', 'manual_override'}:
        raise ValueError('信审处理方式无效')
    if not assessment or assessment.get('case_id') != case_id or assessment.get('status') not in {'done', 'error'}:
        raise ValueError('请先运行本案件的信审评估，再确认或修订条件')
    snapshot = _assessment_snapshot(assessment)
    analysis = (assessment.get('report') or {}).get('assessment') or {}
    production_ready = (assessment.get('status') == 'done' and snapshot.get('runtime_mode') == 'production'
                        and analysis.get('model_status') == 'ready_for_reviewer'
                        and not any(item.get('level') == 'high' for item in analysis.get('risk_flags') or []))
    note = (reviewer_note or '').strip()
    final_conditions = normalize_conditions(conditions)
    recommendation = normalize_conditions(analysis.get('recommendation') or {}) if analysis.get('recommendation') else {}
    if mode == 'agent_recommended':
        if not production_ready:
            raise ValueError('该评估尚不能作为直接报送建议；请补充材料，或填写人工修订依据后报送')
        if final_conditions != recommendation:
            raise ValueError('采用 Agent/模型建议时，报送条件必须与建议一致；调整请使用“人工修订”')
    else:
        if not note:
            raise ValueError('Agent 建议不适用或运行异常时，必须填写审核专员修订依据')
        if snapshot.get('runtime_mode') != 'production' and assessment.get('status') != 'error':
            raise ValueError('只能依据生产 ReAct 审计快照进行人工修订')
        if mode == 'reviewer_adjusted' and not production_ready:
            # A failed/blocked assessment is a manual fallback, not an ordinary
            # fine-tuning of a trustworthy recommendation.
            mode = 'manual_override'
    now = time.time()
    with _lock, _conn() as c:
        row = c.execute('SELECT status FROM credit_cases WHERE case_id=?', (case_id,)).fetchone()
        if not row:
            raise ValueError('信审案件不存在')
        if row['status'] not in {'draft', 'returned_to_reviewer'}:
            raise ValueError('仅草稿或退回审核专员的信审案件可确认或修订建议')
        business = str(business_type or '').strip()
        if business and business not in {'TKM', 'TKP', '模具制作', '注塑组件制造', '一般'}:
            raise ValueError('业务类型无效')
        fields = '''conditions_json=?,assessment_id=?,assessment_snapshot_json=?,review_mode=?,reviewer_note=?,reviewed_by=?,reviewed_at=?,updated_at=?'''
        values: list[Any] = [json.dumps(final_conditions, ensure_ascii=False), assessment.get('assessment_id') or '',
                             json.dumps(snapshot, ensure_ascii=False), mode, note[:2000], actor.get('id'), now, now]
        if business:
            fields += ',business_type=?'; values.append(business)
        values.append(case_id)
        fields = "status='draft',return_note='',return_target='',returned_by=NULL,returned_at=NULL," + fields
        c.execute(f'UPDATE credit_cases SET {fields} WHERE case_id=?', values)
    return get_credit_case(case_id)


def submit_credit_case(case_id: str, actor: dict) -> dict:
    if actor.get('role') not in {'reviewer', 'admin'}:
        raise ValueError('仅信用审核专员可提交信审评估')
    # Fetch the published route before acquiring the case-write lock.  The
    # storage backend intentionally uses a non-reentrant lock, so querying a
    # versioned policy from within that critical section would deadlock.
    route_catalog = get_credit_route_version()
    with _lock, _conn() as c:
        row = c.execute('SELECT status,review_mode,reviewer_note,assessment_id,assessment_snapshot_json,conditions_json FROM credit_cases WHERE case_id=?', (case_id,)).fetchone()
        if not row:
            raise ValueError('信审案件不存在')
        if row['status'] not in {'draft', 'returned_to_reviewer'}:
            raise ValueError('仅草稿或退回审核专员的信审案件可提交')
        if row['review_mode'] not in {'agent_recommended', 'reviewer_adjusted', 'manual_override'} or not row['assessment_id']:
            raise ValueError('请先确认生产 Agent/模型建议；若建议不适用或 Agent 异常，请填写人工修订依据后再报送')
        if row['review_mode'] in {'reviewer_adjusted', 'manual_override'} and not (row['reviewer_note'] or '').strip():
            raise ValueError('人工修订或 Agent 异常报送必须填写审核专员修订依据')
        snapshot = json.loads(row['assessment_snapshot_json'] or '{}')
        if row['review_mode'] == 'agent_recommended':
            recommended = snapshot.get('recommendation') or {}
            from .services.credit import normalize_conditions
            if not recommended or normalize_conditions(json.loads(row['conditions_json'] or '{}')) != normalize_conditions(recommended):
                raise ValueError('报送条件已偏离 Agent/模型建议，请填写审核专员修订依据后重新确认')
        now = time.time()
        conditions = json.loads(row['conditions_json'] or '{}')
        route = _evaluate_credit_route(route_catalog, conditions, row['review_mode'])
        c.execute("UPDATE credit_cases SET status='pending_director',submitted_at=?,route_version=?,route_snapshot_json=?,return_note='',return_target='',returned_by=NULL,returned_at=NULL,updated_at=? WHERE case_id=?",
                  (now, route['version'], json.dumps(route, ensure_ascii=False), now, case_id))
    return get_credit_case(case_id)

def decide_credit_case(case_id: str, decision: str, note: str, actor: dict) -> dict:
    if decision not in {'approved', 'rejected', 'returned_to_reviewer', 'returned_to_business'}:
        raise ValueError('信审决定仅支持通过、拒绝或退回修改/补材料')
    if not (note or '').strip():
        raise ValueError('请填写信审审批意见')
    with _lock, _conn() as c:
        case = c.execute('SELECT * FROM credit_cases WHERE case_id=?', (case_id,)).fetchone()
        if not case:
            raise ValueError('信审案件不存在')
        role = actor.get('role')
        if case['status'] == 'pending_director':
            if role != 'director':
                raise ValueError('该信审申请须由财务审批主管先复核')
            now = time.time()
            if decision == 'rejected':
                c.execute('UPDATE credit_cases SET status=?,director_note=?,director_by=?,director_at=?,decision_note=?,decided_by=?,decided_at=?,updated_at=? WHERE case_id=?',
                          ('rejected', note.strip()[:2000], actor.get('id'), now, note.strip()[:2000], actor.get('id'), now, now, case_id))
            elif decision.startswith('returned_'):
                c.execute('''UPDATE credit_cases SET status=?,director_note=?,director_by=?,director_at=?,return_note=?,return_target=?,returned_by=?,returned_at=?,updated_at=? WHERE case_id=?''',
                          (decision, note.strip()[:2000], actor.get('id'), now, note.strip()[:2000],
                           'reviewer' if decision == 'returned_to_reviewer' else 'business', actor.get('id'), now, now, case_id))
            else:
                route = json.loads(case['route_snapshot_json'] or '{}')
                if route.get('requires_final'):
                    c.execute("UPDATE credit_cases SET status='pending_final',director_note=?,director_by=?,director_at=?,updated_at=? WHERE case_id=?",
                              (note.strip()[:2000], actor.get('id'), now, now, case_id))
                else:
                    c.execute("UPDATE credit_cases SET status='superseded',updated_at=? WHERE customer_key=? AND status='approved'", (now, case['customer_key']))
                    c.execute('UPDATE credit_cases SET status=?,director_note=?,director_by=?,director_at=?,decision_note=?,decided_by=?,decided_at=?,updated_at=? WHERE case_id=?',
                              ('approved', note.strip()[:2000], actor.get('id'), now, note.strip()[:2000], actor.get('id'), now, now, case_id))
        else:
            if case['status'] != 'pending_final':
                raise ValueError('仅待最终审批的信审案件可作出决定')
            if role != 'admin':
                raise ValueError('该信审申请须由集团财务总监最终批核')
            now = time.time()
            if decision == 'approved':
                # A newly approved version supersedes the older decision.
                # Contract reviews must be rerun against this new snapshot.
                c.execute("UPDATE credit_cases SET status='superseded',updated_at=? WHERE customer_key=? AND status='approved'", (now, case['customer_key']))
            if decision.startswith('returned_'):
                c.execute('''UPDATE credit_cases SET status=?,return_note=?,return_target=?,returned_by=?,returned_at=?,updated_at=? WHERE case_id=?''',
                          (decision, note.strip()[:2000], 'reviewer' if decision == 'returned_to_reviewer' else 'business',
                           actor.get('id'), now, now, case_id))
            else:
                c.execute('UPDATE credit_cases SET status=?,decision_note=?,decided_by=?,decided_at=?,updated_at=? WHERE case_id=?',
                          (decision, note.strip()[:2000], actor.get('id'), now, now, case_id))
    return get_credit_case(case_id)


def resubmit_credit_case(case_id: str, actor: dict) -> dict:
    """Return a business-material loop to the reviewer queue without bypassing review."""
    if actor.get('role') not in {'business', 'reviewer', 'admin'}:
        raise ValueError('当前角色不能重新提交信审申请')
    with _lock, _conn() as c:
        row = c.execute('SELECT status,created_by FROM credit_cases WHERE case_id=?', (case_id,)).fetchone()
        if not row:
            raise ValueError('信审案件不存在')
        if row['status'] != 'returned_to_business':
            raise ValueError('仅退回补材料的信审案件可重新提交')
        if actor.get('role') == 'business' and row['created_by'] != actor.get('id'):
            raise ValueError('仅申请人可重新提交该信审案件')
        c.execute("UPDATE credit_cases SET status='draft',updated_at=? WHERE case_id=?", (time.time(), case_id))
    return get_credit_case(case_id)

def require_active_credit_case(case_id: str) -> dict:
    item = get_credit_case(case_id)
    if not item:
        raise ValueError('未找到绑定的信审案件')
    if item['status'] != 'approved':
        raise ValueError('绑定的信审版本尚未生效；合同不得绕过信审')
    now = time.time(); conditions = item['conditions']
    if conditions.get('valid_from') and conditions['valid_from'] > now:
        raise ValueError('绑定的信审版本尚未到生效日期')
    if conditions.get('valid_to') and conditions['valid_to'] < now:
        raise ValueError('绑定的信审版本已失效，请先更新信审')
    return item


# ---- quantitative credit assessment artifacts ----
def _credit_document(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    # Stored paths are an internal implementation detail and must never be
    # returned by list APIs to a browser.
    item.pop('stored_path', None)
    return item


def save_credit_document_text_asset(document_id: str, content_hash: str, records: list[dict] | None,
                                    parser_version: str, status: str='ready', error: str='') -> None:
    """Persist source-bound normalized text encrypted at rest.

    ``records`` intentionally retains page/table/OCR anchors rather than a
    flattened string.  That makes later RAG citations reproducible and avoids
    re-running OCR for an unchanged upload.
    """
    init_db(); now = time.time()
    payload = encrypt_json(records or []) if records is not None else None
    with _lock, _conn() as c:
        c.execute('''INSERT INTO credit_document_text_assets
                     (document_id,content_hash,parser_version,status,records_encrypted,error,created_at,updated_at)
                     VALUES (?,?,?,?,?,?,?,?)
                     ON CONFLICT(document_id) DO UPDATE SET
                       content_hash=excluded.content_hash, parser_version=excluded.parser_version,
                       status=excluded.status, records_encrypted=excluded.records_encrypted,
                       error=excluded.error, updated_at=excluded.updated_at''',
                  (document_id, content_hash, parser_version, status, payload, str(error or '')[:1000], now, now))


def get_credit_document_text_asset(document_id: str, content_hash: str='') -> dict | None:
    init_db()
    with _lock, _conn() as c:
        row = c.execute('SELECT * FROM credit_document_text_assets WHERE document_id=?', (document_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    if content_hash and item.get('content_hash') != content_hash:
        return None
    blob = item.pop('records_encrypted', None)
    item['records'] = decrypt_json(blob) if blob else []
    return item


def add_credit_document(case_id: str, document_type: str, original_name: str, stored_path: str, actor: dict) -> dict:
    init_db()
    if not get_credit_case(case_id):
        raise ValueError('信审案件不存在')
    if not os.path.isfile(stored_path):
        raise ValueError('信审材料未成功保存')
    document_type = str(document_type or 'other').strip().lower()[:40]
    allowed = {'financial_report', 'credit_report', 'trade_history', 'application', 'approval_evidence', 'other'}
    if document_type not in allowed:
        raise ValueError('不支持的信审材料类型')
    digest = hashlib.sha256()
    with open(stored_path, 'rb') as source:
        for chunk in iter(lambda: source.read(1 << 20), b''):
            digest.update(chunk)
    item = {
        'document_id': 'CDOC-' + uuid.uuid4().hex[:16].upper(), 'case_id': case_id,
        'document_type': document_type, 'original_name': os.path.basename(original_name or 'credit-document'),
        'stored_path': stored_path, 'content_hash': digest.hexdigest(), 'uploaded_by': actor.get('id'), 'created_at': time.time(),
    }
    with _lock, _conn() as c:
        c.execute('INSERT INTO credit_documents VALUES (?,?,?,?,?,?,?,?)', tuple(item.values()))
    return _credit_document(item)


def list_credit_documents(case_id: str) -> list[dict]:
    init_db()
    with _lock, _conn() as c:
        rows = c.execute('''SELECT d.*, a.status AS text_status, a.parser_version AS text_parser_version,
                            a.updated_at AS text_updated_at, a.error AS text_error
                            FROM credit_documents d LEFT JOIN credit_document_text_assets a ON a.document_id=d.document_id
                            WHERE d.case_id=? ORDER BY d.created_at DESC''', (case_id,)).fetchall()
    return [_credit_document(row) for row in rows]


def get_credit_document(case_id: str, document_id: str) -> dict | None:
    init_db()
    with _lock, _conn() as c:
        row = c.execute('''SELECT d.*, a.status AS text_status, a.parser_version AS text_parser_version,
                           a.updated_at AS text_updated_at, a.error AS text_error
                           FROM credit_documents d LEFT JOIN credit_document_text_assets a ON a.document_id=d.document_id
                           WHERE d.case_id=? AND d.document_id=?''', (case_id, document_id)).fetchone()
    return dict(row) if row else None


def save_credit_exposure_snapshot(case_id: str, payload: dict, actor: dict, source: str='manual') -> dict:
    """Persist a point-in-time ERP/CRM exposure snapshot encrypted at rest."""
    init_db()
    if not get_credit_case(case_id):
        raise ValueError('信审案件不存在')
    raw = payload or {}
    numeric_keys = ('current_receivables', 'booked_order_amount', 'overdue_amount', 'overdue_days')
    clean: dict[str, Any] = {}
    try:
        for key in numeric_keys:
            value = raw.get(key, 0)
            clean[key] = int(value or 0) if key == 'overdue_days' else float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError('敞口快照的金额和逾期天数必须为数字') from exc
    if any(clean[key] < 0 for key in numeric_keys):
        raise ValueError('敞口快照不能包含负数')
    clean['currency'] = str(raw.get('currency') or 'CNY').upper()[:8]
    clean['as_of'] = float(raw.get('as_of') or time.time())
    clean['note'] = str(raw.get('note') or '')[:1000]
    item = {
        'snapshot_id': 'CEXP-' + uuid.uuid4().hex[:16].upper(), 'case_id': case_id,
        'source': str(source or 'manual')[:40], 'payload_encrypted': encrypt_json(clean),
        'captured_at': clean['as_of'], 'created_by': actor.get('id'), 'created_at': time.time(),
    }
    with _lock, _conn() as c:
        c.execute('INSERT INTO credit_exposure_snapshots VALUES (?,?,?,?,?,?,?)', tuple(item.values()))
    return {key: value for key, value in item.items() if key != 'payload_encrypted'} | {'payload': clean}


def latest_credit_exposure_snapshot(case_id: str) -> dict | None:
    init_db()
    with _lock, _conn() as c:
        row = c.execute('SELECT * FROM credit_exposure_snapshots WHERE case_id=? ORDER BY captured_at DESC,created_at DESC LIMIT 1', (case_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item['payload'] = decrypt_json(item.pop('payload_encrypted'))
    return item


def get_credit_model(version: str='') -> dict:
    init_db()
    with _lock, _conn() as c:
        row = c.execute('SELECT * FROM credit_model_versions WHERE version=?', (version,)).fetchone() if version else c.execute("SELECT * FROM credit_model_versions WHERE status='published' ORDER BY published_at DESC LIMIT 1").fetchone()
    if not row:
        raise ValueError('未找到已发布的信审模型版本')
    item = dict(row)
    item['config'] = json.loads(item.pop('config_json') or '{}')
    return item


def start_credit_assessment(case_id: str, actor: dict, model_version: str='') -> dict:
    init_db()
    case = get_credit_case(case_id)
    if not case:
        raise ValueError('信审案件不存在')
    if case['status'] != 'draft':
        raise ValueError('仅草稿信审案件可重新运行量化评估')
    model = get_credit_model(model_version)
    item = {
        'assessment_id': 'CASM-' + uuid.uuid4().hex[:16].upper(), 'case_id': case_id, 'status': 'running',
        'model_version': model['version'], 'policy_version': 'dongjiang-credit-policy-v1',
        'report_encrypted': None, 'error': '', 'created_by': actor.get('id'), 'created_at': time.time(), 'completed_at': None,
    }
    with _lock, _conn() as c:
        c.execute('INSERT INTO credit_assessments VALUES (?,?,?,?,?,?,?,?,?,?)', tuple(item.values()))
    return {key: value for key, value in item.items() if key != 'report_encrypted'}


def finish_credit_assessment(assessment_id: str, report: dict | None, evidence: list[dict], error: str='') -> dict:
    """Atomically store the report and its source-bound facts after a run."""
    now = time.time()
    status = 'error' if error else 'done'
    with _lock, _conn() as c:
        row = c.execute('SELECT assessment_id FROM credit_assessments WHERE assessment_id=?', (assessment_id,)).fetchone()
        if not row:
            raise ValueError('信审评估任务不存在')
        c.execute('UPDATE credit_assessments SET status=?,report_encrypted=?,error=?,completed_at=? WHERE assessment_id=?',
                  (status, encrypt_json(report) if report else None, str(error or '')[:2000], now, assessment_id))
        c.execute('DELETE FROM credit_evidence WHERE assessment_id=?', (assessment_id,))
        for source in evidence or []:
            c.execute('INSERT INTO credit_evidence VALUES (?,?,?,?,?,?,?,?,?)',
                      ('CEVD-' + uuid.uuid4().hex[:16].upper(), assessment_id,
                       str(source.get('category') or 'fact')[:60], str(source.get('field') or '')[:100],
                       encrypt_json(source.get('value')), source.get('document_id'),
                       str(source.get('source_ref') or '')[:500], source.get('confidence'), now))
    return get_credit_assessment(assessment_id) or {}


def get_credit_assessment(assessment_id: str) -> dict | None:
    init_db()
    with _lock, _conn() as c:
        row = c.execute('SELECT * FROM credit_assessments WHERE assessment_id=?', (assessment_id,)).fetchone()
        evidence_rows = c.execute('SELECT * FROM credit_evidence WHERE assessment_id=? ORDER BY created_at,evidence_id', (assessment_id,)).fetchall()
    if not row:
        return None
    item = dict(row)
    payload = item.pop('report_encrypted')
    item['report'] = decrypt_json(payload) if payload else None
    item['evidence'] = [{**dict(source), 'value': decrypt_json(source['value_encrypted'])} for source in evidence_rows]
    for source in item['evidence']:
        source.pop('value_encrypted', None)
    return item


def latest_credit_assessment(case_id: str) -> dict | None:
    init_db()
    with _lock, _conn() as c:
        row = c.execute('SELECT assessment_id FROM credit_assessments WHERE case_id=? ORDER BY created_at DESC LIMIT 1', (case_id,)).fetchone()
    return get_credit_assessment(row['assessment_id']) if row else None

def _seed_initial_admin():
    if not (INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PASSWORD): return
    with _lock, _conn() as c:
        found = c.execute('SELECT id FROM users WHERE username=?', (INITIAL_ADMIN_USERNAME.strip(),)).fetchone()
        if not found:
            now = time.time()
            c.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)',
                      (uuid.uuid4().hex, INITIAL_ADMIN_USERNAME.strip(), INITIAL_ADMIN_NAME, 'admin',
                       password_hash(INITIAL_ADMIN_PASSWORD), 1, now, now))

def audit(actor: dict | None, action: str, resource_type='', resource_id='', metadata: dict | None=None, ip=''):
    with _lock, _conn() as c:
        c.execute('INSERT INTO audit_events VALUES (?,?,?,?,?,?,?,?,?)',
                  (uuid.uuid4().hex, (actor or {}).get('id'), (actor or {}).get('role'), action,
                   resource_type, resource_id, json.dumps(metadata or {}, ensure_ascii=False), ip, time.time()))

# ---- identity and administration ----
def create_user(username: str, display_name: str, role: str, password: str) -> dict:
    if role not in ROLES: raise ValueError('不支持的角色')
    username = username.strip().lower()
    if len(username) < 3: raise ValueError('用户名至少 3 个字符')
    now = time.time(); row = {'id': uuid.uuid4().hex, 'username': username, 'display_name': display_name.strip() or username,
                              'role': role, 'active': 1, 'created_at': now, 'updated_at': now}
    with _lock, _conn() as c:
        c.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)',
                  (row['id'], row['username'], row['display_name'], row['role'], password_hash(password), 1, now, now))
    return row

def list_users():
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute('SELECT id,username,display_name,role,active,created_at,updated_at FROM users ORDER BY created_at')]

def get_user_by_username(username: str):
    with _lock, _conn() as c:
        r = c.execute('SELECT * FROM users WHERE username=?', (username.strip().lower(),)).fetchone()
        return dict(r) if r else None

def get_user(user_id: str):
    with _lock, _conn() as c:
        r = c.execute('SELECT id,username,display_name,role,active,created_at,updated_at FROM users WHERE id=?', (user_id,)).fetchone()
        return dict(r) if r else None

def authenticate(username: str, password: str):
    user = get_user_by_username(username)
    if not user or not user.get('active') or not verify_password(password, user.get('password_hash','')): return None
    user.pop('password_hash', None)
    return user

def update_user(user_id: str, display_name=None, role=None, active=None, password=None):
    fields=[]; values=[]
    if display_name is not None:
        name = str(display_name).strip()
        if not name: raise ValueError('姓名不能为空')
        fields.append('display_name=?'); values.append(name[:80])
    if role is not None:
        if role not in ROLES: raise ValueError('不支持的角色')
        fields.append('role=?'); values.append(role)
    if active is not None: fields.append('active=?'); values.append(1 if active else 0)
    if password is not None: fields.append('password_hash=?'); values.append(password_hash(password))
    if not fields: return get_user(user_id)
    fields.append('updated_at=?'); values.append(time.time()); values.append(user_id)
    with _lock, _conn() as c: c.execute(f'UPDATE users SET {",".join(fields)} WHERE id=?', values)
    return get_user(user_id)


def active_admin_count(exclude_user_id: str='') -> int:
    with _lock, _conn() as c:
        sql = "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND active=1"
        args: tuple[str, ...] = ()
        if exclude_user_id:
            sql += ' AND id<>?'; args = (exclude_user_id,)
        return int(c.execute(sql, args).fetchone()['n'])


def delete_user(user_id: str) -> dict | None:
    """Permanently remove a login identity.

    Operational records deliberately retain their actor IDs for audit
    continuity, but the credential-bearing user row is irreversibly removed.
    """
    target = get_user(user_id)
    if not target:
        return None
    with _lock, _conn() as c:
        c.execute('DELETE FROM users WHERE id=?', (user_id,))
    return target

# ---- case centre / controlled workflow ----

CASE_STAGES = {
    'draft', 'awaiting_credit', 'ai_review', 'legal_review', 'awaiting_business',
    'approval', 'final_approval', 'ready_to_sign', 'archived', 'cancelled'
}

def _case_event(c, case_id: str, event_type: str, message: str, actor: dict | None=None, payload: dict | None=None):
    c.execute('INSERT INTO case_events VALUES (?,?,?,?,?,?,?)',
              ('EVT-' + uuid.uuid4().hex[:16].upper(), case_id, event_type, message,
               (actor or {}).get('id'), json.dumps(payload or {}, ensure_ascii=False), time.time()))

def _task(c, case_id: str, task_type: str, title: str, detail: str='', assignee_id: str | None=None,
          actor: dict | None=None, due_at: float | None=None, payload: dict | None=None):
    task_id = 'TASK-' + uuid.uuid4().hex[:16].upper()
    c.execute('INSERT INTO workflow_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (task_id, case_id, task_type, title, detail, 'open', assignee_id,
               (actor or {}).get('id'), None, due_at, json.dumps(payload or {}, ensure_ascii=False), time.time(), None))
    return task_id

def create_case_center(customer_name: str, business_type: str, request_note: str, actor: dict,
                       credit_case_id: str='', priority: str='normal', due_at: float | None=None) -> dict:
    """Create the durable business case before any document is uploaded."""
    init_db()
    customer_name = (customer_name or '').strip()
    if not customer_name:
        raise ValueError('请填写客户名称')
    if priority not in CASE_PRIORITIES:
        raise ValueError('优先级无效')
    case_id = 'CASE-' + uuid.uuid4().hex[:12].upper(); now = time.time()
    stage = 'awaiting_credit' if not credit_case_id else 'draft'
    with _lock, _conn() as c:
        c.execute('''INSERT INTO contract_cases(case_id,job_id,business_type,status,created_by,created_at,updated_at,assigned_to,priority,due_at,request_note,customer_name,current_stage,credit_case_id)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (case_id, None, business_type or '一般', stage, actor.get('id'), now, now, None,
                   priority, due_at, (request_note or '').strip()[:1000], customer_name, stage, credit_case_id))
        _case_event(c, case_id, 'case.created', '已创建合同案件，等待提交合同文件', actor, {'customer_name': customer_name})
        if stage == 'awaiting_credit':
            _task(c, case_id, 'credit_required', '补充或选择已生效信审版本', '合同提交前需绑定该客户的有效信审版本。', actor.get('id'), actor, due_at)
        else:
            _task(c, case_id, 'document_required', '上传合同文件包', '请上传主合同、订单或补充协议。', actor.get('id'), actor, due_at)
    return get_case_center(case_id, actor)

def _case_access_clause(actor: dict, alias: str='c') -> tuple[str, list[Any]]:
    if actor.get('role') == 'business':
        return f' AND {alias}.created_by=?', [actor.get('id')]
    return '', []

def list_case_center(actor: dict, scope: str='all', limit: int=100) -> list[dict]:
    init_db()
    with _lock, _conn() as c:
        where, params = _case_access_clause(actor)
        if scope == 'mine':
            where += ' AND (c.created_by=? OR c.assigned_to=?)'; params += [actor.get('id'), actor.get('id')]
        elif scope == 'inbox':
            where += " AND EXISTS (SELECT 1 FROM workflow_tasks wt WHERE wt.case_id=c.case_id AND wt.status='open' AND (wt.assignee_id=? OR wt.assignee_id IS NULL))"; params += [actor.get('id')]
        rows = c.execute(f'''SELECT c.case_id,c.business_type,c.status AS workflow_status,c.current_stage,c.customer_name,c.priority,c.due_at,c.request_note,
                                    c.created_by,c.created_at,c.updated_at,c.assigned_to,creator.display_name AS requester_name,assignee.display_name AS assignee_name,
                                    (SELECT original_name FROM case_documents d WHERE d.case_id=c.case_id ORDER BY d.created_at DESC LIMIT 1) AS filename,
                                    (SELECT job_id FROM case_documents d WHERE d.case_id=c.case_id ORDER BY d.created_at DESC LIMIT 1) AS job_id,
                                    (SELECT overall_level FROM reviews r JOIN case_documents d ON d.job_id=r.id WHERE d.case_id=c.case_id ORDER BY d.created_at DESC LIMIT 1) AS overall_level,
                                    (SELECT COUNT(*) FROM case_documents d WHERE d.case_id=c.case_id) AS document_count,
                                    (SELECT COUNT(*) FROM workflow_tasks wt WHERE wt.case_id=c.case_id AND wt.status='open') AS open_tasks
                             FROM contract_cases c
                             LEFT JOIN users creator ON creator.id=c.created_by
                             LEFT JOIN users assignee ON assignee.id=c.assigned_to
                             WHERE 1=1 {where}
                             ORDER BY CASE c.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, c.updated_at DESC LIMIT ?''', (*params, min(max(limit, 1), 500))).fetchall()
        return [dict(row) for row in rows]

def get_case_center(case_id: str, actor: dict | None=None) -> dict | None:
    init_db()
    with _lock, _conn() as c:
        row = c.execute('''SELECT c.*,creator.display_name AS requester_name,assignee.display_name AS assignee_name
                           FROM contract_cases c LEFT JOIN users creator ON creator.id=c.created_by
                           LEFT JOIN users assignee ON assignee.id=c.assigned_to WHERE c.case_id=?''', (case_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        if actor and actor.get('role') == 'business' and item.get('created_by') != actor.get('id'):
            return None
        docs = c.execute('''SELECT d.*,r.status AS review_status,r.overall_level,r.n_risks,r.high,r.mid,r.low
                            FROM case_documents d LEFT JOIN reviews r ON r.id=d.job_id WHERE d.case_id=? ORDER BY d.created_at DESC''', (case_id,)).fetchall()
        item['documents'] = [dict(doc) for doc in docs]
        task_where = 'WHERE case_id=?'; task_params: list[Any] = [case_id]
        if actor and actor.get('role') == 'director':
            task_where += " AND (assignee_id=? OR task_type='approval')"; task_params.append(actor.get('id'))
        item['tasks'] = [dict(task) for task in c.execute(f'SELECT * FROM workflow_tasks {task_where} ORDER BY CASE status WHEN "open" THEN 0 ELSE 1 END, due_at, created_at DESC', task_params)]
        item['events'] = [dict(event) for event in c.execute('SELECT * FROM case_events WHERE case_id=? ORDER BY created_at DESC LIMIT 100', (case_id,))]
        return item

def _case_for_job(job_id: str) -> str | None:
    with _lock, _conn() as c:
        row = c.execute('SELECT case_id FROM case_documents WHERE job_id=?', (job_id,)).fetchone()
        if not row:
            row = c.execute('SELECT case_id FROM reviews WHERE id=?', (job_id,)).fetchone()
        return row['case_id'] if row else None

def attach_document_to_case(case_id: str, job_id: str, filename: str, actor: dict, document_role: str='main', source_document_id: str='') -> dict:
    with _lock, _conn() as c:
        existing = c.execute('SELECT case_id FROM contract_cases WHERE case_id=?', (case_id,)).fetchone()
        if not existing:
            raise ValueError('合同案件不存在')
        n = c.execute('SELECT COUNT(*) AS n FROM case_documents WHERE case_id=?', (case_id,)).fetchone()['n']
        label = f'V{int(n) + 1}' if document_role in {'main', 'revision'} else f'附件{int(n) + 1}'
        doc_id = 'DOC-' + uuid.uuid4().hex[:16].upper()
        c.execute('INSERT INTO case_documents VALUES (?,?,?,?,?,?,?,?,?)',
                  (doc_id, case_id, job_id, filename or '未命名文件', document_role or 'main', label,
                   source_document_id or None, actor.get('id'), time.time()))
        c.execute("UPDATE contract_cases SET status='ai_review',current_stage='ai_review',updated_at=? WHERE case_id=?", (time.time(), case_id))
        c.execute("UPDATE workflow_tasks SET status='completed',completed_by=?,completed_at=? WHERE case_id=? AND task_type IN ('document_required','revision_required','material') AND status='open'", (actor.get('id'), time.time(), case_id))
        _case_event(c, case_id, 'document.uploaded', f'已上传 {label}：{filename}', actor, {'job_id': job_id, 'document_id': doc_id})
    return {'document_id': doc_id, 'version_label': label}

ACTION_TRANSITIONS = {
    'claim': ({'legal_review'}, 'legal_review'),
    'request_material': ({'legal_review'}, 'awaiting_business'),
    'submit_revision': ({'awaiting_business', 'legal_review'}, 'ai_review'),
    'submit_approval': ({'legal_review'}, 'approval'),
    'ready_for_signing': ({'legal_review'}, 'ready_to_sign'),
    'approve_for_signing': ({'approval'}, 'ready_to_sign'),
    'escalate_final': ({'approval'}, 'final_approval'),
    'final_approve_for_signing': ({'final_approval'}, 'ready_to_sign'),
    'return_to_reviewer': ({'approval', 'final_approval'}, 'legal_review'),
    'return_to_business': ({'approval', 'final_approval'}, 'awaiting_business'),
    'archive': ({'ready_to_sign'}, 'archived'),
    'cancel': (CASE_STAGES - {'archived', 'cancelled'}, 'cancelled'),
}

def transition_case(case_id: str, action: str, actor: dict, note: str='', assignee_id: str='') -> dict:
    if action not in ACTION_TRANSITIONS:
        raise ValueError('不支持的案件动作')
    action_roles = {
        'claim': {'reviewer', 'admin'}, 'request_material': {'reviewer', 'admin'},
        'submit_revision': {'business', 'reviewer', 'admin'}, 'submit_approval': {'reviewer', 'admin'},
        'ready_for_signing': {'reviewer', 'admin'}, 'approve_for_signing': {'director', 'admin'},
        'escalate_final': {'director', 'admin'}, 'final_approve_for_signing': {'admin'},
        'return_to_reviewer': {'director', 'admin'}, 'return_to_business': {'director', 'admin'}, 'archive': {'reviewer', 'admin'},
        'cancel': {'business', 'reviewer', 'admin'},
    }
    if actor.get('role') not in action_roles[action]:
        raise ValueError('当前角色无权执行该案件动作')
    with _lock, _conn() as c:
        row = c.execute('SELECT * FROM contract_cases WHERE case_id=?', (case_id,)).fetchone()
        if not row:
            raise ValueError('合同案件不存在')
        if actor.get('role') == 'business' and row['created_by'] != actor.get('id'):
            raise ValueError('无权操作该案件')
        current = row['current_stage'] or row['status']; allowed, target = ACTION_TRANSITIONS[action]
        if current not in allowed:
            raise ValueError(f'案件当前处于“{current}”，不能执行“{action}”')
        if action in {'ready_for_signing', 'approve_for_signing', 'final_approve_for_signing'}:
            pending_types = "('approval','material')" if action == 'ready_for_signing' else "('material')"
            pending = c.execute(f"SELECT COUNT(*) AS n FROM workflow_tasks WHERE case_id=? AND status='open' AND task_type IN {pending_types}", (case_id,)).fetchone()['n']
            if pending:
                raise ValueError('仍有未完成的审批或待补材料，不能进入可签约状态')
            # Contract-rule approvals and material requests are stored with
            # each reviewed document.  Checking them here prevents the case
            # stage button from bypassing the stricter per-finding workflow.
            required = c.execute('''SELECT DISTINCT fa.required_role FROM finding_approvals fa
                                    JOIN case_documents d ON d.job_id=fa.job_id
                                    WHERE d.case_id=?''', (case_id,)).fetchall()
            unresolved = c.execute('''SELECT COUNT(*) AS n FROM finding_approvals fa
                                      JOIN case_documents d ON d.job_id=fa.job_id
                                      WHERE d.case_id=? AND fa.status<>'approved' ''', (case_id,)).fetchone()['n']
            materials = c.execute('''SELECT COUNT(*) AS n FROM material_requests mr
                                     JOIN case_documents d ON d.job_id=mr.job_id
                                     WHERE d.case_id=? AND mr.status='open' ''', (case_id,)).fetchone()['n']
            if unresolved or materials:
                raise ValueError('仍有未完成或未通过的条款审批/补件，不能进入可签约状态')
            required_roles = {item['required_role'] for item in required}
            if action == 'approve_for_signing':
                if 'admin' in required_roles and actor.get('role') != 'admin':
                    raise ValueError('案件含集团财务总监级例外，须由集团财务总监批准可签约')
                if required_roles == {'director'} and actor.get('role') != 'director':
                    raise ValueError('案件须由财务审批主管批准可签约')
        now = time.time()
        fields = "status=?,current_stage=?,updated_at=?"; values: list[Any] = [target, target, now]
        if action == 'claim':
            if actor.get('role') not in {'reviewer', 'admin'}:
                raise ValueError('仅信用审核专员可领取案件')
            fields += ',assigned_to=?'; values.append(actor.get('id'))
        if action == 'archive':
            fields += ',closed_at=?'; values.append(now)
        values.append(case_id)
        c.execute(f'UPDATE contract_cases SET {fields} WHERE case_id=?', values)
        if action == 'claim':
            c.execute("UPDATE workflow_tasks SET assignee_id=? WHERE case_id=? AND task_type='legal_review' AND status='open'", (actor.get('id'), case_id))
        elif action == 'request_material':
            c.execute("UPDATE workflow_tasks SET status='completed',completed_by=?,completed_at=? WHERE case_id=? AND task_type='legal_review' AND status='open'", (actor.get('id'), now, case_id))
            _task(c, case_id, 'material', '补充业务材料', note or '请补充信用审核专员要求的材料。', row['created_by'], actor, row['due_at'])
        elif action == 'submit_approval':
            c.execute("UPDATE workflow_tasks SET status='completed',completed_by=?,completed_at=? WHERE case_id=? AND task_type='legal_review' AND status='open'", (actor.get('id'), now, case_id))
            _task(c, case_id, 'approval', '合同例外审批', note or '请处理合同例外审批。', assignee_id or None, actor, row['due_at'])
        elif action in {'ready_for_signing', 'approve_for_signing', 'final_approve_for_signing'}:
            types = "('legal_review','approval')" if action == 'ready_for_signing' else "('approval')"
            c.execute(f"UPDATE workflow_tasks SET status='completed',completed_by=?,completed_at=? WHERE case_id=? AND status='open' AND task_type IN {types}", (actor.get('id'), now, case_id))
        elif action == 'escalate_final':
            c.execute("UPDATE workflow_tasks SET status='completed',completed_by=?,completed_at=? WHERE case_id=? AND status='open' AND task_type='approval'", (actor.get('id'), now, case_id))
            _task(c, case_id, 'final_approval', '合同待最终审批', note or '主管复核后上报集团财务总监最终决策。', None, actor, row['due_at'])
        elif action == 'return_to_reviewer':
            c.execute("UPDATE workflow_tasks SET status='completed',completed_by=?,completed_at=? WHERE case_id=? AND status='open' AND task_type IN ('approval','final_approval')", (actor.get('id'), now, case_id))
            _task(c, case_id, 'legal_review', '主管/最终审批退回审核专员修改', note or '请核对审批意见并修订合同审查结论。', row['assigned_to'], actor, row['due_at'])
        elif action == 'return_to_business':
            c.execute("UPDATE workflow_tasks SET status='completed',completed_by=?,completed_at=? WHERE case_id=? AND status='open' AND task_type IN ('approval','final_approval')", (actor.get('id'), now, case_id))
            _task(c, case_id, 'material', '主管/最终审批退回业务补件', note or '请按审批意见补充材料或上传修订合同。', row['created_by'], actor, row['due_at'])
        elif action in {'archive', 'cancel'}:
            c.execute("UPDATE workflow_tasks SET status='completed',completed_by=?,completed_at=? WHERE case_id=? AND status='open'", (actor.get('id'), now, case_id))
        _case_event(c, case_id, f'case.{action}', note or f'执行案件动作：{action}', actor, {'from': current, 'to': target})
    return get_case_center(case_id, actor)

def complete_task(task_id: str, actor: dict, note: str='') -> dict:
    with _lock, _conn() as c:
        row = c.execute('SELECT * FROM workflow_tasks WHERE task_id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('待办不存在')
        case = c.execute('SELECT created_by FROM contract_cases WHERE case_id=?', (row['case_id'],)).fetchone()
        if actor.get('role') == 'business' and (not case or case['created_by'] != actor.get('id')):
            raise ValueError('无权完成该待办')
        if row['status'] != 'open':
            raise ValueError('待办已完成')
        now = time.time()
        c.execute("UPDATE workflow_tasks SET status='completed',completed_by=?,completed_at=?,detail=CASE WHEN ?<>'' THEN detail || '\\n处理说明：' || ? ELSE detail END WHERE task_id=?", (actor.get('id'), now, note, note, task_id))
        _case_event(c, row['case_id'], 'task.completed', f'已完成待办：{row["title"]}', actor, {'task_id': task_id, 'note': note})
    return {'task_id': task_id, 'status': 'completed'}

def my_work_items(actor: dict, limit: int=100) -> list[dict]:
    init_db()
    with _lock, _conn() as c:
        if actor.get('role') == 'business':
            condition = '(t.assignee_id=? OR c.created_by=?)'; params: list[Any] = [actor.get('id'), actor.get('id')]
        elif actor.get('role') in {'admin'}:
            condition = '1=1'; params = []
        else:
            condition = '(t.assignee_id=? OR t.assignee_id IS NULL)'; params = [actor.get('id')]
        rows = c.execute(f'''SELECT t.*,c.customer_name,c.current_stage,c.priority,c.request_note,
                                    (SELECT original_name FROM case_documents d WHERE d.case_id=c.case_id ORDER BY d.created_at DESC LIMIT 1) AS filename
                             FROM workflow_tasks t JOIN contract_cases c ON c.case_id=t.case_id
                             WHERE t.status='open' AND {condition}
                             ORDER BY CASE c.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, t.due_at, t.created_at DESC LIMIT ?''', (*params, min(max(limit, 1), 500))).fetchall()
        contract_items = [{**dict(row), 'source_type': 'contract', 'target_id': row['case_id']} for row in rows]

        role = actor.get('role')
        if role == 'business':
            credit_where = "created_by=? AND status NOT IN ('approved','rejected','superseded')"
            credit_args: list[Any] = [actor.get('id')]
        elif role == 'reviewer':
            credit_where = "status IN ('draft','returned_to_reviewer')"
            credit_args = []
        elif role == 'director':
            credit_where = "status='pending_director'"
            credit_args = []
        else:
            credit_where = "status='pending_final'"
            credit_args = []
        credit_rows = c.execute(f'''SELECT case_id,customer_name,status,request_note,return_note,return_target,
                                           created_at,updated_at,submitted_at,business_type
                                    FROM credit_cases WHERE {credit_where}
                                    ORDER BY updated_at DESC LIMIT ?''', (*credit_args, min(max(limit, 1), 500))).fetchall()
        credit_labels = {
            'draft': ('credit_assessment', '待信用审核专员评估'),
            'returned_to_reviewer': ('credit_returned', '信审已退回审核专员修改'),
            'returned_to_business': ('credit_material', '信审待补充材料'),
            'pending_director': ('credit_director_review', '待财务审批主管复核'),
            'pending_final': ('credit_final_approval', '待集团财务总监最终审批'),
        }
        credit_items = []
        for row in credit_rows:
            item = dict(row); task_type, title = credit_labels.get(item['status'], ('credit', '客户信审待处理'))
            detail = item.get('return_note') or item.get('request_note') or '请进入客户信审查看详情。'
            credit_items.append({
                'task_id': f"credit:{item['case_id']}", 'case_id': item['case_id'], 'target_id': item['case_id'],
                'source_type': 'credit', 'task_type': task_type, 'title': title, 'detail': detail,
                'status': 'open', 'due_at': None, 'created_at': item['updated_at'] or item['created_at'],
                'customer_name': item['customer_name'], 'current_stage': item['status'], 'priority': 'high' if item['status'] in {'pending_final','returned_to_business'} else 'normal',
                'filename': '', 'business_type': item.get('business_type') or '一般',
            })
    return (credit_items + contract_items)[:min(max(limit, 1), 500)]

# ---- review persistence, protected mapping, actions ----
def create_pending(job_id, filename, path, actor=None, business_type='', assignee_id='', priority='normal', due_at=None, request_note='', parent_job_id='', rule_version='contract-v1', credit_case=None, case_id='', document_role='main'):
    init_db(); now=time.time(); case_id=(case_id or '').strip()
    if not credit_case:
        raise ValueError('合同必须绑定已生效的信审版本')
    credit_snapshot = {
        'case_id': credit_case['case_id'], 'customer_name': credit_case['customer_name'],
        'version': credit_case['version'], 'conditions': credit_case['conditions'],
        'approved_at': credit_case.get('decided_at'),
    }
    existing_case_id = (case_id or '').strip()
    with _lock, _conn() as c:
        if existing_case_id:
            root = c.execute('SELECT case_id FROM contract_cases WHERE case_id=?', (existing_case_id,)).fetchone()
            if not root:
                raise ValueError('合同案件不存在')
        else:
            existing_case_id = 'CASE-'+uuid.uuid4().hex[:12].upper()
        c.execute('''INSERT OR REPLACE INTO reviews(id,filename,status,created_at,finished_at,overall_level,n_clauses,n_risks,high,mid,low,masked_entities,our_party,business_type,report_encrypted,file_path,case_id,created_by,rule_version,credit_case_id,credit_version,credit_snapshot_json)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (job_id,filename,'running',now,0,'',0,0,0,0,0,0,'',business_type,None,path,existing_case_id,(actor or {}).get('id'),rule_version,credit_case['case_id'],credit_case['version'],json.dumps(credit_snapshot, ensure_ascii=False)))
        if not case_id:
            c.execute('''INSERT INTO contract_cases(case_id,job_id,business_type,status,created_by,created_at,updated_at,assigned_to,priority,due_at,request_note,customer_name,current_stage,credit_case_id)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (existing_case_id,job_id,business_type,'ai_review',(actor or {}).get('id'),now,now,assignee_id or None,priority,due_at,request_note.strip(),credit_case.get('customer_name',''),'ai_review',credit_case.get('case_id','')))
            _case_event(c, existing_case_id, 'case.created', '已从合同上传创建案件', actor, {'job_id': job_id})
        parent = parent_job_id or None
        version = 'V1'
        if parent:
            n = c.execute('SELECT COUNT(*) AS n FROM contract_versions WHERE parent_job_id=? OR job_id=?', (parent, parent)).fetchone()['n']
            version = f'V{n + 1}'
        c.execute('INSERT OR REPLACE INTO contract_versions(job_id,parent_job_id,version_label,compare_json,created_at) VALUES (?,?,?,?,?)',
                  (job_id, parent, version, '{}', now))
    attach_document_to_case(existing_case_id, job_id, filename, actor or {}, document_role)
    return existing_case_id

def contract_credit_binding(job_id: str, require_current: bool=True) -> dict:
    init_db()
    with _lock, _conn() as c:
        row = c.execute('SELECT credit_case_id,credit_version,credit_snapshot_json FROM reviews WHERE id=?', (job_id,)).fetchone()
    if not row or not row['credit_case_id']:
        raise ValueError('合同未绑定信审版本，不能签署或导出')
    if require_current:
        active = require_active_credit_case(row['credit_case_id'])
        if int(active['version']) != int(row['credit_version'] or 0):
            raise ValueError('合同绑定的信审版本不是当前生效版本，请重新发起合同复审')
    try:
        return json.loads(row['credit_snapshot_json'] or '{}')
    except json.JSONDecodeError:
        raise ValueError('合同信审快照损坏，不能导出')

def save_mask_mapping(task_id: str, mapping: dict, actor: dict | None, ttl_hours=24):
    if not mapping:return
    now=time.time(); encrypted=encrypt_json(mapping)
    with _lock, _conn() as c:
        c.execute('INSERT OR REPLACE INTO mask_mappings VALUES(?,?,?,?,?)',(task_id,encrypted,now+ttl_hours*3600,(actor or {}).get('id'),now))

def get_mask_mapping(task_id: str) -> dict:
    """Return the still-valid mapping for server-side token restoration only."""
    init_db()
    with _lock, _conn() as c:
        row=c.execute('SELECT encrypted_mapping,expires_at FROM mask_mappings WHERE task_id=?',(task_id,)).fetchone()
    if not row or float(row['expires_at']) <= time.time():
        return {}
    mapping=decrypt_json(row['encrypted_mapping'])
    return mapping if isinstance(mapping,dict) else {}

def save_review(job_id, report, status='done', error=None, actor=None, mapping=None, rule_version='contract-v1', rules_by_id=None):
    init_db(); sm=report.get('summary',{}) or {}; f=report.get('contract_fields',{}) or {}; now=time.time()
    protected={'error':error} if status=='error' else report
    encrypted=encrypt_json(protected)
    with _lock, _conn() as c:
        old=c.execute('SELECT created_at,case_id FROM reviews WHERE id=?',(job_id,)).fetchone()
        created=(old['created_at'] if old else now); case_id=(old['case_id'] if old else '')
        c.execute('''UPDATE reviews SET status=?,finished_at=?,overall_level=?,n_clauses=?,n_risks=?,high=?,mid=?,low=?,masked_entities=?,our_party=?,business_type=?,report_encrypted=?,rule_version=? WHERE id=?''',
          (status,now,sm.get('overall_level',''),int(sm.get('n_clauses',0) or 0),int(sm.get('n_risks',0) or 0),int(sm.get('high',0) or 0),int(sm.get('mid',0) or 0),int(sm.get('low',0) or 0),int(report.get('masked_entities',0) or 0),f.get('our_party',''),f.get('business_type',''),encrypted,rule_version,job_id))
        workflow_status = 'pending_review' if status == 'done' else 'failed'
        c.execute('UPDATE contract_cases SET status=?,current_stage=?,updated_at=? WHERE job_id=?',
                  (workflow_status, 'legal_review' if status == 'done' else 'cancelled', now, job_id))
        if old and old['case_id']:
            still_running = c.execute('''SELECT COUNT(*) AS n FROM case_documents d JOIN reviews rr ON rr.id=d.job_id
                                         WHERE d.case_id=? AND rr.status='running' ''', (old['case_id'],)).fetchone()['n']
            case_stage = ('ai_review' if still_running else 'legal_review') if status == 'done' else 'cancelled'
            case_status = 'running' if case_stage == 'ai_review' else workflow_status
            c.execute('UPDATE contract_cases SET status=?,current_stage=?,updated_at=? WHERE case_id=?',
                      (case_status, case_stage, now, old['case_id']))
            if status == 'done':
                if not still_running:
                    existing_task = c.execute("SELECT 1 FROM workflow_tasks WHERE case_id=? AND task_type='legal_review' AND status='open'", (old['case_id'],)).fetchone()
                    if not existing_task:
                        _task(c, old['case_id'], 'legal_review', '信用审核专员复核 AI 审查结果', '请确认风险处置、补件或例外审批路径。', None, actor)
                    _case_event(c, old['case_id'], 'review.completed', '文件包 AI 审查已完成，已进入信用审核专员复核。', actor, {'job_id': job_id})
                else:
                    _case_event(c, old['case_id'], 'review.document_completed', '一份文件已完成审查，正在等待同案其余文件。', actor, {'job_id': job_id, 'remaining': still_running})
        if status=='done':
            c.execute('DELETE FROM review_findings WHERE job_id=?',(job_id,))
            c.execute('DELETE FROM finding_approvals WHERE job_id=?',(job_id,))
            c.execute('DELETE FROM material_requests WHERE job_id=?',(job_id,))
            from .services.rules import RULE_BY_ID
            effective_rules = rules_by_id or RULE_BY_ID
            for risk in report.get('risks',[]) or []:
                fid='RF-'+uuid.uuid4().hex[:16].upper(); risk['finding_id']=fid; risk['rule_version']=rule_version
                c.execute('INSERT INTO review_findings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (fid,job_id,risk.get('clause_id'),risk.get('page'),risk.get('rule_id'),rule_version,risk.get('severity'),risk.get('level'),risk.get('rule_baseline'),risk.get('evidence'),risk.get('numeric_note'),risk.get('suggestion'),risk.get('decision_source'),'pending',now,now))
                required_role = effective_rules.get(risk.get('rule_id'), {}).get('approval_role')
                if required_role:
                    c.execute('INSERT INTO finding_approvals VALUES (?,?,?,?,?,?,?,?,?)',
                              (uuid.uuid4().hex, fid, job_id, required_role, 'pending', '', None, now, None))
            for hint in report.get('review_hints',[]) or []:
                c.execute('INSERT INTO material_requests VALUES (?,?,?,?,?,?,?,?,?,?)',
                          (uuid.uuid4().hex, job_id, None, f"补充核验材料：{hint.get('rule_id', '风险条款')}",
                           hint.get('suggestion') or '请补充合同附件、审批记录或可确认责任主体的材料。',
                           'open', (actor or {}).get('id'), None, now, None))
    if mapping: save_mask_mapping(job_id,mapping,actor)

def _decode_report(row):
    d=dict(row); protected=d.pop('report_encrypted',None)
    if not protected:
        d['report']={}
        return d
    d['report']=decrypt_json(protected)
    return d

def list_history(limit=50, offset=0):
    init_db()
    with _lock, _conn() as c:
        rows=c.execute('''SELECT id,filename,status,created_at,finished_at,overall_level,n_clauses,n_risks,high,mid,low,masked_entities,our_party,business_type,case_id,created_by FROM reviews ORDER BY created_at DESC LIMIT ? OFFSET ?''',(limit,offset)).fetchall()
        return [dict(r) for r in rows]

CASE_STATUSES = {'running', 'pending_review', 'in_review', 'returned', 'approved', 'closed', 'failed'}
CASE_PRIORITIES = {'low', 'normal', 'high', 'urgent'}

def list_reviewers():
    with _lock, _conn() as c:
        rows = c.execute("SELECT id,display_name,role FROM users WHERE active=1 AND role IN ('admin','reviewer') ORDER BY display_name").fetchall()
        return [dict(r) for r in rows]

def list_cases(actor: dict, limit=100):
    init_db()
    with _lock, _conn() as c:
        where = ''
        params: list[Any] = []
        if actor.get('role') == 'business':
            where = 'WHERE c.created_by=?'
            params.append(actor.get('id'))
        rows = c.execute(f'''SELECT c.case_id,c.job_id,c.status AS workflow_status,c.priority,c.due_at,c.request_note,c.created_by,c.created_at,c.updated_at,
                                    c.assigned_to,r.filename,r.status AS review_status,r.overall_level,r.n_clauses,r.n_risks,r.high,r.mid,r.low,
                                    creator.display_name AS requester_name, assignee.display_name AS assignee_name
                             FROM contract_cases c
                             JOIN reviews r ON r.id=c.job_id
                             LEFT JOIN users creator ON creator.id=c.created_by
                             LEFT JOIN users assignee ON assignee.id=c.assigned_to
                             {where} ORDER BY CASE c.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, c.updated_at DESC LIMIT ?''', (*params, limit)).fetchall()
        return [dict(r) for r in rows]

def update_case(job_id: str, body: dict, actor: dict):
    allowed = {'assigned_to', 'priority', 'due_at', 'request_note', 'status'}
    changes = {key: value for key, value in body.items() if key in allowed}
    if not changes: raise ValueError('没有可更新的案件字段')
    if 'priority' in changes and changes['priority'] not in CASE_PRIORITIES: raise ValueError('不支持的优先级')
    if 'status' in changes and changes['status'] not in CASE_STATUSES: raise ValueError('不支持的案件状态')
    if 'assigned_to' in changes and changes['assigned_to']:
        reviewer = get_user(changes['assigned_to'])
        if not reviewer or not reviewer.get('active') or reviewer.get('role') not in {'admin','reviewer'}: raise ValueError('只能指派给启用的信用审核专员')
    if 'request_note' in changes: changes['request_note'] = str(changes['request_note'] or '').strip()[:1000]
    fields=[]; values=[]
    for key, value in changes.items():
        fields.append(f'{key}=?'); values.append(value or None if key == 'assigned_to' else value)
    fields.append('updated_at=?'); values.append(time.time()); values.append(job_id)
    with _lock, _conn() as c:
        c.execute(f'UPDATE contract_cases SET {",".join(fields)} WHERE job_id=?', values)
        if c.total_changes == 0: raise ValueError('案件不存在')
    return get_case(job_id)

def get_case(job_id: str):
    cases = [row for row in list_cases({'role': 'admin'}, 500) if row['job_id'] == job_id]
    return cases[0] if cases else None

def get_review(job_id):
    init_db()
    with _lock, _conn() as c:
        r=c.execute('SELECT * FROM reviews WHERE id=?',(job_id,)).fetchone()
        return _decode_report(r) if r else None

def list_findings(job_id):
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute('SELECT * FROM review_findings WHERE job_id=? ORDER BY CASE severity WHEN "high" THEN 0 WHEN "mid" THEN 1 ELSE 2 END, page',(job_id,))]

def list_approvals(job_id: str, actor: dict | None=None):
    with _lock, _conn() as c:
        where = 'WHERE job_id=?'; values = [job_id]
        if actor and actor.get('role') == 'director':
            where += ' AND required_role=?'; values.append(actor['role'])
        return [dict(r) for r in c.execute(f'SELECT * FROM finding_approvals {where} ORDER BY created_at', values)]

def decide_approval(job_id: str, approval_id: str, decision: str, note: str, actor: dict):
    if decision not in {'approved', 'rejected', 'changes_requested'}:
        raise ValueError('审批决定无效')
    if not note.strip():
        raise ValueError('请填写审批意见')
    with _lock, _conn() as c:
        row = c.execute('SELECT * FROM finding_approvals WHERE approval_id=? AND job_id=?', (approval_id, job_id)).fetchone()
        if not row:
            raise ValueError('审批任务不存在')
        if actor.get('role') not in {'admin', row['required_role']}:
            raise ValueError('当前角色无权处理该审批')
        now = time.time()
        c.execute('UPDATE finding_approvals SET status=?,decision_note=?,actor_id=?,decided_at=? WHERE approval_id=?',
                  (decision, note.strip(), actor.get('id'), now, approval_id))
        finding_status = 'approved' if decision == 'approved' else ('returned' if decision == 'changes_requested' else 'rejected')
        c.execute('UPDATE review_findings SET action_status=?,updated_at=? WHERE finding_id=?', (finding_status, now, row['finding_id']))
    return {'approval_id': approval_id, 'status': decision}

def list_material_requests(job_id: str):
    with _lock, _conn() as c:
        items = [dict(r) for r in c.execute('SELECT * FROM material_requests WHERE job_id=? ORDER BY CASE status WHEN "open" THEN 0 ELSE 1 END, created_at', (job_id,))]
        for item in items:
            item['files'] = [dict(row) for row in c.execute('SELECT file_id,original_name,created_at FROM material_files WHERE request_id=? ORDER BY created_at', (item['request_id'],))]
        return items

def add_material_file(job_id: str, request_id: str, original_name: str, stored_path: str, actor: dict):
    with _lock, _conn() as c:
        request = c.execute('SELECT request_id FROM material_requests WHERE request_id=? AND job_id=?', (request_id, job_id)).fetchone()
        if not request:
            raise ValueError('待补材料不存在')
        file_id = uuid.uuid4().hex
        c.execute('INSERT INTO material_files VALUES (?,?,?,?,?,?,?)',
                  (file_id, request_id, job_id, original_name, stored_path, actor.get('id'), time.time()))
    return {'file_id': file_id, 'original_name': original_name}

def get_material_file(job_id: str, request_id: str, file_id: str):
    with _lock, _conn() as c:
        row = c.execute('SELECT * FROM material_files WHERE file_id=? AND request_id=? AND job_id=?', (file_id, request_id, job_id)).fetchone()
        return dict(row) if row else None

def record_export_snapshot(job_id: str, mode: str, output_path: str, actor: dict, approvals: list[dict], findings: list[dict]):
    snapshot = {
        'export_id': 'EXP-' + uuid.uuid4().hex[:16].upper(), 'job_id': job_id, 'mode': mode,
        'output_path': output_path, 'exported_by': actor.get('id'), 'created_at': time.time(),
    }
    with _lock, _conn() as c:
        c.execute('INSERT INTO export_snapshots VALUES (?,?,?,?,?,?,?,?)',
                  (snapshot['export_id'], job_id, mode, output_path,
                   json.dumps(approvals, ensure_ascii=False), json.dumps(findings, ensure_ascii=False),
                   actor.get('id'), snapshot['created_at']))
    return snapshot

def list_export_snapshots(job_id: str):
    with _lock, _conn() as c:
        return [dict(row) for row in c.execute('SELECT export_id,job_id,mode,exported_by,created_at FROM export_snapshots WHERE job_id=? ORDER BY created_at DESC', (job_id,))]

def resolve_material_request(job_id: str, request_id: str, note: str, actor: dict):
    with _lock, _conn() as c:
        row = c.execute('SELECT request_id FROM material_requests WHERE request_id=? AND job_id=?', (request_id, job_id)).fetchone()
        if not row:
            raise ValueError('待补材料不存在')
        c.execute('UPDATE material_requests SET status=?,detail=?,resolved_by=?,resolved_at=? WHERE request_id=?',
                  ('resolved', note.strip() or '已补充并确认', actor.get('id'), time.time(), request_id))
    return {'request_id': request_id, 'status': 'resolved'}

def list_knowledge(rule_id='', limit=3):
    with _lock, _conn() as c:
        if rule_id:
            rows = c.execute('SELECT * FROM clause_knowledge WHERE rule_id=? ORDER BY created_at DESC LIMIT ?', (rule_id, limit)).fetchall()
        else:
            rows = c.execute('SELECT * FROM clause_knowledge ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows]

def similar_knowledge(job_id: str, finding_id: str, limit=3):
    """Return prior human-adopted examples relevant to this finding and business type."""
    with _lock, _conn() as c:
        finding = c.execute('SELECT rule_id FROM review_findings WHERE finding_id=? AND job_id=?', (finding_id, job_id)).fetchone()
        review = c.execute('SELECT business_type FROM reviews WHERE id=?', (job_id,)).fetchone()
        if not finding:
            raise ValueError('风险项不存在')
        business_type = (review['business_type'] if review else '') or ''
        rows = c.execute('''SELECT * FROM clause_knowledge
                          WHERE rule_id=? AND (business_type=? OR business_type='' OR ?='')
                          ORDER BY created_at DESC LIMIT ?''',
                         (finding['rule_id'], business_type, business_type, min(max(limit, 1), 3))).fetchall()
        return [dict(row) for row in rows]

def purge_knowledge_by_source(source_clause: str):
    """Test-only cleanup helper; production cases are intentionally retained as knowledge."""
    with _lock, _conn() as c:
        c.execute('DELETE FROM clause_knowledge WHERE source_clause=?', (source_clause,))

def compare_reviews(job_id: str, baseline_job_id: str):
    current = get_review(job_id)
    baseline = get_review(baseline_job_id)
    if not current or not baseline:
        raise ValueError('待比较的合同版本不存在')
    current_rules = {x.get('rule_id') for x in current.get('report', {}).get('risks', []) if x.get('rule_id')}
    baseline_rules = {x.get('rule_id') for x in baseline.get('report', {}).get('risks', []) if x.get('rule_id')}
    current_clauses = {x.get('id'): x.get('text', '') for x in current.get('report', {}).get('clauses', [])}
    baseline_clauses = {x.get('id'): x.get('text', '') for x in baseline.get('report', {}).get('clauses', [])}
    changed = [key for key in sorted(set(current_clauses) | set(baseline_clauses)) if current_clauses.get(key) != baseline_clauses.get(key)]
    result = {
        'job_id': job_id, 'baseline_job_id': baseline_job_id,
        'new_risks': sorted(current_rules - baseline_rules),
        'resolved_risks': sorted(baseline_rules - current_rules),
        'persisting_risks': sorted(current_rules & baseline_rules),
        'changed_clauses': changed,
        'review_scope': current.get('report', {}).get('review_scope', {}),
    }
    with _lock, _conn() as c:
        c.execute('UPDATE contract_versions SET parent_job_id=?,compare_json=? WHERE job_id=?',
                  (baseline_job_id, json.dumps(result, ensure_ascii=False), job_id))
    return result

def batch_matrix(actor: dict):
    with _lock, _conn() as c:
        query = '''SELECT r.id,r.filename,r.overall_level,r.high,r.mid,c.priority,c.due_at,
                          GROUP_CONCAT(DISTINCT f.rule_id) AS rule_ids
                   FROM reviews r JOIN contract_cases c ON c.job_id=r.id
                   LEFT JOIN review_findings f ON f.job_id=r.id'''
        params = []
        if actor.get('role') == 'business':
            query += ' WHERE c.created_by=?'; params.append(actor.get('id'))
        query += ' GROUP BY r.id ORDER BY r.created_at DESC LIMIT 100'
        rows = []
        for row in c.execute(query, params):
            item = dict(row); item['rule_ids'] = (item.get('rule_ids') or '').split(',') if item.get('rule_ids') else []
            rows.append(item)
        return rows

def record_finding_action(job_id: str, finding_id: str, action: str, reason: str, actor: dict, edited_suggestion=''):
    if action not in ('adopt','ignore','edit','approve','reject'): raise ValueError('不支持的处置动作')
    if not reason.strip(): raise ValueError('请填写处置理由')
    with _lock, _conn() as c:
        f=c.execute('SELECT * FROM review_findings WHERE finding_id=? AND job_id=?',(finding_id,job_id)).fetchone()
        if not f: raise ValueError('风险项不存在')
        if str(f['rule_id'] or '').startswith('CREDIT_'):
            raise ValueError('信审越界不可在合同端采纳、忽略或审批；请先更新信审条件并重新发起合同复审')
        now=time.time(); status={'adopt':'adopted','ignore':'ignored','edit':'edited','approve':'approved','reject':'rejected'}[action]
        c.execute('INSERT INTO review_actions VALUES (?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,finding_id,action,reason.strip(),edited_suggestion,(actor or {}).get('id'),(actor or {}).get('role'),now))
        c.execute('UPDATE review_findings SET action_status=?,suggestion=COALESCE(NULLIF(?,""),suggestion),updated_at=? WHERE finding_id=?',(status,edited_suggestion,now,finding_id))
        if action in {'adopt', 'edit'}:
            report_row = c.execute('SELECT business_type,report_encrypted FROM reviews WHERE id=?', (job_id,)).fetchone()
            source_clause = ''
            source_ref = ''
            if report_row and report_row['report_encrypted']:
                try:
                    report = decrypt_json(report_row['report_encrypted'])
                    clause = next((x for x in report.get('clauses', []) if x.get('id') == f['clause_id']), {})
                    source_clause, source_ref = clause.get('text', ''), clause.get('source_ref', '')
                except Exception:
                    pass
            c.execute('INSERT INTO clause_knowledge VALUES (?,?,?,?,?,?,?,?,?,?)',
                      (uuid.uuid4().hex, f['rule_id'], report_row['business_type'] if report_row else '', source_clause,
                       source_ref, f['evidence'], edited_suggestion or f['suggestion'], status, actor.get('id'), now))
    return get_finding(finding_id)

def get_finding(finding_id):
    with _lock, _conn() as c:
        r=c.execute('SELECT * FROM review_findings WHERE finding_id=?',(finding_id,)).fetchone()
        if not r:return None
        d=dict(r); d['actions']=[dict(x) for x in c.execute('SELECT * FROM review_actions WHERE finding_id=? ORDER BY created_at',(finding_id,))]; return d

def delete_review(job_id):
    init_db()
    with _lock, _conn() as c:
        r=c.execute('SELECT file_path FROM reviews WHERE id=?',(job_id,)).fetchone(); fp=r['file_path'] if r else None
        material_paths = [row['stored_path'] for row in c.execute('SELECT stored_path FROM material_files WHERE job_id=?', (job_id,))]
        c.execute('DELETE FROM review_actions WHERE finding_id IN (SELECT finding_id FROM review_findings WHERE job_id=?)',(job_id,)); c.execute('DELETE FROM finding_approvals WHERE job_id=?',(job_id,)); c.execute('DELETE FROM material_files WHERE job_id=?',(job_id,)); c.execute('DELETE FROM material_requests WHERE job_id=?',(job_id,)); c.execute('DELETE FROM export_snapshots WHERE job_id=?',(job_id,)); c.execute('DELETE FROM contract_versions WHERE job_id=?',(job_id,)); c.execute('DELETE FROM review_findings WHERE job_id=?',(job_id,)); c.execute('DELETE FROM mask_mappings WHERE task_id=?',(job_id,)); c.execute('DELETE FROM contract_cases WHERE job_id=?',(job_id,)); c.execute('DELETE FROM reviews WHERE id=?',(job_id,))
    if fp and os.path.exists(fp):
        try: os.remove(fp)
        except OSError: pass
    for material_path in material_paths:
        if material_path and os.path.exists(material_path):
            try: os.remove(material_path)
            except OSError: pass

def stats(actor: dict | None=None):
    init_db()
    with _lock, _conn() as c:
        where = ''
        params: list[Any] = []
        if actor and actor.get('role') == 'business':
            where = ' WHERE created_by=?'
            params.append(actor.get('id'))
        def scalar(q, values=()): return c.execute(q, values).fetchone()['v']
        rules_freq={}
        for row in c.execute('SELECT rule_id,COUNT(*) n FROM review_findings GROUP BY rule_id ORDER BY n DESC LIMIT 10'): rules_freq[row['rule_id']]=row['n']
        review_where = where.replace('created_by', 'r.created_by')
        return {'total':scalar(f'SELECT COUNT(*) v FROM reviews r{review_where}', params),'done':scalar(f"SELECT COUNT(*) v FROM reviews r{review_where}{' AND' if review_where else ' WHERE'} r.status='done'", params),'blocked':scalar(f"SELECT COUNT(*) v FROM reviews r{review_where}{' AND' if review_where else ' WHERE'} r.overall_level LIKE '阻断%'", params),'high':scalar(f'SELECT COALESCE(SUM(r.high),0) v FROM reviews r{review_where}', params),'mid':scalar(f'SELECT COALESCE(SUM(r.mid),0) v FROM reviews r{review_where}', params),'clauses':scalar(f'SELECT COALESCE(SUM(r.n_clauses),0) v FROM reviews r{review_where}', params),'rules_freq':rules_freq,'open_actions':scalar("SELECT COUNT(*) v FROM review_findings WHERE action_status='pending'"),'my_open': scalar("SELECT COUNT(*) v FROM contract_cases WHERE (assigned_to=? OR created_by=?) AND status IN ('running','pending_review','in_review','returned')", ((actor or {}).get('id'), (actor or {}).get('id'))),'unassigned':scalar("SELECT COUNT(*) v FROM contract_cases WHERE assigned_to IS NULL AND status='pending_review'"),'due_soon':scalar("SELECT COUNT(*) v FROM contract_cases WHERE due_at IS NOT NULL AND due_at BETWEEN ? AND ? AND status NOT IN ('approved','closed','failed')", (time.time(), time.time()+48*3600))}

def save_translation(job_id: str, target_lang: str, result: dict | None, status: str, actor: dict | None=None, error: str=''):
    """Persist a finished (or failed) privacy-preserving translation for export reuse."""
    init_db(); now = time.time()
    encrypted = encrypt_json(result or {}) if result is not None else None
    with _lock, _conn() as c:
        c.execute('''INSERT INTO translations(job_id,target_lang,status,result_encrypted,error,created_by,created_at,updated_at)
                     VALUES(?,?,?,?,?,?,?,?)
                     ON CONFLICT(job_id,target_lang) DO UPDATE SET
                       status=excluded.status, result_encrypted=excluded.result_encrypted,
                       error=excluded.error, updated_at=excluded.updated_at''',
                  (job_id, target_lang, status, encrypted, error or '', (actor or {}).get('id'), now, now))

def get_translation(job_id: str, target_lang: str) -> dict | None:
    init_db()
    with _lock, _conn() as c:
        row = c.execute('SELECT job_id,target_lang,status,result_encrypted,error,created_at,updated_at FROM translations WHERE job_id=? AND target_lang=?',
                        (job_id, target_lang)).fetchone()
    if not row:
        return None
    item = dict(row)
    blob = item.pop('result_encrypted', None)
    item['result'] = decrypt_json(blob) if blob else None
    return item

def list_translations(job_id: str) -> list[dict]:
    init_db()
    with _lock, _conn() as c:
        rows = c.execute('SELECT job_id,target_lang,status,error,created_at,updated_at FROM translations WHERE job_id=? ORDER BY updated_at DESC',
                         (job_id,)).fetchall()
    return [dict(r) for r in rows]

def add_case_attachment(job_id: str, original_name: str, stored_path: str, actor: dict | None, role: str='annex', preview: list | None=None) -> dict:
    init_db(); now = time.time(); file_id = 'ATT-' + uuid.uuid4().hex[:12].upper()
    with _lock, _conn() as c:
        c.execute('INSERT INTO case_attachments VALUES (?,?,?,?,?,?,?,?)',
                  (file_id, job_id, original_name, stored_path, role or 'annex',
                   json.dumps(preview or [], ensure_ascii=False), (actor or {}).get('id'), now))
    return get_case_attachment(job_id, file_id) or {'file_id': file_id, 'job_id': job_id, 'original_name': original_name, 'role': role}

def list_case_attachments(job_id: str) -> list[dict]:
    init_db()
    with _lock, _conn() as c:
        rows = c.execute('SELECT file_id,job_id,original_name,role,preview_json,uploaded_by,created_at FROM case_attachments WHERE job_id=? ORDER BY created_at',
                         (job_id,)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item['preview'] = json.loads(item.pop('preview_json') or '[]')
        except json.JSONDecodeError:
            item['preview'] = []
        out.append(item)
    return out

def get_case_attachment(job_id: str, file_id: str) -> dict | None:
    init_db()
    with _lock, _conn() as c:
        row = c.execute('SELECT file_id,job_id,original_name,stored_path,role,preview_json,uploaded_by,created_at FROM case_attachments WHERE job_id=? AND file_id=?',
                        (job_id, file_id)).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item['preview'] = json.loads(item.pop('preview_json') or '[]')
    except json.JSONDecodeError:
        item['preview'] = []
    return item

def list_audit(limit=100):
    with _lock,_conn() as c:
        rows=c.execute('SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?',(limit,)).fetchall()
        return [{**dict(r),'metadata':json.loads(r['metadata_json'] or '{}')} for r in rows]
