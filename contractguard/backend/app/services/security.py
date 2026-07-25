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

ROLES = ('admin', 'credit', 'legal', 'director', 'ceo', 'business')
ROLE_LABELS = {
    'admin': '管理员', 'credit': '信审人员', 'legal': '法务',
    'director': '总监', 'ceo': 'CEO', 'business': '业务人员',
}
PERMISSIONS = {
    'admin': {'*'},
    'credit': {'credit:create', 'credit:read', 'credit:manage'},
    'legal': {'review:create', 'review:read', 'review:action', 'review:manage', 'export', 'credit:read'},
    'director': {'review:read', 'review:action', 'review:manage', 'export', 'credit:read'},
    'ceo': {'review:read', 'review:action', 'review:manage', 'export', 'credit:read'},
    'business': {'review:create', 'review:read', 'credit:read'},
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
