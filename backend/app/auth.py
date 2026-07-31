"""FastAPI auth dependencies and administrative routes."""
from __future__ import annotations

import time
from pathlib import Path

import httpx
from dotenv import unset_key
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import store
from .config import (
    LEGACY_MODEL_ENV_KEYS, MODEL_RUNTIME_CONFIG_PATH, MODEL_RUNTIME_CONFIG_SCHEMA_VERSION,
    get_model_runtime_config, update_model_runtime_config,
)
from .services.security import ROLE_LABELS, ROLES, can, issue_token, parse_token

bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix='/api', tags=['identity'])

def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    token = credentials.credentials if credentials else request.query_params.get('access_token', '')
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, '需要登录')
    try:
        claims=parse_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, '登录已过期或无效')
    user=store.get_user(claims.get('sub',''))
    if not user or not user.get('active'):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, '用户不存在或已停用')
    return user

def require(permission: str):
    def dep(user=Depends(current_user)):
        if not can(user['role'],permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f'当前角色无 {permission} 权限')
        return user
    return dep

class LoginIn(BaseModel):
    username: str
    password: str

class UserIn(BaseModel):
    username: str = Field(min_length=3,max_length=80)
    display_name: str = Field(min_length=1,max_length=80)
    role: str
    password: str = Field(min_length=10,max_length=256)

class UserPatch(BaseModel):
    display_name: str | None = Field(default=None,max_length=80)
    role: str | None = None
    active: bool | None = None
    password: str | None = Field(default=None,min_length=10,max_length=256)


class SettingsPatch(BaseModel):
    llm_api_base: str | None = Field(default=None, max_length=500)
    llm_api_key: str | None = Field(default=None, max_length=500)
    llm_model: str | None = Field(default=None, max_length=200)
    ollama_base: str | None = Field(default=None, max_length=500)
    enable_masking: bool | None = None
    smart_mask: bool | None = None
    mask_llm_api_base: str | None = Field(default=None, max_length=500)
    mask_llm_api_key: str | None = Field(default=None, max_length=500)
    mask_llm_model: str | None = Field(default=None, max_length=200)
    financial_llm_extraction: bool | None = None
    financial_llm_mode: str | None = Field(default=None, pattern='^(remote_substitute|local_or_intranet)$')
    financial_llm_api_base: str | None = Field(default=None, max_length=500)
    financial_llm_api_key: str | None = Field(default=None, max_length=500)
    financial_llm_model: str | None = Field(default=None, max_length=200)
    rerank_enabled: bool | None = None
    rerank_allow_remote_financial_data: bool | None = None
    rerank_base_url: str | None = Field(default=None, max_length=500)
    rerank_api_key: str | None = Field(default=None, max_length=500)
    rerank_model: str | None = Field(default=None, max_length=200)
    embedding_enabled: bool | None = None
    embedding_allow_remote_financial_data: bool | None = None
    embedding_base_url: str | None = Field(default=None, max_length=500)
    embedding_api_key: str | None = Field(default=None, max_length=500)
    embedding_model: str | None = Field(default=None, max_length=200)
    embedding_dimensions: int | None = Field(default=None, ge=0, le=4096)


class SettingsTest(BaseModel):
    kind: str = Field(default='llm', pattern='^(llm|mask|rerank|embedding)$')
    api_base: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    ollama_base: str | None = Field(default=None, max_length=500)
    dimensions: int | None = Field(default=None, ge=0, le=4096)


_ENV_PATH = Path(__file__).resolve().parents[1] / '.env'
_SECRET_SETTING_KEYS = {'llm_api_key', 'mask_llm_api_key', 'financial_llm_api_key', 'rerank_api_key', 'embedding_api_key'}


def _settings_payload() -> dict:
    values = get_model_runtime_config()
    return {
        **{key: value for key, value in values.items() if key not in _SECRET_SETTING_KEYS},
        **{f'{key}_configured': bool(values.get(key)) for key in _SECRET_SETTING_KEYS},
        'storage': 'plain_config_file',
        'schema_version': MODEL_RUNTIME_CONFIG_SCHEMA_VERSION,
    }


