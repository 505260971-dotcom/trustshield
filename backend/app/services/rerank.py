"""Bounded qwen3-rerank adapter for credit-review evidence.

The service intentionally accepts already-recalled, source-addressable chunks.
Reranking is a precision stage, not a substitute for recall or fact validation.
When the remote service is not explicitly enabled or fails, the caller receives
the same deterministic lexical ranking plus an auditable fallback reason.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import (
    EMBEDDING_ENABLED,
    RERANK_API_KEY, RERANK_BASE_URL, RERANK_CANDIDATE_LIMIT,
    RERANK_DOCUMENT_TOKEN_BUDGET, RERANK_MODEL, RERANK_TIMEOUT_SECONDS,
    RERANK_TOP_N, configured_rerank,
)
from .embedding import EmbeddingUnavailable, semantic_recall
from .llm import clip_text_to_tokens


_WORD = re.compile(r"[A-Za-z0-9_]{2,}|[\u3400-\u9fff]{1,}")


class RerankUnavailable(RuntimeError):
    """Production audit cannot continue when mandatory reranking is unavailable."""


def _terms(text: str) -> set[str]:
    """Generate language-neutral words plus short CJK n-grams for fallback recall."""
    result: set[str] = set()
    for value in _WORD.findall(str(text or '').lower()):
        if re.fullmatch(r"[\u3400-\u9fff]+", value):
            result.update(value[index:index + 2] for index in range(max(0, len(value) - 1)))
            if len(value) <= 2:
                result.add(value)
        else:
            result.add(value)
    return result


def lexical_recall(query: str, candidates: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    """High-recall local ranking; it never discards source metadata."""
    limit = limit or RERANK_CANDIDATE_LIMIT
    query_terms = _terms(query)
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for index, candidate in enumerate(candidates):
        text = str(candidate.get('text') or '')
        terms = _terms(text)
        overlap = len(query_terms & terms)
        # Preserve a small preference for source tables without assuming a
        # financial-report vocabulary or document template.
        table_bonus = .25 if candidate.get('source_kind') in {'table', 'sheet'} else 0.0
        score = overlap + table_bonus
        ranked.append((score, index, candidate))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    # Zero-overlap chunks remain candidates: an LLM-generated query can use
    # synonyms not present in OCR text, and qwen rerank is allowed to recover
    # them from the bounded tail.
    return [dict(item[2]) | {'lexical_score': round(item[0], 4)} for item in ranked[:limit]]


def _rerank_document(candidate: dict[str, Any]) -> str:
    anchor = str(candidate.get('source_ref') or '')
    document = f"【来源：{anchor}】\n{candidate.get('text') or ''}" if anchor else str(candidate.get('text') or '')
    return clip_text_to_tokens(document, RERANK_DOCUMENT_TOKEN_BUDGET)


def hybrid_recall(query: str, candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Fuse local lexical recall with optional DashScope semantic recall.

    Rerank still receives a bounded list and remains the only precision gate.
    Reciprocal-rank fusion keeps both paths auditable and does not compare raw
    provider scores with local token-overlap scores.
    """
    lexical = lexical_recall(query, candidates)
    if not EMBEDDING_ENABLED:
        return lexical, 'lexical'
    semantic = semantic_recall(query, candidates)
    merged: dict[str, tuple[float, int, dict[str, Any]]] = {}
    for source, rows in (('lexical', lexical), ('embedding', semantic)):
        for rank, item in enumerate(rows, 1):
            identity = str(item.get('chunk_id') or item.get('source_ref') or rank)
            score, first_rank, prior = merged.get(identity, (0.0, rank, {}))
            merged[identity] = (score + 1 / (60 + rank), min(first_rank, rank), dict(prior) | dict(item))
    ranked = sorted(merged.values(), key=lambda row: (-row[0], row[1]))[:RERANK_CANDIDATE_LIMIT]
    return [dict(item) | {'hybrid_score': round(score, 7)} for score, _, item in ranked], 'hybrid_lexical_embedding'


