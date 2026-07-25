"""SQLite repository for the single-node contract review workspace."""
from __future__ import annotations

import json
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
        CREATE INDEX IF NOT EXISTS idx_translations_job ON translations(job_id);
        CREATE INDEX IF NOT EXISTS idx_attachments_job ON case_attachments(job_id);
        ''')
        _add_column(c, 'reviews', 'report_encrypted BLOB')
        _add_column(c, 'reviews', 'case_id TEXT')
        _add_column(c, 'reviews', 'created_by TEXT')
        _add_column(c, 'reviews', 'rule_version TEXT')
        _add_column(c, 'reviews', 'credit_case_id TEXT')
        _add_column(c, 'reviews', 'credit_version INTEGER')
        _add_column(c, 'reviews', "credit_snapshot_json TEXT NOT NULL DEFAULT '{}'")
        for definition in ('assigned_to TEXT', "priority TEXT NOT NULL DEFAULT 'normal'", 'due_at REAL', "request_note TEXT NOT NULL DEFAULT ''"):
            _add_column(c, 'contract_cases', definition)
    _seed_initial_admin()
    _seed_rule_catalog()

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
    return item

def _customer_key(customer_name: str) -> str:
    key = ''.join((customer_name or '').strip().lower().split())
    if len(key) < 2:
        raise ValueError('客户名称至少需要 2 个字符')
    return key[:200]

def list_credit_cases(customer: str='', active_only: bool=False) -> list[dict]:
    init_db()
    sql = 'SELECT * FROM credit_cases'
    args: list[Any] = []
    where = []
    if customer.strip():
        where.append('customer_name LIKE ?'); args.append(f'%{customer.strip()}%')
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

def create_credit_case(customer_name: str, conditions: dict, request_note: str, actor: dict) -> dict:
    from .services.credit import normalize_conditions
    customer_name = (customer_name or '').strip()
    key = _customer_key(customer_name)
    normal = normalize_conditions(conditions)
    now = time.time(); case_id = 'CREDIT-' + uuid.uuid4().hex[:12].upper()
    with _lock, _conn() as c:
        row = c.execute('SELECT COALESCE(MAX(version), 0) AS v FROM credit_cases WHERE customer_key=?', (key,)).fetchone()
        version = int(row['v']) + 1
        c.execute('''INSERT INTO credit_cases(case_id,customer_key,customer_name,version,status,conditions_json,request_note,decision_note,created_by,created_at,updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                  (case_id, key, customer_name, version, 'draft', json.dumps(normal, ensure_ascii=False),
                   (request_note or '').strip()[:2000], '', actor.get('id'), now, now))
    return get_credit_case(case_id)

def update_credit_case(case_id: str, conditions: dict, request_note: str, actor: dict) -> dict:
    from .services.credit import normalize_conditions
    normal = normalize_conditions(conditions)
    with _lock, _conn() as c:
        row = c.execute('SELECT status FROM credit_cases WHERE case_id=?', (case_id,)).fetchone()
        if not row:
            raise ValueError('信审案件不存在')
        if row['status'] != 'draft':
            raise ValueError('仅草稿信审案件可修改；放宽条件请新建信审版本')
        c.execute('UPDATE credit_cases SET conditions_json=?,request_note=?,updated_at=? WHERE case_id=?',
                  (json.dumps(normal, ensure_ascii=False), (request_note or '').strip()[:2000], time.time(), case_id))
    return get_credit_case(case_id)

def submit_credit_case(case_id: str, actor: dict) -> dict:
    with _lock, _conn() as c:
        row = c.execute('SELECT status FROM credit_cases WHERE case_id=?', (case_id,)).fetchone()
        if not row:
            raise ValueError('信审案件不存在')
        if row['status'] != 'draft':
            raise ValueError('仅草稿信审案件可提交')
        now = time.time()
        c.execute("UPDATE credit_cases SET status='pending_approval',submitted_at=?,updated_at=? WHERE case_id=?", (now, now, case_id))
    return get_credit_case(case_id)