def _openai_endpoint(base: str, path: str) -> str:
    clean = base.rstrip('/')
    if clean.endswith('/v1'):
        return f'{clean}/{path}'
    return f'{clean}/v1/{path}'


def _test_error(response: httpx.Response) -> str:
    try:
        detail = response.json().get('error', {}).get('message')
        if detail: return str(detail)[:240]
    except Exception:
        pass
    return f'服务返回 HTTP {response.status_code}'

@router.post('/auth/login')
def login(body: LoginIn, request: Request):
    user=store.authenticate(body.username,body.password)
    if not user:
        store.audit(None,'auth.login_failed','user',body.username,ip=request.client.host if request.client else '')
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,'用户名或密码错误')
    token=issue_token(user)
    store.audit(user,'auth.login','user',user['id'],ip=request.client.host if request.client else '')
    return {'access_token':token,'token_type':'bearer','user':user,'role_label':ROLE_LABELS[user['role']]}

@router.get('/auth/me')
def me(user=Depends(current_user)):
    return {'user':user,'permissions':['*'] if user['role']=='admin' else sorted(__import__('app.services.security',fromlist=['PERMISSIONS']).PERMISSIONS[user['role']])}

@router.get('/admin/users')
def users(user=Depends(require('admin:users'))):
    return {'items':store.list_users(),'roles':[{'id':x,'label':ROLE_LABELS[x]} for x in ROLES]}

@router.post('/admin/users')
def create_user(body: UserIn, request: Request, user=Depends(require('admin:users'))):
    try: created=store.create_user(body.username,body.display_name,body.role,body.password)
    except ValueError as e: raise HTTPException(400,str(e))
    except Exception as e: raise HTTPException(409,'用户名已存在')
    store.audit(user,'admin.user_create','user',created['id'],{'username':created['username'],'role':created['role']},request.client.host if request.client else '')
    return created

@router.patch('/admin/users/{user_id}')
def patch_user(user_id: str, body: UserPatch, request: Request, user=Depends(require('admin:users'))):
    target = store.get_user(user_id)
    if not target: raise HTTPException(404,'用户不存在')
    if user_id==user['id'] and body.active is False: raise HTTPException(400,'不能停用当前登录管理员')
    if user_id==user['id'] and body.role is not None and body.role != 'admin':
        raise HTTPException(400,'当前登录管理员不能将自己降级；请由另一位管理员操作')
    will_remain_active_admin = (target.get('role') == 'admin' and bool(target.get('active'))
                                and (body.role not in (None, 'admin') or body.active is False))
    if will_remain_active_admin and store.active_admin_count(exclude_user_id=user_id) < 1:
        raise HTTPException(400,'系统至少需要保留一名启用的集团财务总监 / 最终审批人')
    try: updated=store.update_user(user_id,**body.model_dump(exclude_unset=True))
    except ValueError as e: raise HTTPException(400,str(e))
    audit_fields = body.model_dump(exclude_unset=True)
    if 'password' in audit_fields: audit_fields['password_changed'] = bool(audit_fields.pop('password'))
    store.audit(user,'admin.user_update','user',user_id,audit_fields,request.client.host if request.client else '')
    return updated


@router.delete('/admin/users/{user_id}')
def delete_user(user_id: str, request: Request, user=Depends(require('admin:users'))):
    if user_id == user['id']:
        raise HTTPException(400,'不能永久删除当前登录管理员')
    target = store.get_user(user_id)
    if not target:
        raise HTTPException(404,'用户不存在')
    if target.get('role') == 'admin' and target.get('active') and store.active_admin_count(exclude_user_id=user_id) < 1:
        raise HTTPException(400,'系统至少需要保留一名启用的集团财务总监 / 最终审批人')
    deleted = store.delete_user(user_id)
    store.audit(user,'admin.user_delete','user',user_id,{'username':deleted['username'],'role':deleted['role'],'permanent':True},request.client.host if request.client else '')
    return {'deleted':True,'user_id':user_id}

@router.get('/admin/audit')
def audit(limit: int=100, user=Depends(require('admin:audit'))):
    return {'items':store.list_audit(min(max(limit,1),500))}