def rerank(query: str, candidates: list[dict[str, Any]], top_n: int | None = None, instruct: str = '') -> dict[str, Any]:
    """Return one request-local ordering and its audit metadata.

    qwen relevance scores are not comparable across requests.  The caller must
    therefore treat them solely as ordering metadata for this invocation.
    """
    try:
        shortlisted, recall_mode = hybrid_recall(query, candidates)
    except EmbeddingUnavailable as exc:
        shortlisted, recall_mode = lexical_recall(query, candidates), 'lexical_embedding_failed'
    wanted = min(len(shortlisted), top_n or RERANK_TOP_N)
    base = {
        'query': query,
        'candidate_count': len(shortlisted),
        'top_n': wanted,
        'model': RERANK_MODEL,
        'recall_mode': recall_mode,
    }
    if not shortlisted:
        return base | {'mode': 'empty', 'results': [], 'fallback_reason': 'no_candidates'}
    if not configured_rerank():
        return base | {
            'mode': 'lexical_fallback', 'results': [dict(item) | {'rank': rank + 1} for rank, item in enumerate(shortlisted[:wanted])],
            'fallback_reason': 'rerank_not_explicitly_configured',
        }

    payload = {
        'model': RERANK_MODEL,
        'query': clip_text_to_tokens(query, RERANK_DOCUMENT_TOKEN_BUDGET),
        'documents': [_rerank_document(item) for item in shortlisted],
        'top_n': wanted,
        'instruct': instruct or 'Given a credit-review evidence request, retrieve passages that directly prove the requested fact. Prefer primary source evidence over commentary.',
    }
    request = Request(
        RERANK_BASE_URL.rstrip('/') + '/reranks',
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Authorization': f'Bearer {RERANK_API_KEY}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urlopen(request, timeout=RERANK_TIMEOUT_SECONDS) as response:  # nosec B310: URL is deployment configuration
            data = json.loads(response.read().decode('utf-8'))
        rows = data.get('results') if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ValueError('rerank 响应缺少 results')
        results: list[dict[str, Any]] = []
        used: set[int] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            index = row.get('index')
            if not isinstance(index, int) or index < 0 or index >= len(shortlisted) or index in used:
                continue
            used.add(index)
            try:
                score = float(row.get('relevance_score'))
            except (TypeError, ValueError):
                score = None
            results.append(dict(shortlisted[index]) | {'rank': len(results) + 1, 'rerank_index': index, 'relevance_score': score})
        if not results:
            raise ValueError('rerank 响应未返回有效索引')
        return base | {
            'mode': 'qwen3-rerank', 'request_id': str(data.get('id') or data.get('request_id') or ''),
            'results': results[:wanted],
        }
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return base | {
            'mode': 'lexical_fallback', 'results': [dict(item) | {'rank': rank + 1} for rank, item in enumerate(shortlisted[:wanted])],
            'fallback_reason': f'{type(exc).__name__}: {str(exc)[:180]}',
        }


def rerank_required(query: str, candidates: list[dict[str, Any]], top_n: int | None = None, instruct: str = '') -> dict[str, Any]:
    """Run qwen3-rerank for production credit audit or fail closed.

    Local lexical ranking is only a candidate-generation primitive because
    qwen3-rerank needs a bounded candidate list.  It is never returned as a
    substitute ordering and never constitutes evidence on its own.
    """
    if not configured_rerank():
        raise RerankUnavailable('qwen3-rerank 未配置或未获财务数据传输授权')
    try:
        shortlisted, recall_mode = hybrid_recall(query, candidates)
    except EmbeddingUnavailable as exc:
        raise RerankUnavailable(str(exc)) from exc
    wanted = min(len(shortlisted), top_n or RERANK_TOP_N)
    if not shortlisted:
        return {'mode': 'empty', 'query': query, 'candidate_count': 0, 'top_n': 0, 'model': RERANK_MODEL, 'recall_mode': recall_mode, 'results': []}
    payload = {
        'model': RERANK_MODEL,
        'query': clip_text_to_tokens(query, RERANK_DOCUMENT_TOKEN_BUDGET),
        'documents': [_rerank_document(item) for item in shortlisted],
        'top_n': wanted,
        'instruct': instruct or 'Given a credit-review evidence request, retrieve passages that directly prove the requested fact. Prefer primary source evidence over commentary.',
    }
    request = Request(
        RERANK_BASE_URL.rstrip('/') + '/reranks', data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Authorization': f'Bearer {RERANK_API_KEY}', 'Content-Type': 'application/json'}, method='POST',
    )
    try:
        with urlopen(request, timeout=RERANK_TIMEOUT_SECONDS) as response:  # nosec B310: deployment-configured endpoint
            data = json.loads(response.read().decode('utf-8'))
        rows = data.get('results') if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise RerankUnavailable('rerank 响应缺少 results')
        results: list[dict[str, Any]] = []
        used: set[int] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            index = row.get('index')
            if not isinstance(index, int) or index < 0 or index >= len(shortlisted) or index in used:
                continue
            used.add(index)
            try:
                score = float(row.get('relevance_score'))
            except (TypeError, ValueError):
                score = None
            results.append(dict(shortlisted[index]) | {'rank': len(results) + 1, 'rerank_index': index, 'relevance_score': score})
        if not results:
            raise RerankUnavailable('rerank 响应未返回有效索引')
        return {'mode': 'qwen3-rerank', 'query': query, 'candidate_count': len(shortlisted), 'top_n': wanted, 'recall_mode': recall_mode,
                'model': RERANK_MODEL, 'request_id': str(data.get('id') or data.get('request_id') or ''), 'results': results[:wanted]}
    except RerankUnavailable:
        raise
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise RerankUnavailable(f'qwen3-rerank 调用失败: {type(exc).__name__}: {str(exc)[:180]}') from exc
