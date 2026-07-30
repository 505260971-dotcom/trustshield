"""Bootstrap and config.json-backed runtime configuration.

Only bootstrap secrets (token signing, database encryption and the initial
administrator) come from the deployment environment. Model endpoints, model
names and provider keys are maintained in the local config.json file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


# A local .env remains useful for the bootstrap secrets in a developer
# workspace. Runtime model settings are deliberately never read from it:
# config.json is their sole runtime source.
load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv('CONTRACTGUARD_DATA_DIR', os.path.join(BASE_DIR, 'data'))
UPLOAD_DIR = os.path.join(DATA_DIR, 'uploads')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'contractguard.db')
# Keep the runtime file inside the configured data root so isolated test or
# deployment data directories never overwrite another instance's credentials.
MODEL_RUNTIME_CONFIG_PATH = os.getenv('CONTRACTGUARD_CONFIG_PATH', os.path.join(DATA_DIR, 'config.json'))
MODEL_RUNTIME_CONFIG_SCHEMA_VERSION = 2

AUTH_SECRET = os.getenv('AUTH_SECRET', '')
DATA_ENCRYPTION_KEY = os.getenv('DATA_ENCRYPTION_KEY', '')
INITIAL_ADMIN_USERNAME = os.getenv('INITIAL_ADMIN_USERNAME', '')
INITIAL_ADMIN_PASSWORD = os.getenv('INITIAL_ADMIN_PASSWORD', '')
INITIAL_ADMIN_NAME = os.getenv('INITIAL_ADMIN_NAME', '系统管理员')
ACCESS_TOKEN_MINUTES = max(5, int(os.getenv('ACCESS_TOKEN_MINUTES', '480')))
CORS_ORIGINS = [x.strip() for x in os.getenv('CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(',') if x.strip()]

# These are deployment and policy boundaries rather than a model-provider
# credential.  They remain immutable environment-level controls.
CREDIT_AUDIT_AGENT_ENABLED = os.getenv('CREDIT_AUDIT_AGENT_ENABLED', 'true').lower() == 'true'
CREDIT_AUDIT_AGENT_MAX_TASKS = min(12, max(3, int(os.getenv('CREDIT_AUDIT_AGENT_MAX_TASKS', '8'))))
# The production ReAct executor has a separate bounded tool budget.  Keep it
# above the minimum needed to inspect a document, validate context and submit
# claims, while retaining an upper bound against runaway remote calls.
CREDIT_REACT_AGENT_MAX_STEPS = min(24, max(8, int(os.getenv('CREDIT_REACT_AGENT_MAX_STEPS', '16'))))
CREDIT_AUDIT_MAX_FINANCIAL_AGE_YEARS = min(5, max(0, int(os.getenv('CREDIT_AUDIT_MAX_FINANCIAL_AGE_YEARS', '2'))))
CREDIT_AUDIT_MAX_EXPOSURE_AGE_DAYS = min(90, max(1, int(os.getenv('CREDIT_AUDIT_MAX_EXPOSURE_AGE_DAYS', '7'))))
REMOTE_CONTEXT_TOKENS = 128000
LOCAL_CONTEXT_TOKENS = 2048


DEFAULT_MODEL_RUNTIME_CONFIG: dict[str, Any] = {
    'llm_api_base': '', 'llm_api_key': '', 'llm_model': '', 'llm_timeout_seconds': 60,
    'ollama_base': 'http://localhost:11434',
    'enable_masking': True, 'smart_mask': False,
    'mask_llm_api_base': 'http://localhost:11434/v1', 'mask_llm_api_key': 'ollama',
    'mask_llm_model': '', 'mask_llm_native_ollama': True, 'mask_llm_think': False,
    'mask_llm_max_output': 160, 'mask_llm_deep_scan': False,
    'financial_llm_extraction': True, 'financial_llm_mode': 'remote_substitute',
    'financial_llm_api_base': '', 'financial_llm_api_key': '', 'financial_llm_model': '',
    'rerank_enabled': False, 'rerank_allow_remote_financial_data': False,
    'rerank_base_url': '', 'rerank_api_key': '', 'rerank_model': 'qwen3-rerank',
    'rerank_timeout_seconds': 20, 'rerank_candidate_limit': 36, 'rerank_top_n': 6,
    'rerank_document_token_budget': 3000,
    'embedding_enabled': False, 'embedding_allow_remote_financial_data': False,
    'embedding_base_url': '', 'embedding_api_key': '', 'embedding_model': '',
    'embedding_dimensions': 0, 'embedding_timeout_seconds': 20,
    'embedding_candidate_limit': 36, 'embedding_document_token_budget': 1200,
}

# Existing local installations may still have these values in .env. They are
# listed only so the administrator can remove obsolete keys; they are never
# read as runtime model configuration.
LEGACY_MODEL_ENV_KEYS = {
    'llm_api_base': 'LLM_API_BASE', 'llm_api_key': 'LLM_API_KEY', 'llm_model': 'LLM_MODEL', 'llm_timeout_seconds': 'LLM_TIMEOUT_SECONDS',
    'ollama_base': 'OLLAMA_BASE', 'enable_masking': 'ENABLE_MASKING', 'smart_mask': 'SMART_MASK',
    'mask_llm_api_base': 'MASK_LLM_API_BASE', 'mask_llm_api_key': 'MASK_LLM_API_KEY', 'mask_llm_model': 'MASK_LLM_MODEL',
    'mask_llm_native_ollama': 'MASK_LLM_NATIVE_OLLAMA', 'mask_llm_think': 'MASK_LLM_THINK',
    'mask_llm_max_output': 'MASK_LLM_MAX_OUTPUT', 'mask_llm_deep_scan': 'MASK_LLM_DEEP_SCAN',
    'financial_llm_extraction': 'FINANCIAL_LLM_EXTRACTION', 'financial_llm_mode': 'FINANCIAL_LLM_MODE',
    'financial_llm_api_base': 'FINANCIAL_LLM_API_BASE', 'financial_llm_api_key': 'FINANCIAL_LLM_API_KEY', 'financial_llm_model': 'FINANCIAL_LLM_MODEL',
    'rerank_enabled': 'RERANK_ENABLED', 'rerank_allow_remote_financial_data': 'RERANK_ALLOW_REMOTE_FINANCIAL_DATA',
    'rerank_base_url': 'RERANK_BASE_URL', 'rerank_api_key': 'RERANK_API_KEY', 'rerank_model': 'RERANK_MODEL',
    'rerank_timeout_seconds': 'RERANK_TIMEOUT_SECONDS', 'rerank_candidate_limit': 'RERANK_CANDIDATE_LIMIT',
    'rerank_top_n': 'RERANK_TOP_N', 'rerank_document_token_budget': 'RERANK_DOCUMENT_TOKEN_BUDGET',
    'embedding_enabled': 'EMBEDDING_ENABLED', 'embedding_allow_remote_financial_data': 'EMBEDDING_ALLOW_REMOTE_FINANCIAL_DATA',
    'embedding_base_url': 'EMBEDDING_BASE_URL', 'embedding_api_key': 'EMBEDDING_API_KEY', 'embedding_model': 'EMBEDDING_MODEL',
    'embedding_dimensions': 'EMBEDDING_DIMENSIONS', 'embedding_timeout_seconds': 'EMBEDDING_TIMEOUT_SECONDS',
    'embedding_candidate_limit': 'EMBEDDING_CANDIDATE_LIMIT', 'embedding_document_token_budget': 'EMBEDDING_DOCUMENT_TOKEN_BUDGET',
}

_BOOL_FIELDS = {key for key, value in DEFAULT_MODEL_RUNTIME_CONFIG.items() if isinstance(value, bool)}
_INT_FIELDS = {key for key, value in DEFAULT_MODEL_RUNTIME_CONFIG.items() if isinstance(value, int) and not isinstance(value, bool)}


def _normalise_model_runtime(raw: dict[str, Any] | None) -> dict[str, Any]:
    value = {**DEFAULT_MODEL_RUNTIME_CONFIG, **(raw or {})}
    for key in _BOOL_FIELDS:
        item = value.get(key)
        value[key] = item if isinstance(item, bool) else str(item or '').strip().lower() == 'true'
    for key in _INT_FIELDS:
        try:
            value[key] = int(value.get(key) or 0)
        except (TypeError, ValueError):
            value[key] = int(DEFAULT_MODEL_RUNTIME_CONFIG[key])
    value['llm_timeout_seconds'] = min(180, max(10, value['llm_timeout_seconds']))
    value['mask_llm_max_output'] = min(384, max(64, value['mask_llm_max_output']))
    value['rerank_timeout_seconds'] = min(60, max(3, value['rerank_timeout_seconds']))
    value['rerank_candidate_limit'] = min(100, max(8, value['rerank_candidate_limit']))
    value['rerank_top_n'] = min(16, max(1, value['rerank_top_n']))
    value['rerank_document_token_budget'] = min(3400, max(600, value['rerank_document_token_budget']))
    value['embedding_timeout_seconds'] = min(60, max(3, value['embedding_timeout_seconds']))
    value['embedding_candidate_limit'] = min(100, max(8, value['embedding_candidate_limit']))
    value['embedding_document_token_budget'] = min(3000, max(300, value['embedding_document_token_budget']))
    value['embedding_dimensions'] = min(4096, max(0, value['embedding_dimensions']))
    for key, default in DEFAULT_MODEL_RUNTIME_CONFIG.items():
        if key not in _BOOL_FIELDS and key not in _INT_FIELDS:
            value[key] = str(value.get(key) or default).strip()
    return value


def _load_file_model_runtime() -> dict[str, Any] | None:
    """Read all provider settings directly from config.json."""
    if not os.path.exists(MODEL_RUNTIME_CONFIG_PATH):
        return None
    try:
        with open(MODEL_RUNTIME_CONFIG_PATH, 'r', encoding='utf-8') as stream:
            payload = json.load(stream)
        settings = payload.get('model_runtime') if isinstance(payload, dict) else None
        if not isinstance(settings, dict):
            return None
        return _normalise_model_runtime(settings)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _write_file_model_runtime(value: dict[str, Any]) -> dict[str, Any]:
    """Persist all provider runtime settings directly in config.json."""
    normal = _normalise_model_runtime(value)
    payload = {'schema_version': MODEL_RUNTIME_CONFIG_SCHEMA_VERSION, 'model_runtime': normal}
    temporary = MODEL_RUNTIME_CONFIG_PATH + '.tmp'
    with open(temporary, 'w', encoding='utf-8', newline='\n') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n')
    os.replace(temporary, MODEL_RUNTIME_CONFIG_PATH)
    return normal


_FILE_MODEL_RUNTIME = _load_file_model_runtime()
MODEL_RUNTIME_CONFIG = _FILE_MODEL_RUNTIME or dict(DEFAULT_MODEL_RUNTIME_CONFIG)
MODEL_RUNTIME_SOURCE = 'config_file' if _FILE_MODEL_RUNTIME is not None else 'defaults_pending_file'


def get_model_runtime_config() -> dict[str, Any]:
    """Read the current config.json value, or defaults before first startup."""
    return _load_file_model_runtime() or dict(DEFAULT_MODEL_RUNTIME_CONFIG)


def update_model_runtime_config(updates: dict[str, Any]) -> dict[str, Any]:
    allowed = set(DEFAULT_MODEL_RUNTIME_CONFIG)
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError('包含不支持的模型配置字段：' + '、'.join(sorted(unknown)))
    return _write_file_model_runtime({**get_model_runtime_config(), **updates})


def ensure_model_runtime_config_file() -> bool:
    """Create or upgrade config.json to the plaintext schema requested by user."""
    current = _load_file_model_runtime()
    if current is None:
        _write_file_model_runtime(MODEL_RUNTIME_CONFIG)
        return True
    try:
        with open(MODEL_RUNTIME_CONFIG_PATH, 'r', encoding='utf-8') as stream:
            raw = json.load(stream)
        if raw.get('schema_version') != MODEL_RUNTIME_CONFIG_SCHEMA_VERSION:
            _write_file_model_runtime(current)
            return True
    except (OSError, json.JSONDecodeError):
        _write_file_model_runtime(current)
        return True
    return False

LLM_API_BASE = MODEL_RUNTIME_CONFIG['llm_api_base'].rstrip('/')
LLM_API_KEY = MODEL_RUNTIME_CONFIG['llm_api_key']
LLM_MODEL = MODEL_RUNTIME_CONFIG['llm_model']
LLM_TIMEOUT_SECONDS = MODEL_RUNTIME_CONFIG['llm_timeout_seconds']
OLLAMA_BASE = MODEL_RUNTIME_CONFIG['ollama_base']
ENABLE_MASKING = MODEL_RUNTIME_CONFIG['enable_masking']
SMART_MASK = MODEL_RUNTIME_CONFIG['smart_mask']
MASK_LLM_API_BASE = MODEL_RUNTIME_CONFIG['mask_llm_api_base'].rstrip('/')
MASK_LLM_API_KEY = MODEL_RUNTIME_CONFIG['mask_llm_api_key']
MASK_LLM_MODEL = MODEL_RUNTIME_CONFIG['mask_llm_model']
MASK_LLM_NATIVE_OLLAMA = MODEL_RUNTIME_CONFIG['mask_llm_native_ollama']
MASK_LLM_THINK = MODEL_RUNTIME_CONFIG['mask_llm_think']
MASK_LLM_MAX_OUTPUT = MODEL_RUNTIME_CONFIG['mask_llm_max_output']
MASK_LLM_DEEP_SCAN = MODEL_RUNTIME_CONFIG['mask_llm_deep_scan']
FINANCIAL_LLM_EXTRACTION = MODEL_RUNTIME_CONFIG['financial_llm_extraction']
FINANCIAL_LLM_MODE = MODEL_RUNTIME_CONFIG['financial_llm_mode']
FINANCIAL_LLM_API_BASE = MODEL_RUNTIME_CONFIG['financial_llm_api_base'].rstrip('/') or LLM_API_BASE
FINANCIAL_LLM_API_KEY = MODEL_RUNTIME_CONFIG['financial_llm_api_key'] or LLM_API_KEY
FINANCIAL_LLM_MODEL = MODEL_RUNTIME_CONFIG['financial_llm_model'] or LLM_MODEL
RERANK_ENABLED = MODEL_RUNTIME_CONFIG['rerank_enabled']
RERANK_ALLOW_REMOTE_FINANCIAL_DATA = MODEL_RUNTIME_CONFIG['rerank_allow_remote_financial_data']
RERANK_BASE_URL = MODEL_RUNTIME_CONFIG['rerank_base_url'].rstrip('/')
RERANK_API_KEY = MODEL_RUNTIME_CONFIG['rerank_api_key']
RERANK_MODEL = MODEL_RUNTIME_CONFIG['rerank_model'] or 'qwen3-rerank'
RERANK_TIMEOUT_SECONDS = MODEL_RUNTIME_CONFIG['rerank_timeout_seconds']
RERANK_CANDIDATE_LIMIT = MODEL_RUNTIME_CONFIG['rerank_candidate_limit']
RERANK_TOP_N = MODEL_RUNTIME_CONFIG['rerank_top_n']
RERANK_DOCUMENT_TOKEN_BUDGET = MODEL_RUNTIME_CONFIG['rerank_document_token_budget']
EMBEDDING_ENABLED = MODEL_RUNTIME_CONFIG['embedding_enabled']
EMBEDDING_ALLOW_REMOTE_FINANCIAL_DATA = MODEL_RUNTIME_CONFIG['embedding_allow_remote_financial_data']
EMBEDDING_BASE_URL = MODEL_RUNTIME_CONFIG['embedding_base_url'].rstrip('/')
EMBEDDING_API_KEY = MODEL_RUNTIME_CONFIG['embedding_api_key']
EMBEDDING_MODEL = MODEL_RUNTIME_CONFIG['embedding_model']
EMBEDDING_DIMENSIONS = MODEL_RUNTIME_CONFIG['embedding_dimensions']
EMBEDDING_TIMEOUT_SECONDS = MODEL_RUNTIME_CONFIG['embedding_timeout_seconds']
EMBEDDING_CANDIDATE_LIMIT = MODEL_RUNTIME_CONFIG['embedding_candidate_limit']
EMBEDDING_DOCUMENT_TOKEN_BUDGET = MODEL_RUNTIME_CONFIG['embedding_document_token_budget']


def configured_llm() -> bool:
    return bool(LLM_API_BASE and LLM_API_KEY and LLM_MODEL)


def configured_financial_llm() -> bool:
    return bool(FINANCIAL_LLM_API_BASE and FINANCIAL_LLM_API_KEY and FINANCIAL_LLM_MODEL)


def configured_rerank() -> bool:
    return bool(RERANK_ENABLED and RERANK_ALLOW_REMOTE_FINANCIAL_DATA and RERANK_BASE_URL and RERANK_API_KEY and RERANK_MODEL)


def configured_embedding() -> bool:
    return bool(EMBEDDING_ENABLED and EMBEDDING_ALLOW_REMOTE_FINANCIAL_DATA and EMBEDDING_BASE_URL and EMBEDDING_API_KEY and EMBEDDING_MODEL)


def secure_runtime_ready() -> bool:
    return bool(AUTH_SECRET and DATA_ENCRYPTION_KEY)


def masking_model_mode() -> str:
    if not (SMART_MASK and MASK_LLM_MODEL):
        return 'regex_only'
    return 'local_ollama' if MASK_LLM_NATIVE_OLLAMA else 'remote_proxy'


def financial_llm_mode() -> str:
    return 'local_or_intranet' if FINANCIAL_LLM_MODE == 'local_or_intranet' else 'remote_substitute'