@router.get('/admin/settings')
def settings(user=Depends(require('admin:users'))):
    """Return editable runtime settings without ever returning secret values."""
    return _settings_payload()


@router.patch('/admin/settings')
def patch_settings(body: SettingsPatch, request: Request, user=Depends(require('admin:users'))):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, '没有可保存的配置')
    for field, value in list(updates.items()):
        # Blank secret inputs mean "keep current" so the UI never needs to hold
        # or echo a real API key in browser state.
        if field in _SECRET_SETTING_KEYS and not str(value or '').strip():
            updates.pop(field)
            continue
        if isinstance(value, str): updates[field] = value.strip()
    if not updates:
        raise HTTPException(400, '没有可保存的配置')
    update_model_runtime_config(updates)
    changed = sorted(updates)
    store.audit(user, 'admin.settings_update', 'model_runtime', '', {'keys': changed, 'storage': 'plain_config_file'}, request.client.host if request.client else '')
    return {**_settings_payload(), 'changed': changed, 'requires_restart': True}


@router.post('/admin/settings/clear-legacy-model-env')
def clear_legacy_model_env(request: Request, user=Depends(require('admin:users'))):
    """Remove obsolete model keys from the local .env after config.json migration."""
    # Verify that the sole runtime config file exists before modifying the
    # legacy bootstrap file.
    if not Path(MODEL_RUNTIME_CONFIG_PATH).exists():
        raise HTTPException(409, 'config.json 尚未初始化，拒绝清理旧模型配置')
    get_model_runtime_config()
    removed = []
    if _ENV_PATH.exists():
        for env_key in LEGACY_MODEL_ENV_KEYS.values():
            if unset_key(str(_ENV_PATH), env_key, quote_mode='auto'):
                removed.append(env_key)
    store.audit(user, 'admin.settings_clear_legacy_env', 'model_runtime', '', {'keys': removed}, request.client.host if request.client else '')
    return {'removed': removed, 'requires_restart': True}


@router.post('/admin/settings/test')
async def test_settings(body: SettingsTest, user=Depends(require('admin:users'))):
    values = get_model_runtime_config()
    prefix = {'llm': 'llm', 'mask': 'mask_llm', 'rerank': 'rerank', 'embedding': 'embedding'}[body.kind]
    base = (body.api_base or values.get(f'{prefix}_api_base') or values.get(f'{prefix}_base_url') or '').strip()
    key = (body.api_key or values.get(f'{prefix}_api_key', '')).strip()
    model = (body.model or values.get(f'{prefix}_model', '')).strip()
    started = time.perf_counter()
    try:
        if not (base and key and model):
            return {'ok': False, 'kind': body.kind, 'message': '请填写 API 地址、API Key 和模型'}
        async with httpx.AsyncClient(timeout=12) as client:
            if body.kind in {'llm', 'mask'}:
                response = await client.post(_openai_endpoint(base, 'chat/completions'), headers={'Authorization': f'Bearer {key}'}, json={'model': model, 'messages': [{'role': 'user', 'content': 'Reply with OK only.'}], 'max_tokens': 2})
            elif body.kind == 'rerank':
                response = await client.post(base.rstrip('/') + '/reranks', headers={'Authorization': f'Bearer {key}'}, json={'model': model, 'query': '信用风险', 'documents': ['企业财务报表证据'], 'top_n': 1})
            else:
                payload = {'model': model, 'input': ['信用风险']}
                if body.dimensions:
                    payload['dimensions'] = body.dimensions
                response = await client.post(_openai_endpoint(base, 'embeddings'), headers={'Authorization': f'Bearer {key}'}, json=payload)
            ok = response.status_code < 400
        return {'ok': ok, 'kind': body.kind, 'model': model, 'latency_ms': round((time.perf_counter() - started) * 1000), 'message': '连接成功' if ok else _test_error(response)}
    except Exception as exc:
        return {'ok': False, 'kind': body.kind, 'latency_ms': round((time.perf_counter() - started) * 1000), 'message': f'连接失败：{str(exc)[:180]}'}
