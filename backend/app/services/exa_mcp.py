"""Bounded, no-key Exa MCP client for public corporate due diligence.

This adapter never sends contracts, financial statements, exposure snapshots
or contact details to Exa.  It sends only the corporate identity supplied in
the credit case, retains the original source URLs/excerpts for review, and
never makes a credit or approval decision.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import get_model_runtime_config


# Keep this at Exa's documented raw Streamable-HTTP MCP endpoint.  The
# no-key server advertises ``web_search_exa`` and ``web_fetch_exa`` itself;
# appending a non-standard tool filter changes the server surface and makes
# the integration needlessly dependent on an advanced-tool variant.
EXA_MCP_URL = 'https://mcp.exa.ai/mcp'
_HEADERS = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}
_HIGH = ('失信', '被执行', '终本', '破产', '重整', '清算', '债券违约', '债务违约', 'default', 'bankruptcy', 'liquidation')
_MID = ('诉讼', '仲裁', '行政处罚', '立案', '监管处罚', '评级下调', 'credit rating', 'rating downgrade', 'lawsuit', 'arbitration', 'enforcement', 'penalty')


class ExaMcpError(RuntimeError):
    pass


def _sse_json(text: str) -> dict[str, Any]:
    for line in (text or '').splitlines():
        if line.startswith('data:'):
            try:
                return json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ExaMcpError('Exa MCP 返回了无法解析的响应') from exc


def _call(method: str, params: dict[str, Any], request_id: int, session_id: str | None='') -> tuple[dict[str, Any], str]:
    config = get_model_runtime_config()
    timeout = float(config.get('external_due_diligence_timeout_seconds') or 25)
    headers = dict(_HEADERS)
    if session_id:
        headers['Mcp-Session-Id'] = session_id
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.post(EXA_MCP_URL, headers=headers, json={'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
    except httpx.HTTPError as exc:
        raise ExaMcpError(f'Exa MCP 网络连接失败：{str(exc)[:160]}') from exc
    payload = _sse_json(response.text)
    if response.status_code >= 400 or payload.get('error'):
        detail = ((payload.get('error') or {}).get('message') or response.text or f'HTTP {response.status_code}').strip()
        raise ExaMcpError(str(detail)[:300])
    return payload.get('result') or {}, response.headers.get('mcp-session-id') or session_id or ''


def _search(arguments: dict[str, Any]) -> dict[str, Any]:
    initialized, session_id = _call('initialize', {
        'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'contractguard', 'version': '1.0'},
    }, 1)
    if not session_id or not initialized:
        raise ExaMcpError('Exa MCP 未返回有效会话')
    # MCP notifications intentionally have no id and normally return 202.
    config = get_model_runtime_config()
    try:
        with httpx.Client(timeout=float(config.get('external_due_diligence_timeout_seconds') or 25), follow_redirects=True) as client:
            client.post(EXA_MCP_URL, headers={**_HEADERS, 'Mcp-Session-Id': session_id}, json={
                'jsonrpc': '2.0', 'method': 'notifications/initialized', 'params': {},
            })
    except httpx.HTTPError:
        # The server has already initialized the session.  A notification
        # transport failure should not suppress the read-only search attempt.
        pass
    # ``web_search_exa`` has a deliberately small public schema: query and
    # numResults only.  Do not pass old advanced-search-only fields such as
    # category, date filters or highlight settings to this default tool.
    result, _ = _call('tools/call', {'name': 'web_search_exa', 'arguments': {
        'query': str(arguments.get('query') or '').strip(),
        'numResults': int(arguments.get('numResults') or 6),
    }}, 2, session_id)
    return result


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {'text': value}
    return {}


def _tool_data(result: dict[str, Any]) -> dict[str, Any]:
    content = result.get('content') or []
    for item in content if isinstance(content, list) else []:
        if isinstance(item, dict) and item.get('type') == 'text':
            data = _as_dict(item.get('text'))
            if data:
                return data
    structured = result.get('structuredContent')
    return _as_dict(structured)


def _find_results(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ('results', 'searchResults', 'data'):
            value = payload.get(key)
            if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                return value
            if isinstance(value, dict):
                nested = _find_results(value)
                if nested:
                    return nested
    return []


def _markdown_sources(payload: dict[str, Any], query_kind: str) -> list[dict[str, Any]]:
    """Recover source cards if the default Exa tool returns clean Markdown.

    ``web_search_exa`` is documented as returning ready-to-use text rather
    than a fixed JSON results schema.  We retain each URL plus its surrounding
    excerpt so the reviewer can open and verify the original page.  Structured
    results still use the richer parsing path above.
    """
    text = str(payload.get('text') or '').strip()
    if not text:
        return []
    rows: list[dict[str, Any]] = []
    # The default tool emits one human-readable block per hit:
    # ``Title: ... / URL: ... / Published: ... / Highlights: ...``.  Parse
    # those blocks first; a URL-neighbourhood heuristic merges adjacent hits
    # and can mislabel the title as the literal word "URL".
    blocks = re.split(r'(?m)^\s*---\s*$', text)
    for block in blocks:
        title_match = re.search(r'(?mi)^Title:\s*(.+)$', block)
        url_match = re.search(r'(?mi)^URL:\s*(https?://\S+)', block)
        if not url_match:
            continue
        url = url_match.group(1).rstrip('.,;，。')
        published_match = re.search(r'(?mi)^Published:\s*(.+)$', block)
        highlights_match = re.search(r'(?ims)^Highlights:\s*(.*)$', block)
        title = (title_match.group(1).strip() if title_match else 'Exa 公开检索来源')
        excerpt = re.sub(r'\s+', ' ', (highlights_match.group(1) if highlights_match else block)).strip()
        rows.append({
            'url': url[:1000], 'title': title[:300], 'excerpt': excerpt[:1200],
            'published_at': (published_match.group(1).strip() if published_match else '')[:60], 'source_type': query_kind,
        })
    if rows:
        return rows

    # Keep a narrow fallback for a future text layout without the documented
    # labels.  It is intentionally used only if no labelled Exa blocks exist.
    urls = list(dict.fromkeys(re.findall(r'https?://[^\s)\]>"}]+', text)))
    for url in urls[:12]:
        position = text.find(url)
        start = max(0, position - 380)
        end = min(len(text), position + len(url) + 720)
        excerpt = re.sub(r'\s+', ' ', text[start:end]).strip()
        before = text[start:position].strip().splitlines()
        title = next((line.strip(' #-:*') for line in reversed(before) if line.strip()), '')
        rows.append({
            'url': url, 'title': title[:300] or 'Exa 公开检索来源', 'excerpt': excerpt[:1200],
            'published_at': '', 'source_type': query_kind,
        })
    return rows


def _source(result: dict[str, Any], query_kind: str) -> dict[str, Any] | None:
    url = str(result.get('url') or result.get('link') or '').strip()
    title = str(result.get('title') or result.get('name') or '').strip()
    excerpt = str(result.get('summary') or result.get('text') or result.get('snippet') or '').strip()
    highlights = result.get('highlights') or []
    if isinstance(highlights, list) and highlights:
        excerpt = ' '.join(str(item) for item in highlights[:2]) or excerpt
    if not (url or title or excerpt):
        return None
    return {
        'url': url[:1000], 'title': title[:300] or '未命名公开来源', 'excerpt': re.sub(r'\s+', ' ', excerpt)[:1200],
        'published_at': str(result.get('publishedDate') or result.get('published_at') or result.get('published_date') or '')[:60],
        'source_type': query_kind,
    }


def _classify(source: dict[str, Any], identity_confidence: str) -> dict[str, Any] | None:
    haystack = ' '.join(str(source.get(key) or '') for key in ('title', 'excerpt', 'url')).lower()
    if not haystack:
        return None
    if any(term.lower() in haystack for term in _HIGH):
        code, severity = 'EXTERNAL_MAJOR_ADVERSE_LEAD', 'high'
    elif any(term.lower() in haystack for term in _MID):
        code, severity = 'EXTERNAL_ADVERSE_LEAD', 'mid'
    else:
        return None
    fingerprint = hashlib.sha256(f'{code}|{source.get("url")}|{source.get("title")}'.encode('utf-8')).hexdigest()[:20].upper()
    return {
        'finding_id': f'EXA-{fingerprint}', 'code': code, 'severity': severity,
        'title': source.get('title'), 'summary': source.get('excerpt') or source.get('title'),
        'source': source, 'identity_confidence': identity_confidence,
        'status': 'pending_reviewer', 'requires_reviewer_confirmation': True,
    }


def run_external_due_diligence(case: dict[str, Any], on_event=None) -> dict[str, Any]:
    """Search public-company credit context with three bounded, read-only queries.

    A clean result is deliberately worded as ``no_verifiable_findings`` rather
    than ``no_risk``: anonymous web search is neither complete nor an official
    enterprise-credit database.  Third-party credit reports and recent business
    updates remain reference sources unless a reviewer explicitly adopts them.
    """
    config = get_model_runtime_config()
    now = datetime.now(timezone.utc)
    identity = {
        'customer_name': str(case.get('customer_name') or '').strip(),
        'enterprise_code': str(case.get('enterprise_code') or '').strip(),
        'registered_location': str(case.get('registered_location') or '').strip(),
    }
    result: dict[str, Any] = {
        'provider': 'exa_mcp', 'status': 'not_started', 'searched_at': now.timestamp(), 'identity': identity,
        'identity_confidence': 'strong' if identity['enterprise_code'] else ('contextual' if identity['registered_location'] else 'name_only'),
        'queries': [], 'sources': [], 'findings': [], 'message': '',
    }
    if not config.get('external_due_diligence_enabled', True):
        result.update(status='disabled', message='系统管理员已关闭 Exa 公开信息尽调')
        return result
    if len(identity['customer_name']) < 2:
        result.update(status='skipped', message='客户名称不足，未执行公开信息尽调')
        return result
    entity = identity['customer_name']
    qualifier = ' '.join(item for item in (identity['enterprise_code'], identity['registered_location']) if item)
    end_date = now.date().isoformat()
    start_date = (now - timedelta(days=int(config.get('external_due_diligence_recent_days') or 180))).date().isoformat()
    queries = [
        ('adverse', f'{entity} {qualifier} 失信 被执行 诉讼 仲裁 破产 重整 行政处罚 信用评级 评级下调 债券违约'),
        ('credit_profile', f'{entity} {qualifier} 第三方企业信用报告 信用评级 评级展望 评级下调 信用风险 债券评级'),
        ('business', f'{entity} {qualifier} 近期经营情况 业绩预告 财务业绩 中标 订单 合作 重大合同 经营动态 新闻'),
    ]
    errors: list[str] = []
    sources: list[dict[str, Any]] = []
    def run_query(kind: str, query: str) -> tuple[str, list[dict[str, Any]], str]:
        # The public ``web_search_exa`` tool accepts only ``query`` and
        # ``numResults``.  Preserve the desired recency window in natural
        # language rather than sending parameters that its schema rejects.
        scoped_query = query
        if kind in {'credit_profile', 'business'}:
            scoped_query = f'{query}；优先 {start_date} 至 {end_date} 期间的报道和公告'
        arguments: dict[str, Any] = {
            'query': scoped_query.strip(), 'numResults': int(config.get('external_due_diligence_max_results') or 6),
        }
        try:
            payload = _tool_data(_search(arguments))
            rows = []
            for raw in _find_results(payload):
                item = _source(raw, kind)
                if item:
                    rows.append(item)
            if not rows:
                rows = _markdown_sources(payload, kind)
            return kind, rows, ''
        except ExaMcpError as exc:
            return kind, [], str(exc)
    for kind, query in queries:
        # The recency constraint applies to the credit-profile and operating
        # context searches.  Keep it in the audit payload so the reviewer can
        # see exactly which searches were time-bounded.
        is_recent_context = kind in {'credit_profile', 'business'}
        result['queries'].append({'kind': kind, 'query': query.strip(), 'start_date': start_date if is_recent_context else '', 'end_date': end_date if is_recent_context else ''})
    if on_event:
        on_event({'type': 'external_due_diligence', 'message': 'Exa 公开信息尽调：并发检索司法监管、第三方信用报告/评级与近期经营动态。'})
    # External web lookup is supplementary.  Run its three fixed queries in
    # parallel so a throttled anonymous endpoint cannot serially delay the
    # financial evidence workflow.
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix='exa-dd') as executor:
        pending = [executor.submit(run_query, kind, query) for kind, query in queries]
        for future in as_completed(pending):
            kind, rows, error = future.result()
            sources.extend(rows)
            if error:
                errors.append(error)
    deduped: dict[str, dict[str, Any]] = {}
    for source in sources:
        key = source.get('url') or f"{source.get('title')}|{source.get('excerpt')[:80]}"
        deduped[key] = source
    result['sources'] = list(deduped.values())[:24]
    findings = [_classify(source, result['identity_confidence']) for source in result['sources']]
    result['findings'] = [item for item in findings if item]
    if errors and not result['sources']:
        message = errors[0]
        result.update(status='rate_limited' if 'rate limit' in message.lower() else 'unavailable', message=message)
    elif errors:
        result.update(status='partial', message='；'.join(errors)[:500])
    elif result['findings']:
        result.update(status='review_required', message=f'已完成公开信用/经营信息检索，发现 {len(result["findings"])} 条待审核风险线索')
    else:
        result.update(status='no_verifiable_findings', message='已完成公开信用/经营信息检索，未发现可自动归属的风险线索；这不代表客户无风险。')
    return result


def probe_exa_mcp() -> dict[str, Any]:
    """Validate Exa's raw MCP endpoint and its documented default tools.

    This intentionally does not execute a search, so the settings check does
    not consume anonymous-search quota or send customer data.
    """
    started = time.perf_counter()
    try:
        result, session = _call('initialize', {
            'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'contractguard', 'version': '1.0'},
        }, 1)
        if not session or not result:
            return {'ok': False, 'latency_ms': round((time.perf_counter() - started) * 1000), 'message': 'Exa MCP 未返回会话'}
        config = get_model_runtime_config()
        with httpx.Client(timeout=float(config.get('external_due_diligence_timeout_seconds') or 25), follow_redirects=True) as client:
            client.post(EXA_MCP_URL, headers={**_HEADERS, 'Mcp-Session-Id': session}, json={
                'jsonrpc': '2.0', 'method': 'notifications/initialized', 'params': {},
            })
        listing, _ = _call('tools/list', {}, 2, session)
        names = {str(item.get('name') or '') for item in (listing.get('tools') or []) if isinstance(item, dict)}
        expected = {'web_search_exa', 'web_fetch_exa'}
        missing = expected - names
        return {
            'ok': not missing, 'latency_ms': round((time.perf_counter() - started) * 1000),
            'tools': sorted(names & expected),
            'message': 'Exa 无 Key MCP 连接成功，已确认 web_search_exa / web_fetch_exa' if not missing
                       else f'Exa MCP 缺少默认工具：{", ".join(sorted(missing))}',
        }
    except ExaMcpError as exc:
        return {'ok': False, 'latency_ms': round((time.perf_counter() - started) * 1000), 'message': str(exc)}
    except httpx.HTTPError as exc:
        return {'ok': False, 'latency_ms': round((time.perf_counter() - started) * 1000), 'message': f'Exa MCP 网络连接失败：{str(exc)[:160]}'}
