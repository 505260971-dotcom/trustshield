"""DashScope/OpenAI-compatible embedding recall for credit evidence.

Vectors are request-scoped and kept only in process memory.  Source documents
and their text assets stay in TrustShield's encrypted store; the remote
embedding provider receives passages only when the administrator explicitly
enables financial-data transfer for this stage.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import (
    EMBEDDING_ALLOW_REMOTE_FINANCIAL_DATA, EMBEDDING_API_KEY, EMBEDDING_BASE_URL,
    EMBEDDING_CANDIDATE_LIMIT, EMBEDDING_DIMENSIONS, EMBEDDING_DOCUMENT_TOKEN_BUDGET,
    EMBEDDING_ENABLED, EMBEDDING_MODEL, EMBEDDING_TIMEOUT_SECONDS, configured_embedding,
)
from .llm import clip_text_to_tokens


class EmbeddingUnavailable(RuntimeError):
    """Semantic recall was explicitly requested but cannot safely run."""


_cache: dict[str, list[float]] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 512


def _endpoint(base: str) -> str:
    clean = base.rstrip('/')
    return f'{clean}/embeddings' if clean.endswith('/v1') else f'{clean}/v1/embeddings'


def _key(text: str) -> str:
    return f'{EMBEDDING_MODEL}:{EMBEDDING_DIMENSIONS}:{hashlib.sha256(text.encode("utf-8")).hexdigest()}'


def _as_vector(value: Any) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ValueError('embedding 响应缺少向量')
    try:
        vector = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ValueError('embedding 响应包含非数值向量') from exc
    if not all(math.isfinite(item) for item in vector):
        raise ValueError('embedding 响应包含非有限数值')
    return vector


def _remote_embeddings(inputs: list[str]) -> list[list[float]]:
    payload: dict[str, Any] = {'model': EMBEDDING_MODEL, 'input': inputs}
    if EMBEDDING_DIMENSIONS:
        payload['dimensions'] = EMBEDDING_DIMENSIONS
    request = Request(
        _endpoint(EMBEDDING_BASE_URL), data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Authorization': f'Bearer {EMBEDDING_API_KEY}', 'Content-Type': 'application/json'}, method='POST',
    )
    try:
        with urlopen(request, timeout=EMBEDDING_TIMEOUT_SECONDS) as response:  # nosec B310: admin-configured provider
            body = json.loads(response.read().decode('utf-8'))
        rows = body.get('data') if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise ValueError('embedding 响应缺少 data')
        indexed: dict[int, list[float]] = {}
        for position, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            index = row.get('index', position)
            if isinstance(index, int) and 0 <= index < len(inputs):
                indexed[index] = _as_vector(row.get('embedding'))
        if len(indexed) != len(inputs):
            raise ValueError('embedding 响应数量与请求不一致')
        vectors = [indexed[index] for index in range(len(inputs))]
        size = len(vectors[0])
        if size < 8 or any(len(vector) != size for vector in vectors):
            raise ValueError('embedding 向量维度不一致或过短')
        return vectors
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise EmbeddingUnavailable(f'embedding 调用失败: {type(exc).__name__}: {str(exc)[:180]}') from exc


def embed_texts(inputs: list[str]) -> list[list[float]]:
    if not configured_embedding():
        reason = '未获财务数据传输授权' if not EMBEDDING_ALLOW_REMOTE_FINANCIAL_DATA else '未配置'
        raise EmbeddingUnavailable(f'embedding {reason}')
    clipped = [clip_text_to_tokens(str(item or ''), EMBEDDING_DOCUMENT_TOKEN_BUDGET) for item in inputs]
    keys = [_key(item) for item in clipped]
    with _cache_lock:
        cached = {index: _cache.get(key) for index, key in enumerate(keys)}
    missing_indexes = [index for index, value in cached.items() if value is None]
    if missing_indexes:
        fresh = _remote_embeddings([clipped[index] for index in missing_indexes])
        with _cache_lock:
            if len(_cache) + len(fresh) > _CACHE_MAX:
                _cache.clear()
            for index, vector in zip(missing_indexes, fresh):
                _cache[keys[index]] = vector
                cached[index] = vector
    return [cached[index] or [] for index in range(len(clipped))]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError('查询与证据向量维度不一致')
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else -1.0


def semantic_recall(query: str, candidates: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    """Rank a bounded source-addressable candidate set by cosine similarity."""
    if EMBEDDING_ENABLED and not configured_embedding():
        raise EmbeddingUnavailable('embedding 已启用但缺少模型、地址、密钥或财务数据传输授权')
    if not configured_embedding():
        return []
    size = min(len(candidates), limit or EMBEDDING_CANDIDATE_LIMIT)
    selected = candidates[:size]
    if not selected:
        return []
    vectors = embed_texts([query, *[str(item.get('text') or '') for item in selected]])
    query_vector = vectors[0]
    scored = []
    for index, (candidate, vector) in enumerate(zip(selected, vectors[1:])):
        scored.append((_cosine(query_vector, vector), index, candidate))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [dict(item) | {'embedding_score': round(score, 7), 'embedding_rank': rank + 1}
            for rank, (score, _, item) in enumerate(scored)]
