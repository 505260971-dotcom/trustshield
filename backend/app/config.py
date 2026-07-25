"""Runtime configuration.

All credentials are intentionally supplied through environment variables.  Do
not add a fallback secret here: the application must fail closed when a model,
token-signing key, or data-encryption key is not configured.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Local development convenience only.  Production should inject the same keys
# through the deployment platform's secret store/environment.
load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)

LLM_API_BASE = os.getenv('LLM_API_BASE', '').rstrip('/')
LLM_API_KEY = os.getenv('LLM_API_KEY', '')
LLM_MODEL = os.getenv('LLM_MODEL', '')
# A review must fail visibly rather than leave its worker thread waiting on an
# unavailable provider forever. The value remains configurable for slow models.
LLM_TIMEOUT_SECONDS = min(180, max(10, int(os.getenv('LLM_TIMEOUT_SECONDS', '60'))))
OLLAMA_BASE = os.getenv('OLLAMA_BASE', 'http://localhost:11434')
ENABLE_MASKING = os.getenv('ENABLE_MASKING', 'true').lower() == 'true'
# 本地隐私模型。它只负责敏感实体识别，绝不参与合同风险判断。
# 通过 Ollama/OpenAI 兼容接口接入本地 8B；未配置模型时自动回退到正则脱敏。
SMART_MASK = os.getenv('SMART_MASK', 'false').lower() == 'true'
MASK_LLM_API_BASE = os.getenv('MASK_LLM_API_BASE', 'http://localhost:11434/v1')
MASK_LLM_API_KEY = os.getenv('MASK_LLM_API_KEY', 'ollama')
MASK_LLM_MODEL = os.getenv('MASK_LLM_MODEL', '')
MASK_LLM_NATIVE_OLLAMA = os.getenv('MASK_LLM_NATIVE_OLLAMA', 'true').lower() == 'true'
MASK_LLM_THINK = os.getenv('MASK_LLM_THINK', 'false').lower() == 'true'
MASK_LLM_MAX_OUTPUT = min(384, max(64, int(os.getenv('MASK_LLM_MAX_OUTPUT', '160'))))
MASK_LLM_DEEP_SCAN = os.getenv('MASK_LLM_DEEP_SCAN', 'false').lower() == 'true'
# 上下文总预算（输入 + 输出）。即使环境变量设置得更大，也不允许突破业务安全上限。
REMOTE_CONTEXT_TOKENS = min(int(os.getenv('REMOTE_CONTEXT_TOKENS', '128000')), 128000)
LOCAL_CONTEXT_TOKENS = min(int(os.getenv('LOCAL_CONTEXT_TOKENS', '2048')), 2048)
AUTH_SECRET = os.getenv('AUTH_SECRET', '')
DATA_ENCRYPTION_KEY = os.getenv('DATA_ENCRYPTION_KEY', '')
INITIAL_ADMIN_USERNAME = os.getenv('INITIAL_ADMIN_USERNAME', '')
INITIAL_ADMIN_PASSWORD = os.getenv('INITIAL_ADMIN_PASSWORD', '')
INITIAL_ADMIN_NAME = os.getenv('INITIAL_ADMIN_NAME', '系统管理员')
ACCESS_TOKEN_MINUTES = max(5, int(os.getenv('ACCESS_TOKEN_MINUTES', '480')))
CORS_ORIGINS = [x.strip() for x in os.getenv('CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(',') if x.strip()]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv('CONTRACTGUARD_DATA_DIR', os.path.join(BASE_DIR, 'data'))
UPLOAD_DIR = os.path.join(DATA_DIR, 'uploads')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

def configured_llm() -> bool:
    return bool(LLM_API_BASE and LLM_API_KEY and LLM_MODEL)

def secure_runtime_ready() -> bool:
    return bool(AUTH_SECRET and DATA_ENCRYPTION_KEY)
