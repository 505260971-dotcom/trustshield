"""FastAPI auth dependencies and administrative routes."""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values, set_key
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import store
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


class SettingsTest(BaseModel):
    kind: str = Field(default='llm', pattern='^(llm)$')
    api_base: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    ollama_base: str | None = Field(default=None, max_length=500)


_ENV_PATH = Path(__file__).resolve().parents[1] / '.env'
_SETTING_ENV_KEYS = {
    'llm_api_base': 'LLM_API_BASE', 'llm_api_key': 'LLM_API_KEY', 'llm_model': 'LLM_MODEL',
    'ollama_base': 'OLLAMA_BASE',
    'enable_masking': 'ENABLE_MASKING', 'smart_mask': 'SMART_MASK',
    'mask_llm_api_base': 'MASK_LLM_API_BASE', 'mask_llm_api_key': 'MASK_LLM_API_KEY',
    'mask_llm_model': 'MASK_LLM_MODEL',
}
_SECRET_SETTING_KEYS = {'llm_api_key', 'mask_llm_api_key'}


def _env_values() -> dict[str, str]:
    saved = dotenv_values(str(_ENV_PATH)) if _ENV_PATH.exists() else {}
    return {env_key: str(saved.get(env_key) or os.getenv(env_key, '') or '') for env_key in _SETTING_ENV_KEYS.values()}


def _configured(values: dict[str, str], key: str) -> bool:
    return bool(values.get(_SETTING_ENV_KEYS[key], '').strip())


def _settings_payload() -> dict:
    values = _env_values()
    return {
        'llm_api_base': values['LLM_API_BASE'],
        'llm_model': values['LLM_MODEL'],
        'llm_api_key_configured': _configured(values, 'llm_api_key'),
        'ollama_base': values['OLLAMA_BASE'],
        'enable_masking': values['ENABLE_MASKING'].lower() != 'false',
        'smart_mask': values['SMART_MASK'].lower() == 'true',
        'mask_llm_api_base': values['MASK_LLM_API_BASE'],
        'mask_llm_model': values['MASK_LLM_MODEL'],
        'mask_llm_api_key_configured': _configured(values, 'mask_llm_api_key'),
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
    if user_id==user['id'] and body.active is False: raise HTTPException(400,'不能停用当前登录管理员')
    try: updated=store.update_user(user_id,**body.model_dump(exclude_unset=True))
    except ValueError as e: raise HTTPException(400,str(e))
    if not updated: raise HTTPException(404,'用户不存在')
    store.audit(user,'admin.user_update','user',user_id,body.model_dump(exclude_unset=True),request.client.host if request.client else '')
    return updated

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
    changed=[]
    for field, value in updates.items():
        # Blank secret inputs mean "keep current" so the UI never needs to hold
        # or echo a real API key in browser state.
        if field in _SECRET_SETTING_KEYS and not str(value or '').strip():
            continue
        env_key = _SETTING_ENV_KEYS[field]
        if isinstance(value, bool): value = 'true' if value else 'false'
        elif isinstance(value, int): value = str(value)
        else: value = str(value or '').strip()
        set_key(str(_ENV_PATH), env_key, value, quote_mode='auto')
        changed.append(env_key)
    store.audit(user, 'admin.settings_update', 'settings', '', {'keys': changed}, request.client.host if request.client else '')
    return {**_settings_payload(), 'changed': changed, 'requires_restart': True}


@router.post('/admin/settings/test')
async def test_settings(body: SettingsTest, user=Depends(require('admin:users'))):
    values = _env_values()
    base = (body.api_base or values.get('LLM_API_BASE', '')).strip()
    key = (body.api_key or values.get('LLM_API_KEY', '')).strip()
    model = (body.model or values.get('LLM_MODEL', '')).strip()
    started = time.perf_counter()
    try:
        if not (base and key and model):
            return {'ok': False, 'kind': 'llm', 'message': '请填写主模型地址、API Key 和模型'}
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                _openai_endpoint(base, 'chat/completions'),
                headers={'Authorization': f'Bearer {key}'},
                json={'model': model, 'messages': [{'role': 'user', 'content': 'Reply with OK only.'}], 'max_tokens': 2},
            )
            ok = response.status_code < 400
        return {'ok': ok, 'kind': 'llm', 'model': model, 'latency_ms': round((time.perf_counter() - started) * 1000), 'message': '连接成功' if ok else _test_error(response)}
    except Exception as exc:
        return {'ok': False, 'kind': 'llm', 'latency_ms': round((time.perf_counter() - started) * 1000), 'message': f'连接失败：{str(exc)[:180]}'}
