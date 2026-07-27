"""Authentication, RBAC and encrypted-at-rest helpers.

The data-encryption key must be a Fernet key in production.  This service
never falls back to an embedded key, so an incorrectly configured deployment
cannot silently persist sensitive mappings in clear text.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken

from ..config import ACCESS_TOKEN_MINUTES, AUTH_SECRET, DATA_ENCRYPTION_KEY

"""The demo follows Dongjiang's documented approval ladder:
business applicant -> credit reviewer -> finance approval manager -> group CFO.

`admin` intentionally remains the technical superuser because it also owns
system configuration, but is presented to users as the Group CFO / final
approver rather than a generic administrator.
"""
ROLES = ('admin', 'director', 'reviewer', 'business')
ROLE_LABELS = {
    'admin': '集团财务总监 / 最终审批人',
    'director': '财务审批主管',
    'reviewer': '信用审核专员',
    'business': '业务申请人',
}
PERMISSIONS = {
    'admin': {'*'},
    # The credit reviewer investigates, makes recommendations and performs
    # contract first review.  It may never approve its own credit decision.
    'reviewer': {'credit:create', 'credit:read', 'credit:manage',
                 'review:create', 'review:read', 'review:action', 'review:manage', 'export'},
    # The finance approval manager performs the second-level credit approval
    # and contract-exception approval; Group CFO handles final exceptions.
    'director': {'review:read', 'review:action', 'review:manage', 'export', 'credit:read', 'credit:approve'},
    # The applicant can open a credit application, but cannot edit the
    # assessed terms or send it into the finance approval chain.
    'business': {'review:create', 'review:read', 'credit:create', 'credit:read'},
}

def password_hash(password: str) -> str:
    if not password or len(password) < 10:
        raise ValueError('密码至少需要 10 个字符')
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2**14, r=8, p=1)
    return f'scrypt$16384$8$1${salt.hex()}${digest.hex()}'

def verify_password(password: str, encoded: str) -> bool:
    try:
        kind, n, r, p, salt_hex, digest_hex = encoded.split('$')
        if kind != 'scrypt': return False
        calc = hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(calc, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False

def issue_token(user: dict[str, Any]) -> str:
    if not AUTH_SECRET:
        raise RuntimeError('AUTH_SECRET 未配置，拒绝签发登录令牌')
    now = datetime.now(timezone.utc)
    payload = {'sub': user['id'], 'username': user['username'], 'role': user['role'],
               'iat': now, 'exp': now + timedelta(minutes=ACCESS_TOKEN_MINUTES)}
    return jwt.encode(payload, AUTH_SECRET, algorithm='HS256')

def parse_token(token: str) -> dict[str, Any]:
    if not AUTH_SECRET:
        raise ValueError('AUTH_SECRET 未配置')
    return jwt.decode(token, AUTH_SECRET, algorithms=['HS256'])

def can(role: str, permission: str) -> bool:
    grants = PERMISSIONS.get(role, set())
    return '*' in grants or permission in grants

def _fernet() -> Fernet:
    if not DATA_ENCRYPTION_KEY:
        raise RuntimeError('DATA_ENCRYPTION_KEY 未配置，拒绝持久化敏感映射')
    try:
        return Fernet(DATA_ENCRYPTION_KEY.encode('utf-8'))
    except Exception as e:
        raise RuntimeError('DATA_ENCRYPTION_KEY 必须是有效 Fernet 密钥') from e

def encrypt_json(value: Any) -> bytes:
    import json
    return _fernet().encrypt(json.dumps(value, ensure_ascii=False).encode('utf-8'))

def decrypt_json(value: bytes | str) -> Any:
    import json
    raw = value.encode('utf-8') if isinstance(value, str) else value
    try:
        return json.loads(_fernet().decrypt(raw).decode('utf-8'))
    except InvalidToken as e:
        raise ValueError('加密数据无法解密') from e