def decide_credit_case(case_id: str, decision: str, note: str, actor: dict) -> dict:
    if decision not in {'approved', 'rejected'}:
        raise ValueError('信审决定仅支持 approved 或 rejected')
    if not (note or '').strip():
        raise ValueError('请填写信审审批意见')
    with _lock, _conn() as c:
        case = c.execute('SELECT * FROM credit_cases WHERE case_id=?', (case_id,)).fetchone()
        if not case:
            raise ValueError('信审案件不存在')
        if case['status'] != 'pending_approval':
            raise ValueError('仅待审批信审案件可作出决定')
        now = time.time()
        if decision == 'approved':
            # A newly approved version supersedes the older decision.  Contract
            # reviews must be rerun against this new snapshot before signature.
            c.execute("UPDATE credit_cases SET status='superseded',updated_at=? WHERE customer_key=? AND status='approved'", (now, case['customer_key']))
        c.execute('UPDATE credit_cases SET status=?,decision_note=?,decided_by=?,decided_at=?,updated_at=? WHERE case_id=?',
                  (decision, note.strip()[:2000], actor.get('id'), now, now, case_id))
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
    if display_name is not None: fields.append('display_name=?'); values.append(display_name.strip())
    if role is not None:
        if role not in ROLES: raise ValueError('不支持的角色')
        fields.append('role=?'); values.append(role)
    if active is not None: fields.append('active=?'); values.append(1 if active else 0)
    if password is not None: fields.append('password_hash=?'); values.append(password_hash(password))
    if not fields: return get_user(user_id)
    fields.append('updated_at=?'); values.append(time.time()); values.append(user_id)
    with _lock, _conn() as c: c.execute(f'UPDATE users SET {",".join(fields)} WHERE id=?', values)
    return get_user(user_id)

# ---- review persistence, protected mapping, actions ----
def create_pending(job_id, filename, path, actor=None, business_type='', assignee_id='', priority='normal', due_at=None, request_note='', parent_job_id='', rule_version='contract-v1', credit_case=None):
    init_db(); now=time.time(); case_id='CASE-'+uuid.uuid4().hex[:12].upper()
    if not credit_case:
        raise ValueError('合同必须绑定已生效的信审版本')
    credit_snapshot = {
        'case_id': credit_case['case_id'], 'customer_name': credit_case['customer_name'],
        'version': credit_case['version'], 'conditions': credit_case['conditions'],
        'approved_at': credit_case.get('decided_at'),
    }
    with _lock, _conn() as c:
        c.execute('''INSERT OR REPLACE INTO reviews(id,filename,status,created_at,finished_at,overall_level,n_clauses,n_risks,high,mid,low,masked_entities,our_party,business_type,report_encrypted,file_path,case_id,created_by,rule_version,credit_case_id,credit_version,credit_snapshot_json)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (job_id,filename,'running',now,0,'',0,0,0,0,0,0,'',business_type,None,path,case_id,(actor or {}).get('id'),rule_version,credit_case['case_id'],credit_case['version'],json.dumps(credit_snapshot, ensure_ascii=False)))
        c.execute('''INSERT INTO contract_cases(case_id,job_id,business_type,status,created_by,created_at,updated_at,assigned_to,priority,due_at,request_note)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                  (case_id,job_id,business_type,'running',(actor or {}).get('id'),now,now,assignee_id or None,priority,due_at,request_note.strip()))
        parent = parent_job_id or None
        version = 'V1'
        if parent:
            n = c.execute('SELECT COUNT(*) AS n FROM contract_versions WHERE parent_job_id=? OR job_id=?', (parent, parent)).fetchone()['n']
            version = f'V{n + 1}'
        c.execute('INSERT OR REPLACE INTO contract_versions(job_id,parent_job_id,version_label,compare_json,created_at) VALUES (?,?,?,?,?)',
                  (job_id, parent, version, '{}', now))
    return case_id

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
        c.execute('UPDATE contract_cases SET status=?,updated_at=? WHERE job_id=?',(workflow_status,now,job_id))
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
        rows = c.execute("SELECT id,display_name,role FROM users WHERE active=1 AND role IN ('admin','legal') ORDER BY display_name").fetchall()
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
        if not reviewer or not reviewer.get('active') or reviewer.get('role') not in {'admin','legal'}: raise ValueError('只能指派给启用的法务成员')
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
        if actor and actor.get('role') in {'ceo', 'director'}:
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
