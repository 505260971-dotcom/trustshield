import asyncio
import json
import os
import threading
import time
import traceback
import uuid

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import store
from .auth import current_user, require, router as auth_router
from .config import (
    CORS_ORIGINS, EMBEDDING_ALLOW_REMOTE_FINANCIAL_DATA, EMBEDDING_ENABLED,
    EMBEDDING_MODEL, FINANCIAL_LLM_MODEL, LLM_API_BASE, LLM_API_KEY, LLM_MODEL,
    RERANK_ALLOW_REMOTE_FINANCIAL_DATA, RERANK_ENABLED, RERANK_MODEL, UPLOAD_DIR,
    configured_embedding, configured_financial_llm, configured_llm, configured_rerank,
    ensure_model_runtime_config_file, secure_runtime_ready,
)
from .services.export_docx import export_revised_docx
from .services.integrations import APPROVAL_ROLES, crm, oa
from .services.translate import run_translate
from .services.credit import assess_credit_compliance, assess_customer_binding
from .services.parse import PARSER_VERSION, parse_contract, read_paragraphs, text_asset_status
from .services.signability import calculate_signability

app = FastAPI(title='ContractGuard 合同评审协作中心', version='3.0')
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=['GET','POST','PATCH','DELETE'], allow_headers=['Authorization','Content-Type'])
app.include_router(auth_router)

# Short-lived runtime state only; sensitive report and mapping are persisted encrypted.
JOBS: dict[str, dict] = {}
TJOBS: dict[str, dict] = {}
CREDIT_JOBS: dict[str, dict] = {}
REVIEW_JOB_LOCK = threading.RLock()
CREDIT_JOB_LOCK = threading.RLock()
ALLOWED_CONTRACT = {'.docx','.pdf','.txt','.xlsx','.xls','.png','.jpg','.jpeg','.webp','.bmp'}
ALLOWED_ATTACHMENT = ALLOWED_CONTRACT
EXPORT_MODES = {'revised', 'plain', 'bilingual'}


def _assert_credit_access(case_id: str, user: dict) -> dict:
    """Business applicants may access only the credit cases they created."""
    item = store.get_credit_case(case_id)
    if not item:
        raise HTTPException(404, '信用审核案件不存在')
    if user.get('role') == 'business' and item.get('created_by') != user.get('id'):
        raise HTTPException(403, '无权访问该信用审核案件')
    return item


def _publish_credit_event(assessment_id: str, event: dict) -> None:
    """Publish a small, browser-safe progress event for a running assessment.

    Credit assessments run in a daemon thread.  The event log is deliberately
    kept in short-lived memory: the encrypted assessment report remains the
    source of record, while this log lets a reviewer follow the same run before
    the final report has been persisted.
    """
    with CREDIT_JOB_LOCK:
        job = CREDIT_JOBS.get(assessment_id)
        if not job:
            return
        job['event_seq'] = int(job.get('event_seq') or 0) + 1
        item = {
            'event_id': f'{assessment_id}:{job["event_seq"]}',
            'created_at': time.time(),
            **(event or {}),
        }
        job.setdefault('events', []).append(item)
        event_type = str(item.get('type') or '')
        if event_type in {'agent_action', 'tool_result', 'claim_validated'}:
            job['active'] = {
                'type': event_type,
                'message': item.get('message') or item.get('result_summary') or item.get('reason_summary') or '',
                'step': item.get('step'),
                'tool': item.get('tool'),
                'updated_at': item['created_at'],
            }
        for source in item.get('sources') or []:
            source_id = str(source.get('chunk_id') or '')
            if not source_id:
                continue
            existing = {str(row.get('chunk_id') or ''): row for row in job.setdefault('live_evidence', [])}
            existing[source_id] = source
            job['live_evidence'] = list(existing.values())[-120:]
        for claim in item.get('claims') or []:
            claim_id = str(claim.get('claim_id') or '')
            if not claim_id:
                continue
            existing = {str(row.get('claim_id') or ''): row for row in job.setdefault('live_claims', [])}
            existing[claim_id] = claim
            job['live_claims'] = list(existing.values())[-80:]


def _publish_credit_step(assessment_id: str, step: str) -> None:
    with CREDIT_JOB_LOCK:
        job = CREDIT_JOBS.get(assessment_id)
        if not job:
            return
        job.setdefault('steps', []).append(str(step))
    _publish_credit_event(assessment_id, {'type': 'milestone', 'message': str(step)})


def _publish_review_event(job_id: str, event: dict) -> None:
    """Publish live, source-bound contract review progress to the UI."""
    with REVIEW_JOB_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job['event_seq'] = int(job.get('event_seq') or 0) + 1
        item = {'event_id': f'{job_id}:{job["event_seq"]}', 'created_at': time.time(), **(event or {})}
        job.setdefault('events', []).append(item)
        if item.get('type') in {'agent_update', 'milestone', 'error', 'completed'}:
            job['active'] = {
                'type': item.get('type'), 'message': item.get('message') or '',
                'step_index': item.get('step_index'), 'updated_at': item['created_at'],
            }
        for source in item.get('sources') or []:
            source_id = f"{source.get('clause_id') or ''}:{source.get('source_ref') or ''}:{source.get('evidence_quote') or ''}"
            if not source_id.strip(':'):
                continue
            existing = {f"{row.get('clause_id') or ''}:{row.get('source_ref') or ''}:{row.get('evidence_quote') or ''}": row
                        for row in job.setdefault('live_evidence', [])}
            existing[source_id] = source
            job['live_evidence'] = list(existing.values())[-120:]


def _publish_review_step(job_id: str, step: str) -> None:
    with REVIEW_JOB_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job.setdefault('steps', []).append(str(step))

@app.on_event('startup')
def _startup():
    store.init_db()
    # config.json is the sole runtime model configuration source.  This also
    # upgrades the earlier encrypted-file format to the requested plain JSON.
    ensure_model_runtime_config_file()

@app.get('/api/health')
async def health(user=Depends(current_user)):
    ollama_ok=False; llm_ok=False
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            ollama_ok=(await c.get('http://localhost:11434/api/tags')).status_code==200
    except Exception: pass
    if configured_llm():
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r=await c.post(f'{LLM_API_BASE}/chat/completions',headers={'Authorization':f'Bearer {LLM_API_KEY}'},json={'model':LLM_MODEL,'messages':[{'role':'user','content':'ok'}],'max_tokens':1})
                llm_ok=r.status_code<500
        except Exception: pass
    return {'ollama':ollama_ok,'llm':llm_ok,'llm_configured':configured_llm(),'secure_runtime':secure_runtime_ready()}

@app.get('/api/rules')
async def rules(user=Depends(current_user)):
    return store.get_rule_version()

@app.get('/api/admin/rule-versions')
async def rule_versions(user=Depends(require('admin:cases'))):
    return {'items': store.list_rule_versions()}

@app.post('/api/admin/rule-versions')
async def rule_draft_create(user=Depends(require('admin:cases'))):
    result = store.create_rule_draft(user)
    store.audit(user, 'rules.draft_create', 'rule_version', result['version'])
    return result

@app.get('/api/admin/rule-versions/{version}')
async def rule_version_get(version: str, user=Depends(require('admin:cases'))):
    result = store.get_rule_version(version)
    if not result['rules']:
        raise HTTPException(404, '规则版本不存在')
    return result

@app.patch('/api/admin/rule-versions/{version}/rules/{rule_id}')
async def rule_definition_update(version: str, rule_id: str, body: dict, user=Depends(require('admin:cases'))):
    try:
        result = store.update_rule_definition(version, rule_id, body, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'rules.definition_update', 'rule', f'{version}:{rule_id}', {'fields': list(body.keys())})
    return result

@app.post('/api/admin/rule-versions/{version}/publish')
async def rule_version_publish(version: str, user=Depends(require('admin:cases'))):
    try:
        result = store.publish_rule_version(version, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'rules.publish', 'rule_version', version)
    return result


@app.get('/api/admin/credit-route-versions')
async def credit_route_versions(user=Depends(require('admin:cases'))):
    return {'items': store.list_credit_route_versions()}


@app.post('/api/admin/credit-route-versions')
async def credit_route_draft_create(user=Depends(require('admin:cases'))):
    result = store.create_credit_route_draft(user)
    store.audit(user, 'credit_route.draft_create', 'credit_route_version', result['version'])
    return result


@app.get('/api/admin/credit-route-versions/{version}')
async def credit_route_version_get(version: str, user=Depends(require('admin:cases'))):
    result = store.get_credit_route_version(version)
    if not result.get('version'):
        raise HTTPException(404, '信用审核审批路径版本不存在')
    return result


@app.patch('/api/admin/credit-route-versions/{version}')
async def credit_route_version_update(version: str, body: dict, user=Depends(require('admin:cases'))):
    try:
        result = store.update_credit_route_version(version, body.get('config') or body, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'credit_route.update', 'credit_route_version', version, {'fields': list((body.get('config') or body).keys())})
    return result


@app.post('/api/admin/credit-route-versions/{version}/publish')
async def credit_route_version_publish(version: str, user=Depends(require('admin:cases'))):
    try:
        result = store.publish_credit_route_version(version, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'credit_route.publish', 'credit_route_version', version)
    return result

# Credit review is deliberately separate from contract review.  A contract can
# read a published decision but cannot create, alter, or approve one.
@app.get('/api/credit/decisions')
async def credit_decisions(customer: str='', active_only: bool=True, user=Depends(require('credit:read'))):
    # Business users select a decision only for the customer in the case they
    # are creating; they must not browse the enterprise-wide credit ledger.
    if user.get('role') == 'business' and not customer.strip():
        return {'items': []}
    return {'items': store.list_credit_cases(customer, active_only=active_only)}

@app.get('/api/credit/cases')
async def credit_cases(customer: str='', user=Depends(require('credit:read'))):
    if user.get('role') == 'business':
        return {'items': store.list_credit_cases(customer, created_by=user.get('id'))}
    return {'items': store.list_credit_cases(customer)}

@app.post('/api/credit/cases')
async def credit_case_create(body: dict, user=Depends(require('credit:create'))):
    try:
        result = store.create_credit_case(body.get('customer_name', ''), body.get('conditions') or {}, body.get('request_note', ''), user, body.get('business_type', '一般'))
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'credit.create', 'credit_case', result['case_id'], {'customer': result['customer_name'], 'version': result['version']})
    return result

@app.patch('/api/credit/cases/{case_id}')
async def credit_case_update(case_id: str, body: dict, user=Depends(require('credit:manage'))):
    try:
        current = _assert_credit_access(case_id, user)
        conditions = body['conditions'] if 'conditions' in body else current['conditions']
        request_note = body['request_note'] if 'request_note' in body else current.get('request_note', '')
        result = store.update_credit_case(case_id, conditions, request_note, user, body.get('reviewer_note', ''))
        if 'business_type' in body:
            result = store.set_credit_business_type(case_id, body.get('business_type'), user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'credit.update', 'credit_case', case_id)
    return result

@app.post('/api/credit/cases/{case_id}/submit')
async def credit_case_submit(case_id: str, user=Depends(require('credit:manage'))):
    try: result = store.submit_credit_case(case_id, user)
    except ValueError as e: raise HTTPException(400, str(e))
    store.audit(user, 'credit.submit', 'credit_case', case_id)
    return result

@app.post('/api/credit/cases/{case_id}/decision')
async def credit_case_decision(case_id: str, body: dict, user=Depends(require('credit:approve'))):
    try: result = store.decide_credit_case(case_id, body.get('decision', ''), body.get('note', ''), user)
    except ValueError as e: raise HTTPException(400, str(e))
    store.audit(user, 'credit.decision', 'credit_case', case_id, {'decision': body.get('decision')})
    return result


@app.post('/api/credit/cases/{case_id}/resubmit')
async def credit_case_resubmit(case_id: str, user=Depends(require('credit:create'))):
    _assert_credit_access(case_id, user)
    try:
        result = store.resubmit_credit_case(case_id, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'credit.resubmit', 'credit_case', case_id)
    return result

@app.delete('/api/credit/cases/{case_id}')
async def credit_case_delete(case_id: str, user=Depends(require('admin:cases'))):
    try:
        result = store.delete_historical_credit_case(case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'credit.delete_historical', 'credit_case', case_id,
                {'customer': result['customer_name'], 'version': result['version'], 'status': result['status'], 'permanent': True})
    return {'deleted': True, **result}


@app.get('/api/credit/model')
async def credit_model(user=Depends(require('credit:read'))):
    return store.get_credit_model()


@app.get('/api/credit/cases/{case_id}/documents')
async def credit_documents(case_id: str, user=Depends(require('credit:read'))):
    _assert_credit_access(case_id, user)
    return {'items': store.list_credit_documents(case_id)}


@app.get('/api/credit/cases/{case_id}/documents/{document_id}/preview')
async def credit_document_preview(case_id: str, document_id: str, user=Depends(require('credit:read'))):
    """Return normalized source records for the evidence comparison pane.

    The browser receives source-bound text records, not an internal storage
    path.  Each record retains the parser's stable source_ref and page/table
    metadata so Agent evidence can be highlighted without guessing offsets in
    a DOCX, PDF, spreadsheet, or OCR result.
    """
    _assert_credit_access(case_id, user)
    item = store.get_credit_document(case_id, document_id)
    if not item:
        raise HTTPException(404, '信用审核材料不存在')
    asset = store.get_credit_document_text_asset(document_id, item.get('content_hash') or '')
    records = (asset or {}).get('records') or []
    status = (asset or {}).get('status') or item.get('text_status') or 'pending'
    error = (asset or {}).get('error') or item.get('text_error') or ''
    # Historical uploads may predate encrypted text assets.  Parse them lazily
    # so the new preview remains useful without changing the stored original.
    if asset is None and os.path.isfile(item.get('stored_path') or ''):
        try:
            records = await asyncio.to_thread(read_paragraphs, item['stored_path'])
            status = text_asset_status(records)
        except Exception as exc:
            status = 'failed'
            error = str(exc)[:500]
    public_document = {key: value for key, value in item.items() if key != 'stored_path'}
    public_document['text_record_count'] = len(records)
    store.audit(user, 'credit.document_preview', 'credit_document', document_id, {'case_id': case_id, 'record_count': len(records)})
    return {
        'document': public_document,
        'records': records,
        'status': status,
        'error': error,
        'total': len(records),
    }


@app.post('/api/credit/cases/{case_id}/documents')
async def credit_document_upload(case_id: str, file: UploadFile=File(...), document_type: str=Form('other'), user=Depends(require('credit:create'))):
    _assert_credit_access(case_id, user)
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ALLOWED_ATTACHMENT:
        raise HTTPException(400, '信用审核材料仅支持 DOCX、PDF、XLSX、TXT、PNG、JPG 格式')
    safe_name = os.path.basename(file.filename or 'credit-document')
    if not safe_name or len(safe_name) > 255:
        raise HTTPException(400, '信用审核材料文件名无效')
    folder = os.path.join(UPLOAD_DIR, 'credit-materials', case_id)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'{uuid.uuid4().hex}_{safe_name}')
    await _write_upload(file, path)
    try:
        item = store.add_credit_document(case_id, document_type, safe_name, path, user)
    except ValueError as exc:
        if os.path.exists(path):
            os.remove(path)
        raise HTTPException(400, str(exc))
    # Build the encrypted text asset at upload time.  A source file remains
    # available even if local OCR is not installed; the status tells reviewers
    # exactly why it cannot yet participate in text/RAG extraction.
    try:
        records = await asyncio.to_thread(read_paragraphs, path)
        text_status = text_asset_status(records)
        await asyncio.to_thread(store.save_credit_document_text_asset, item['document_id'], item['content_hash'], records, PARSER_VERSION, text_status)
        item['text_status'] = text_status
        item['text_record_count'] = len(records)
    except Exception as exc:
        await asyncio.to_thread(store.save_credit_document_text_asset, item['document_id'], item['content_hash'], None, PARSER_VERSION, 'failed', str(exc))
        item['text_status'] = 'failed'
        item['text_error'] = str(exc)[:300]
    store.audit(user, 'credit.document_upload', 'credit_case', case_id, {'document_id': item['document_id'], 'document_type': document_type})
    return item


@app.get('/api/credit/cases/{case_id}/documents/{document_id}/download')
async def credit_document_download(case_id: str, document_id: str, user=Depends(require('credit:read'))):
    _assert_credit_access(case_id, user)
    item = store.get_credit_document(case_id, document_id)
    if not item or not os.path.isfile(item.get('stored_path') or ''):
        raise HTTPException(404, '信用审核材料不存在')
    store.audit(user, 'credit.document_download', 'credit_document', document_id, {'case_id': case_id})
    return FileResponse(item['stored_path'], filename=item['original_name'])


@app.get('/api/credit/cases/{case_id}/exposure')
async def credit_exposure_get(case_id: str, user=Depends(require('credit:read'))):
    _assert_credit_access(case_id, user)
    return store.latest_credit_exposure_snapshot(case_id) or {'payload': None}


@app.post('/api/credit/cases/{case_id}/exposure')
async def credit_exposure_save(case_id: str, body: dict, user=Depends(require('credit:manage'))):
    _assert_credit_access(case_id, user)
    try:
        result = store.save_credit_exposure_snapshot(case_id, body, user, source=str(body.get('source') or 'manual'))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    store.audit(user, 'credit.exposure_snapshot', 'credit_case', case_id, {'source': result['source'], 'captured_at': result['captured_at']})
    return result


def _run_credit_assessment(assessment_id: str):
    job = CREDIT_JOBS[assessment_id]
    try:
        # ``run_credit_assessment`` can legitimately spend longer than one UI
        # polling window in its first remote ReAct turn.  Publish an immediate
        # heartbeat so an empty step list is never mistaken for a dead worker.
        _publish_credit_step(assessment_id, '任务已启动：正在载入信用审核材料与 CRM/ERP 额度占用数据')
        _publish_credit_step(assessment_id, '正在执行信用审核 Agent；单轮模型调用最长可能等待 45 秒')
        from .graph.credit_graph import run_credit_assessment
        case = store.get_credit_case(job['case_id'])
        documents = [store.get_credit_document(job['case_id'], item['document_id']) for item in store.list_credit_documents(job['case_id'])]
        documents = [item for item in documents if item]
        exposure = store.latest_credit_exposure_snapshot(job['case_id'])
        report, evidence = run_credit_assessment(
            case, documents, (exposure or {}).get('payload'), store.get_credit_model(job['model_version']),
            on_step=lambda step: _publish_credit_step(assessment_id, step),
            on_event=lambda event: _publish_credit_event(assessment_id, event),
        )
        completed = store.finish_credit_assessment(assessment_id, report, evidence)
        with CREDIT_JOB_LOCK:
            job.update(status='done', result=completed)
            _publish_credit_event(assessment_id, {'type': 'completed', 'message': '信用审核 Agent 已完成，正在保存评估记录'})
    except Exception as exc:
        try:
            store.finish_credit_assessment(assessment_id, None, [], str(exc))
        except Exception:
            pass
        with CREDIT_JOB_LOCK:
            job.update(status='error', error=str(exc)[:1000])
        _publish_credit_event(assessment_id, {'type': 'error', 'message': str(exc)[:500]})


@app.post('/api/credit/cases/{case_id}/assessments')
async def credit_assessment_start(case_id: str, body: dict | None=None, user=Depends(require('credit:manage'))):
    _assert_credit_access(case_id, user)
    if not secure_runtime_ready():
        raise HTTPException(503, '安全运行环境未就绪：请配置 AUTH_SECRET 与 DATA_ENCRYPTION_KEY')
    try:
        assessment = store.start_credit_assessment(case_id, user, str((body or {}).get('model_version') or ''))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    with CREDIT_JOB_LOCK:
        CREDIT_JOBS[assessment['assessment_id']] = {
            'status': 'running', 'case_id': case_id, 'model_version': assessment['model_version'],
            'steps': [], 'events': [], 'live_evidence': [], 'live_claims': [],
            'active': {'type': 'starting', 'message': '正在准备信用审核材料'},
            'event_seq': 0, 'result': None, 'error': '', 'started_at': time.time(),
        }
    threading.Thread(target=_run_credit_assessment, args=(assessment['assessment_id'],), daemon=True).start()
    store.audit(user, 'credit.assessment_start', 'credit_assessment', assessment['assessment_id'], {'case_id': case_id, 'model_version': assessment['model_version']})
    return assessment


@app.get('/api/credit/runtime-readiness')
async def credit_runtime_readiness(user=Depends(require('credit:manage'))):
    """Expose non-secret readiness information to the credit reviewer.

    This makes a deliberately fail-closed rerank path diagnosable before a
    reviewer uploads financial material.  No key, endpoint credential, or
    customer data is returned.
    """
    financial_ready = configured_financial_llm()
    rerank_ready = configured_rerank()
    embedding_ready = configured_embedding()
    return {
        'financial_llm': {
            'ready': financial_ready,
            'model': FINANCIAL_LLM_MODEL if financial_ready else '',
            'message': '已就绪' if financial_ready else '未配置 FINANCIAL_LLM_* 或主 LLM_*',
        },
        'rerank': {
            'ready': rerank_ready,
            'enabled': RERANK_ENABLED,
            'data_transfer_authorized': RERANK_ALLOW_REMOTE_FINANCIAL_DATA,
            'model': RERANK_MODEL,
            'message': ('已就绪' if rerank_ready else
                        '未启用或未配置 DashScope qwen3-rerank；正式依据检索会安全失败，不会降级为本地词法排序'),
        },
        'embedding': {
            'ready': embedding_ready,
            'enabled': EMBEDDING_ENABLED,
            'data_transfer_authorized': EMBEDDING_ALLOW_REMOTE_FINANCIAL_DATA,
            'model': EMBEDDING_MODEL,
            'message': ('已就绪：与词法召回做 RRF 融合，再交由 qwen3-rerank 精排' if embedding_ready else
                        '未启用或未配置 embedding；当前使用受控词法召回后交由 qwen3-rerank 精排'),
        },
        'production_ready': financial_ready and rerank_ready and (not EMBEDDING_ENABLED or embedding_ready),
    }


@app.get('/api/credit/cases/{case_id}/assessments/latest')
async def credit_assessment_latest(case_id: str, user=Depends(require('credit:read'))):
    _assert_credit_access(case_id, user)
    return store.latest_credit_assessment(case_id) or {'status': 'none', 'report': None, 'evidence': []}


@app.get('/api/credit/cases/{case_id}/assessments/{assessment_id}')
async def credit_assessment_get(case_id: str, assessment_id: str, user=Depends(require('credit:read'))):
    _assert_credit_access(case_id, user)
    result = store.get_credit_assessment(assessment_id)
    if not result or result.get('case_id') != case_id:
        raise HTTPException(404, '信用审核评估不存在')
    return result


@app.get('/api/credit/cases/{case_id}/assessments/{assessment_id}/status')
async def credit_assessment_status(case_id: str, assessment_id: str, user=Depends(require('credit:read'))):
    _assert_credit_access(case_id, user)
    with CREDIT_JOB_LOCK:
        job = CREDIT_JOBS.get(assessment_id)
        if job and job.get('case_id') == case_id:
            return {key: value for key, value in job.items() if key != 'result'}
    result = store.get_credit_assessment(assessment_id)
    if not result or result.get('case_id') != case_id:
        raise HTTPException(404, '信用审核评估不存在')
    runtime = (result.get('report') or {}).get('audit_runtime') or {}
    return {
        'status': result['status'],
        'steps': (result.get('report') or {}).get('steps', []),
        'events': [],
        'trace': runtime.get('trace') or [],
        'live_evidence': runtime.get('evidence_sources') or [],
        'live_claims': runtime.get('claims') or [],
        'active': {'type': result['status'], 'message': '已载入最近一次信用审核结果'},
        'error': result.get('error', ''),
    }


@app.post('/api/credit/cases/{case_id}/assessments/{assessment_id}/apply')
async def credit_assessment_apply(case_id: str, assessment_id: str, user=Depends(require('credit:manage'))):
    current = _assert_credit_access(case_id, user)
    assessment = store.get_credit_assessment(assessment_id)
    if not assessment or assessment.get('case_id') != case_id or assessment.get('status') != 'done':
        raise HTTPException(409, '尚无可应用的已完成信用审核评估')
    result = assessment.get('report') or {}
    if result.get('runtime_mode') != 'production':
        raise HTTPException(409, '该信用审核结果不是可用的正式 Agent 评估记录，不能应用、审批或绑定合同')
    analysis = result.get('assessment') or {}
    if analysis.get('model_status') != 'ready_for_reviewer' or any(item.get('level') == 'high' for item in analysis.get('risk_flags') or []):
        raise HTTPException(409, '评估存在材料缺失或高风险阻断，不能直接应用建议条件')
    try:
        updated = store.record_credit_reviewer_decision(
            case_id, assessment, analysis.get('recommendation') or current['conditions'], '', 'agent_recommended', user,
            analysis.get('business_type') or current.get('business_type', '一般'),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    store.audit(user, 'credit.assessment_apply', 'credit_case', case_id, {'assessment_id': assessment_id, 'model_version': result.get('model_version')})
    return updated


@app.post('/api/credit/cases/{case_id}/assessments/{assessment_id}/reviewer-decision')
async def credit_reviewer_decision(case_id: str, assessment_id: str, body: dict, user=Depends(require('credit:manage'))):
    """Persist an accountable reviewer adjustment or fallback before approval."""
    current = _assert_credit_access(case_id, user)
    assessment = store.get_credit_assessment(assessment_id)
    try:
        result = store.record_credit_reviewer_decision(
            case_id, assessment, body.get('conditions') or current['conditions'], body.get('reviewer_note', ''),
            body.get('mode', 'reviewer_adjusted'), user, body.get('business_type') or current.get('business_type', '一般'),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    store.audit(user, 'credit.reviewer_decision', 'credit_case', case_id, {
        'assessment_id': assessment_id, 'mode': result.get('review_mode'),
        'has_reviewer_note': bool(result.get('reviewer_note')),
    })
    return result

# ---- Case centre: the primary OA surface ----
@app.get('/api/workbench/tasks')
async def workbench_tasks(limit: int=100, user=Depends(current_user)):
    return {'items': store.my_work_items(user, limit)}

@app.get('/api/workboxes/{bucket}')
async def workbox(bucket: str, limit: int=200, user=Depends(current_user)):
    try:
        return {'items': store.list_workbox(user, bucket, limit)}
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get('/api/customer-workspaces')
async def customer_workspaces(limit: int=200, user=Depends(current_user)):
    return {'items': store.list_customer_workspaces(user, limit)}

@app.get('/api/customer-workspaces/{customer_key}/headroom')
async def customer_headroom(customer_key: str, user=Depends(current_user)):
    result = store.customer_headroom(customer_key, user)
    if not result:
        raise HTTPException(404, '客户不存在或无权查看')
    return result

@app.post('/api/customer-workspaces/{customer_key}/headroom/simulate')
async def customer_headroom_simulate(customer_key: str, body: dict, user=Depends(current_user)):
    try:
        result = store.customer_headroom(customer_key, user, body.get('amount') or body.get('additional_amount') or 0)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not result:
        raise HTTPException(404, '客户不存在或无权查看')
    store.audit(user, 'customer.headroom_simulate', 'customer', result['customer_key'], {'amount': result['simulation']['amount'], 'status': result['simulation']['status']})
    return result

@app.get('/api/customer-workspaces/{customer_key}')
async def customer_workspace_detail(customer_key: str, user=Depends(current_user)):
    result = store.get_customer_workspace(customer_key, user)
    if not result:
        raise HTTPException(404, '客户不存在或无权查看')
    return result

@app.get('/api/case-center/cases')
async def case_center_list(scope: str='all', limit: int=100, user=Depends(current_user)):
    if scope not in {'all', 'mine', 'inbox'}:
        raise HTTPException(400, 'scope 仅支持 all、mine 或 inbox')
    return {'items': store.list_case_center(user, scope, limit)}

@app.post('/api/case-center/cases')
async def case_center_create(body: dict, user=Depends(require('review:create'))):
    try:
        credit_case_id = str(body.get('credit_case_id') or '').strip()
        if credit_case_id:
            credit = store.require_active_credit_case(credit_case_id)
            if credit.get('customer_name') != str(body.get('customer_name') or '').strip():
                raise ValueError('信用审核版本客户与合同案件客户不一致')
        result = store.create_case_center(str(body.get('customer_name') or ''), str(body.get('business_type') or '一般'),
                                          str(body.get('request_note') or ''), user, credit_case_id,
                                          str(body.get('priority') or 'normal'), body.get('due_at'))
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'case.create', 'case', result['case_id'], {'customer': body.get('customer_name')})
    return result

@app.get('/api/case-center/cases/{case_id}')
async def case_center_detail(case_id: str, user=Depends(current_user)):
    result = store.get_case_center(case_id, user)
    if not result:
        raise HTTPException(404, '案件不存在')
    return result

@app.delete('/api/case-center/cases/{case_id}')
async def case_center_delete(case_id: str, user=Depends(require('admin:cases'))):
    try:
        result = store.delete_historical_contract_case(case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'case.delete_historical', 'case', case_id,
                {'customer': result['customer_name'], 'stage': result['stage'], 'permanent': True})
    return {'deleted': True, **result}

@app.post('/api/case-center/cases/{case_id}/actions/{action}')
async def case_center_action(case_id: str, action: str, body: dict, user=Depends(current_user)):
    try:
        result = store.transition_case(case_id, action, user, str(body.get('note') or ''), str(body.get('assignee_id') or ''))
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, f'case.{action}', 'case', case_id, {'note': str(body.get('note') or '')[:300]})
    return result

@app.post('/api/workbench/tasks/{task_id}/complete')
async def workbench_task_complete(task_id: str, body: dict, user=Depends(current_user)):
    try:
        result = store.complete_task(task_id, user, str(body.get('note') or ''))
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'task.complete', 'task', task_id)
    return result

def _safe_result(report: dict) -> dict:
    copy=dict(report); copy.pop('_mask_mapping',None); return copy

def _assert_case_access(job_id: str, user: dict):
    """Business users may only access cases they created, even when they know a job id."""
    case = store.get_case(job_id)
    if not case:
        raise HTTPException(404, '案件不存在')
    if user.get('role') == 'business' and case.get('created_by') != user.get('id'):
        raise HTTPException(404, '案件不存在')
    return case

def _run(path: str, job_id: str, created_at: float):
    job=JOBS[job_id]
    try:
        _publish_review_step(job_id, '任务已启动：正在读取合同文件与已绑定信用审核条件')
        from .graph.review_graph import run_review
        report=run_review(
            path, on_step=lambda step: _publish_review_step(job_id, step),
            on_event=lambda event: _publish_review_event(job_id, event),
            business_type_hint=job.get('business_type',''), rule_snapshot=job.get('rule_snapshot'),
            parent_report=job.get('parent_report'),
        )
        credit_case = job['credit_case']
        exposure = store.latest_credit_exposure_snapshot(credit_case['case_id'])
        credit_risks = [
            *assess_customer_binding(report.get('contract_fields', {}), credit_case['customer_name']),
            *assess_credit_compliance(report.get('clauses', []), credit_case['conditions'], (exposure or {}).get('payload')),
        ]
        report['credit_decision'] = {
            'case_id': credit_case['case_id'], 'customer_name': credit_case['customer_name'],
            'version': credit_case['version'], 'conditions': credit_case['conditions'],
            'business_type': credit_case.get('business_type', '一般'),
            'exposure_snapshot_at_review': (exposure or {}).get('payload'),
        }
        if credit_risks:
            report['risks'] = [*report.get('risks', []), *credit_risks]
            summary = report.setdefault('summary', {})
            summary['n_risks'] = len(report['risks'])
            summary['high'] = sum(1 for item in report['risks'] if item.get('severity') == 'high')
            summary['mid'] = sum(1 for item in report['risks'] if item.get('severity') == 'mid')
            summary['low'] = sum(1 for item in report['risks'] if item.get('severity') == 'low')
            summary['overall_level'] = '信用审核条件不符·须先更新条件'
            step = f'信用审核前置检查：绑定 {credit_case["customer_name"]} / V{credit_case["version"]}，发现 {len(credit_risks)} 项不符合条件的问题'
            report['steps'].append(step); _publish_review_step(job_id, step)
        else:
            step = f'信用审核前置检查：绑定 {credit_case["customer_name"]} / V{credit_case["version"]}，合同未超出已生效条件'
            report['steps'].append(step); _publish_review_step(job_id, step)
        report['_created_at']=created_at; report['_path']=path; report['filename']=job.get('filename') or report.get('filename','')
        mapping=report.pop('_mask_mapping',{})
        store.save_review(job_id,report,status='done',actor=job['actor'],mapping=mapping,rule_version=job['rule_version'],rules_by_id=job['rules_by_id'])
        with REVIEW_JOB_LOCK:
            job['result']=_safe_result(report); job['status']='done'
        _publish_review_event(job_id, {'type': 'completed', 'message': '合同审查已完成，正在保存风险与放行条件检查结果'})
        store.audit(job['actor'],'review.complete','review',job_id,{'risks':report.get('summary',{}).get('n_risks',0)})
    except Exception as e:
        with REVIEW_JOB_LOCK:
            job['status']='error'; job['error']=str(e)
        _publish_review_event(job_id, {'type': 'error', 'message': str(e)[:500]})
        try: store.save_review(job_id,{'filename':job.get('filename',''),'summary':{}},status='error',error=str(e),actor=job['actor'])
        except Exception: pass
        store.audit(job['actor'],'review.error','review',job_id,{'error':str(e)[:300]})

def _start_review(file: UploadFile, actor: dict):
    ext=os.path.splitext(file.filename or '')[1].lower()
    if ext not in ALLOWED_CONTRACT: raise HTTPException(400,'仅支持 DOCX/PDF/XLSX/TXT/PNG/JPG；图片需本机 OCR（pytesseract）')
    job_id=uuid.uuid4().hex[:12]; path=os.path.join(UPLOAD_DIR,f'{job_id}{ext}')
    return job_id,path

async def _write_upload(file: UploadFile,path: str):
    with open(path,'wb') as f:
        while chunk:=await file.read(1<<20): f.write(chunk)

def _review_metadata(assignee_id: str, priority: str, due_at: str, request_note: str):
    try: due = float(due_at) if due_at else None
    except ValueError: raise HTTPException(400, '截止时间格式无效')
    if priority not in store.CASE_PRIORITIES: raise HTTPException(400, '优先级无效')
    return {'assignee_id': assignee_id, 'priority': priority, 'due_at': due, 'request_note': request_note}

@app.post('/api/case-center/cases/{case_id}/documents')
async def case_document_review(case_id: str, file: UploadFile=File(...), business_type: str=Form(''), credit_case_id: str=Form(''), parent_job_id: str=Form(''), assignee_id: str=Form(''), priority: str=Form('normal'), due_at: str=Form(''), request_note: str=Form(''), document_role: str=Form('main'), user=Depends(require('review:create'))):
    if not secure_runtime_ready(): raise HTTPException(503,'安全运行环境未就绪：请配置 AUTH_SECRET 与 DATA_ENCRYPTION_KEY')
    existing = store.get_case_center(case_id, user)
    if not existing:
        raise HTTPException(404, '合同案件不存在或无权访问')
    requested_credit_id = str(credit_case_id or '').strip()
    bound_credit_id = str(existing.get('credit_case_id') or '').strip()
    try:
        if bound_credit_id:
            if requested_credit_id and requested_credit_id != bound_credit_id:
                raise ValueError('上传请求的信用审核版本与合同案件已绑定版本不一致')
            credit_case = store.require_active_credit_case(bound_credit_id)
        else:
            # This also safely repairs a case created before the browser had
            # finished preserving a multi-step form field.
            credit_case = store.bind_case_center_credit(case_id, requested_credit_id, user)
    except ValueError as e: raise HTTPException(409, str(e))
    metadata=_review_metadata(assignee_id,priority,due_at,request_note); job_id,path=_start_review(file,user); await _write_upload(file,path); created=time.time(); catalog=store.get_rule_version(); parent_report={}
    if parent_job_id:
        _assert_case_access(parent_job_id, user); parent = store.get_review(parent_job_id)
        if not parent or parent.get('status') != 'done': raise HTTPException(400, '上一版本尚未完成，不能增量复审')
        parent_report = parent.get('report') or {}
    resolved_case_id=store.create_pending(job_id,file.filename,path,user,business_type,parent_job_id=parent_job_id,rule_version=catalog['version'],credit_case=credit_case,case_id=case_id,document_role=document_role,**metadata)
    with REVIEW_JOB_LOCK:
        JOBS[job_id]={'status':'running','steps':[],'events':[],'live_evidence':[],
                      'active':{'type':'starting','message':'正在准备合同审查'},'event_seq':0,
                      'result':None,'path':path,'filename':file.filename,'actor':user,'case_id':resolved_case_id,
                      'business_type':business_type,'rule_version':catalog['version'],'rule_snapshot':catalog['rules'],
                      'rules_by_id':{rule['id']:rule for rule in catalog['rules']},'parent_report':parent_report,'credit_case':credit_case}
    threading.Thread(target=_run,args=(path,job_id,created),daemon=True).start()
    store.audit(user,'review.create','case',resolved_case_id,{'job_id':job_id,'filename':file.filename})
    return {'job_id':job_id,'case_id':resolved_case_id}

@app.get('/api/reviews/{job_id}/status')
async def job_status(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    with REVIEW_JOB_LOCK:
        j=JOBS.get(job_id)
        if j:
            return {k:v for k,v in j.items() if k not in {'actor','path','rule_snapshot','rules_by_id','parent_report','credit_case'}}
    rec=store.get_review(job_id)
    if not rec: raise HTTPException(404,'任务不存在')
    report = rec.get('report') or {}
    sources = []
    for item in (report.get('risks') or []) + (report.get('review_hints') or []):
        sources.append({'clause_id': item.get('clause_id'), 'source_ref': item.get('source_ref', ''),
                        'page': item.get('page'), 'evidence_quote': item.get('evidence', ''), 'rule_id': item.get('rule_id', '')})
    return {
        'status':rec['status'], 'steps':report.get('steps') or [],
        'events':[{'type':'agent_update','message':step,'step_index':index + 1} for index, step in enumerate(report.get('steps') or [])],
        'live_evidence':sources, 'active':{'type':rec['status'],'message':'已载入最近一次合同审查结果'},
        'result':report, 'case_id':rec.get('case_id'), 'error':rec.get('error',''),
    }


@app.get('/api/reviews/{job_id}/preview')
async def review_preview(job_id: str, user=Depends(require('review:read'))):
    """Return source records for the contract evidence comparison pane."""
    _assert_case_access(job_id, user)
    rec = store.get_review(job_id)
    if not rec:
        raise HTTPException(404, '任务不存在')
    path = rec.get('file_path') or (JOBS.get(job_id) or {}).get('path') or ''
    records = []
    error = ''
    if path and os.path.isfile(path):
        try:
            records = await asyncio.to_thread(read_paragraphs, path)
        except Exception as exc:
            error = str(exc)[:500]
    if not records:
        # A completed report remains previewable even when the original file
        # has been moved out of the upload directory by an external archive.
        for clause in (rec.get('report') or {}).get('clauses') or []:
            records.append({
                'text': clause.get('text', ''), 'source_ref': clause.get('source_ref', ''),
                'source_kind': 'clause', 'start_page': clause.get('start_page') or clause.get('page') or 1,
                'end_page': clause.get('end_page') or clause.get('page') or 1,
            })
    store.audit(user, 'review.document_preview', 'review', job_id, {'record_count': len(records)})
    return {'job_id': job_id, 'filename': rec.get('filename') or '', 'status': rec.get('status'),
            'records': records, 'total': len(records), 'error': error}

@app.get('/api/reviews/{job_id}/stream')
async def stream(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    with REVIEW_JOB_LOCK:
        j=JOBS.get(job_id)
    if not j:
        rec=store.get_review(job_id)
        if not rec: raise HTTPException(404,'任务不存在')
        if rec.get('status') == 'running':
            raise HTTPException(409,'任务正在执行，但当前进程未保留实时事件')
        report=rec.get('report') or {}
        j={
            'steps':report.get('steps') or [],
            'events':[{'type':'agent_update','message':step,'step_index':index + 1} for index, step in enumerate(report.get('steps') or [])],
            'status':rec.get('status'), 'result':report, 'error':rec.get('error',''),
        }
    async def gen():
        last=0
        last_event=0
        while True:
            for step in j['steps'][last:]: yield f'event: step\ndata: {json.dumps(step,ensure_ascii=False)}\n\n'
            last=len(j['steps'])
            for event in j.get('events', [])[last_event:]:
                yield f'event: progress\ndata: {json.dumps(event,ensure_ascii=False)}\n\n'
            last_event=len(j.get('events', []))
            if j['status'] in ('done','error'):
                event='done' if j['status']=='done' else 'error'; payload=j['result'] if event=='done' else j['error']
                yield f'event: {event}\ndata: {json.dumps(payload,ensure_ascii=False)}\n\n'; break
            await asyncio.sleep(1)
    return StreamingResponse(gen(),media_type='text/event-stream')

@app.get('/api/reviewers')
async def reviewers(user=Depends(require('review:read'))): return {'items':store.list_reviewers()}

@app.get('/api/reviews/{job_id}/signability')
async def review_signability(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    rec = store.get_review(job_id)
    if not rec:
        raise HTTPException(404, 'not found')
    result = calculate_signability(rec.get('report') or {}, store.list_findings(job_id), job_id)
    store.audit(user, 'review.signability', 'review', job_id, {'status': result.get('status'), 'blocked': result.get('counts', {}).get('blocked', 0)})
    return result

@app.get('/api/reviews/{job_id}')
async def review_detail(job_id: str,user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    rec=store.get_review(job_id)
    if not rec: raise HTTPException(404,'not found')
    rec['findings']=store.list_findings(job_id)
    rec['approvals']=store.list_approvals(job_id, user)
    rec['material_requests']=store.list_material_requests(job_id)
    store.audit(user,'review.view','review',job_id)
    return rec

@app.get('/api/stats')
async def dashboard_stats(user=Depends(current_user)): return store.stats(user)

@app.get('/api/reviews/{job_id}/findings')
async def findings(job_id: str,user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    return {'items':store.list_findings(job_id),'rule_version':'contract-v1'}

@app.get('/api/reviews/{job_id}/approvals')
async def approvals(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    return {'items': store.list_approvals(job_id, user)}

@app.post('/api/reviews/{job_id}/approvals/{approval_id}')
async def approval_decision(job_id: str, approval_id: str, body: dict, user=Depends(require('review:action'))):
    _assert_case_access(job_id, user)
    try:
        result = store.decide_approval(job_id, approval_id, body.get('decision', ''), body.get('note', ''), user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'review.approval_decision', 'approval', approval_id, {'job_id': job_id, 'decision': body.get('decision')})
    return result

@app.get('/api/reviews/{job_id}/materials')
async def material_requests(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    return {'items': store.list_material_requests(job_id)}

@app.post('/api/reviews/{job_id}/materials/{request_id}/resolve')
async def material_resolve(job_id: str, request_id: str, body: dict, user=Depends(require('review:action'))):
    _assert_case_access(job_id, user)
    try:
        result = store.resolve_material_request(job_id, request_id, body.get('note', ''), user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'review.material_resolve', 'material', request_id, {'job_id': job_id})
    return result

@app.post('/api/reviews/{job_id}/materials/{request_id}/files')
async def material_upload(job_id: str, request_id: str, file: UploadFile=File(...), user=Depends(require('review:action'))):
    _assert_case_access(job_id, user)
    safe_name = os.path.basename(file.filename or 'attachment.bin')
    if not safe_name or len(safe_name) > 255:
        raise HTTPException(400, '附件文件名无效')
    material_dir = os.path.join(UPLOAD_DIR, 'materials', job_id, request_id)
    os.makedirs(material_dir, exist_ok=True)
    stored_path = os.path.join(material_dir, f'{uuid.uuid4().hex}_{safe_name}')
    await _write_upload(file, stored_path)
    try:
        result = store.add_material_file(job_id, request_id, safe_name, stored_path, user)
    except ValueError as e:
        if os.path.exists(stored_path): os.remove(stored_path)
        raise HTTPException(404, str(e))
    store.audit(user, 'review.material_upload', 'material', request_id, {'job_id': job_id, 'file_id': result['file_id']})
    return result

@app.get('/api/reviews/{job_id}/materials/{request_id}/files/{file_id}')
async def material_download(job_id: str, request_id: str, file_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    item = store.get_material_file(job_id, request_id, file_id)
    if not item or not os.path.isfile(item['stored_path']):
        raise HTTPException(404, '附件不存在')
    return FileResponse(item['stored_path'], filename=item['original_name'])

@app.get('/api/contracts/knowledge')
async def clause_knowledge(rule_id: str='', limit: int=3, user=Depends(require('review:read'))):
    return {'items': store.list_knowledge(rule_id, min(max(limit, 1), 10))}

@app.get('/api/reviews/{job_id}/findings/{finding_id}/knowledge')
async def finding_knowledge(job_id: str, finding_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    try:
        return {'items': store.similar_knowledge(job_id, finding_id, 3)}
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.get('/api/reviews/{job_id}/compare/{baseline_job_id}')
async def compare_contract_versions(job_id: str, baseline_job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    _assert_case_access(baseline_job_id, user)
    try:
        return store.compare_reviews(job_id, baseline_job_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.get('/api/contracts/batch-matrix')
async def review_batch_matrix(user=Depends(require('review:read'))):
    return {'items': store.batch_matrix(user)}

@app.post('/api/reviews/{job_id}/findings/{finding_id}/actions')
async def finding_action(job_id: str,finding_id: str,body: dict,user=Depends(require('review:action'))):
    try: result=store.record_finding_action(job_id,finding_id,body.get('action',''),body.get('reason',''),user,body.get('edited_suggestion',''))
    except ValueError as e: raise HTTPException(400,str(e))
    store.audit(user,'review.finding_action','finding',finding_id,{'job_id':job_id,'action':body.get('action')})
    return result

@app.get('/api/reviews/{job_id}/export')
async def export_docx_route(job_id: str, mode: str='revised', lang: str='', user=Depends(require('export'))):
    _assert_case_access(job_id, user)
    rec=store.get_review(job_id)
    if not rec: raise HTTPException(404,'not found')
    if mode not in EXPORT_MODES: raise HTTPException(400,'mode 仅支持 revised/plain/bilingual')
    translation = None
    if mode == 'bilingual':
        target_lang = lang or 'en'
        if target_lang not in ('en','vi','ja','es'):
            raise HTTPException(400,'双语导出仅支持 en/vi/ja/es')
        saved = store.get_translation(job_id, target_lang)
        if not saved or saved.get('status') != 'done' or not saved.get('result'):
            raise HTTPException(409, f'尚未完成 {target_lang} 翻译，请先在报告页执行翻译后再导出双语稿')
        translation = saved['result']
    if mode in ('revised', 'bilingual'):
        try:
            store.contract_credit_binding(job_id, require_current=True)
        except ValueError as e:
            raise HTTPException(409, str(e))
        credit_blockers = [x for x in store.list_findings(job_id) if str(x.get('rule_id') or '').startswith('CREDIT_')]
        if credit_blockers:
            raise HTTPException(409, '合同存在不符合信用审核条件的问题，必须先更新信用审核并基于新版本重新复审，不能直接放行')
        pending = [x for x in store.list_approvals(job_id) if x['status'] != 'approved']
        if pending:
            raise HTTPException(409, '存在未完成或未通过的主管/集团财务总监审批，不能导出可签约修订稿')
    report=rec.get('report') or {}; approved=store.list_findings(job_id)
    # Export only findings that a human has explicitly accepted or approved.
    accepted={'adopted','edited','approved'}; report={**report,'risks':[{'finding_id':x['finding_id'],'clause_id':x['clause_id'],'page':x['page'],'rule_id':x['rule_id'],'rule_baseline':x['baseline'],'severity':x['severity'],'level':x['level'],'evidence':x['evidence'],'numeric_note':x['numeric_note'],'suggestion':x['suggestion']} for x in approved if x['action_status'] in accepted]}
    out_dir=os.path.join(UPLOAD_DIR,'exports'); os.makedirs(out_dir,exist_ok=True); out_path=os.path.join(out_dir,f'{job_id}_{mode}{("_"+lang) if mode=="bilingual" and lang else ""}.docx')
    export_revised_docx(report,out_path,mode=mode,source_path=rec.get('file_path',''),translation=translation)
    snapshot = store.record_export_snapshot(job_id, mode, out_path, user, store.list_approvals(job_id), approved)
    store.audit(user,'review.export','review',job_id,{'mode':mode,'lang':lang,'findings':len(report['risks']),'export_id':snapshot['export_id']})
    labels={'revised':'建议稿','plain':'原文版','bilingual':'双语对照'}
    return FileResponse(out_path,filename=f"{(report.get('filename') or 'report').replace('.','_')}_{labels.get(mode,'export')}.docx",media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

def _run_translate(report,mapping,tfid,target_lang,job_id,actor):
    try:
        result=run_translate(report,target_lang,mapping=mapping,on_step=lambda s:TJOBS[tfid]['steps'].append(s))
        store.save_translation(job_id, target_lang, result, 'done', actor=actor)
        TJOBS[tfid].update(result=result,status='done')
    except Exception as e:
        store.save_translation(job_id, target_lang, None, 'error', actor=actor, error=str(e))
        TJOBS[tfid].update(error=str(e),status='error')

@app.post('/api/reviews/{job_id}/translations')
async def translate_route(job_id: str,body: dict,user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    rec=store.get_review(job_id)
    if not rec: raise HTTPException(404,'合同审查记录不存在')
    target_lang=body.get('target_lang','en')
    if target_lang not in ('en','vi','ja','es'):
        raise HTTPException(400,'不支持的目标语言')
    mapping=store.get_mask_mapping(job_id)
    if not mapping:
        raise HTTPException(409,'该合同的脱敏映射不存在或已过期，已拒绝将原文发送至翻译模型')
    # Reuse cached translation unless caller forces refresh.
    if not body.get('force'):
        cached = store.get_translation(job_id, target_lang)
        if cached and cached.get('status') == 'done' and cached.get('result'):
            tfid=uuid.uuid4().hex[:12]
            TJOBS[tfid]={'status':'done','steps':['翻译任务：已使用已保存结果'],'result':cached['result']}
            store.audit(user,'review.translate_cache','review',job_id,{'target_lang':target_lang})
            return {'tfid':tfid,'cached':True}
    tfid=uuid.uuid4().hex[:12]
    TJOBS[tfid]={'status':'running','steps':[],'result':None}
    store.save_translation(job_id, target_lang, None, 'running', actor=user)
    threading.Thread(target=_run_translate,args=(rec['report'],mapping,tfid,target_lang,job_id,user),daemon=True).start()
    store.audit(user,'review.translate','review',job_id,{'target_lang':target_lang}); return {'tfid':tfid,'cached':False}

@app.get('/api/reviews/{job_id}/translations')
async def translate_get(job_id: str, lang: str='en', user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    if lang not in ('en','vi','ja','es'):
        raise HTTPException(400,'不支持的目标语言')
    saved = store.get_translation(job_id, lang)
    if not saved:
        raise HTTPException(404,'尚无该语言的翻译结果')
    return saved

@app.get('/api/reviews/{job_id}/translations/list')
async def translate_list(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    return {'items': store.list_translations(job_id)}

@app.get('/api/reviews/translations/stream/{tfid}')
async def translate_stream(tfid: str,user=Depends(require('review:read'))):
    j=TJOBS.get(tfid)
    if not j: raise HTTPException(404,'not found')
    async def gen():
        last=0
        while True:
            for step in j['steps'][last:]: yield f'event: step\ndata: {json.dumps(step,ensure_ascii=False)}\n\n'
            last=len(j['steps'])
            if j['status'] in ('done','error'):
                event='done' if j['status']=='done' else 'error'; yield f'event: {event}\ndata: {json.dumps(j["result"] if event=="done" else j["error"],ensure_ascii=False)}\n\n'; break
            await asyncio.sleep(1)
    return StreamingResponse(gen(),media_type='text/event-stream')

@app.post('/api/reviews/{job_id}/attachments')
async def case_attachment_upload(job_id: str, file: UploadFile=File(...), role: str=Form('annex'), user=Depends(require('review:action'))):
    _assert_case_access(job_id, user)
    ext=os.path.splitext(file.filename or '')[1].lower()
    if ext not in ALLOWED_ATTACHMENT:
        raise HTTPException(400,'附件仅支持 DOCX/PDF/XLSX/TXT/PNG/JPG')
    file_id=uuid.uuid4().hex[:12]
    path=os.path.join(UPLOAD_DIR, f'{job_id}_att_{file_id}{ext}')
    await _write_upload(file, path)
    preview=[]
    try:
        parsed=parse_contract(path)
        preview=[{'id':c.get('id'),'text':(c.get('text') or '')[:240],'source_ref':c.get('source_ref','')} for c in (parsed.get('clauses') or [])[:40]]
    except Exception as e:
        preview=[{'id':'ERR','text':f'预览解析失败：{e}','source_ref':''}]
    item=store.add_case_attachment(job_id, file.filename or f'attachment{ext}', path, user, role=role or 'annex', preview=preview)
    store.audit(user,'case.attachment_upload','review',job_id,{'file_id':item['file_id'],'filename':file.filename})
    return item

@app.get('/api/reviews/{job_id}/attachments')
async def case_attachment_list(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    return {'items': store.list_case_attachments(job_id)}

@app.get('/api/reviews/{job_id}/attachments/{file_id}')
async def case_attachment_get(job_id: str, file_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    item=store.get_case_attachment(job_id, file_id)
    if not item: raise HTTPException(404,'附件不存在')
    # Do not expose absolute stored_path to non-admin clients.
    safe={k:v for k,v in item.items() if k != 'stored_path'}
    return safe

@app.get('/api/reviews/{job_id}/attachments/{file_id}/download')
async def case_attachment_download(job_id: str, file_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    item=store.get_case_attachment(job_id, file_id)
    if not item or not os.path.exists(item.get('stored_path') or ''):
        raise HTTPException(404,'附件不存在')
    return FileResponse(item['stored_path'], filename=item.get('original_name') or 'attachment')

@app.get('/api/integrations/roles')
async def roles_route(user=Depends(current_user)): return {'roles':APPROVAL_ROLES,'mode':'mock'}

@app.post('/api/integrations/oa/flow')
async def oa_flow_route(body: dict,user=Depends(require('review:action'))):
    job_id = str(body.get('job_id') or '')
    if job_id:
        _assert_case_access(job_id, user)
    findings = store.list_findings(job_id) if job_id else (body.get('findings') or [])
    rec = store.get_review(job_id) if job_id else None
    report = (rec or {}).get('report') or {}
    contract_meta = body.get('contract') or {
        'filename': report.get('filename') or (rec or {}).get('filename'),
        'job_id': job_id,
        'business_type': (report.get('contract_fields') or {}).get('business_type'),
    }
    summary = body.get('summary') or report.get('summary') or {}
    result=oa.create_review_flow(contract_meta, summary, job_id=job_id, findings=findings)
    store.audit(user,'oa.flow_create','oa',result['flow_id'],{'job_id':job_id})
    return result

@app.get('/api/integrations/oa/flow/{flow_id}')
async def oa_flow_get(flow_id: str,user=Depends(require('review:read'))):
    flow = oa.get_flow(flow_id)
    if not flow:
        raise HTTPException(404, 'OA 流程不存在')
    return flow

@app.post('/api/integrations/oa/flow/{flow_id}/decision')
async def oa_flow_decision(flow_id: str, body: dict, user=Depends(require('review:action'))):
    role = str(body.get('role') or user.get('role') or '信用审核专员')
    decision = str(body.get('decision') or '').strip()
    if not decision:
        raise HTTPException(400, '请填写决策（采纳/驳回/修改）')
    result = oa.submit_role_decision(flow_id, role, decision, body.get('note', ''))
    if not result.get('ok'):
        raise HTTPException(404, result.get('msg') or 'flow not found')
    store.audit(user,'oa.flow_decision','oa',flow_id,{'role':role,'decision':decision})
    return result

@app.post('/api/integrations/oa/flow/{flow_id}/batch-update')
async def oa_flow_batch_update(flow_id: str, body: dict, user=Depends(require('review:action'))):
    accepted = body.get('accepted_suggestions') or body.get('accepted') or []
    if not isinstance(accepted, list):
        raise HTTPException(400, 'accepted_suggestions 必须为数组')
    result = oa.batch_update(flow_id, accepted)
    if not result.get('ok'):
        raise HTTPException(404, result.get('msg') or 'flow not found')
    store.audit(user,'oa.flow_batch_update','oa',flow_id,{'count':len(accepted)})
    return result

@app.post('/api/integrations/crm/credit-hooks')
async def crm_credit_hook_create(body: dict, user=Depends(require('credit:create'))):
    """CRM 接入端口：接收客户主数据并可选创建信用审核草稿（不执行授信测算）。"""
    customer_name = str(body.get('customer_name') or '').strip()
    if not customer_name:
        raise HTTPException(400, 'customer_name 必填')
    hook = crm.create_credit_hook(body)
    credit_case = None
    if body.get('create_draft', True):
        conditions = body.get('conditions') or {
            'max_credit_amount': 0, 'currency': 'CNY', 'max_payment_days': 0,
            'min_prepayment_ratio': 0, 'allowed_payment_methods': ['bank_transfer'],
            'allow_vmi_jit': False,
        }
        try:
            credit_case = store.create_credit_case(customer_name, conditions, hook.get('request_note',''), user)
            crm.attach_credit_case(hook['hook_id'], credit_case['case_id'])
            hook = crm.get_hook(hook['hook_id']) or hook
        except ValueError as e:
            raise HTTPException(400, str(e))
    store.audit(user,'crm.credit_hook','crm',hook['hook_id'],{'customer':customer_name,'credit_case_id':(credit_case or {}).get('case_id')})
    return {'hook': hook, 'credit_case': credit_case, 'mock': True,
            'integration_note': '此端口供 CRM 推送信用申请；额度和账期由后续 Agent 评估生成，再进入审批流程。'}

@app.get('/api/integrations/crm/credit-hooks')
async def crm_credit_hook_list(limit: int=50, user=Depends(require('credit:read'))):
    return {'items': crm.list_hooks(limit), 'mock': True}

@app.get('/api/integrations/crm/credit-hooks/{hook_id}')
async def crm_credit_hook_get(hook_id: str, user=Depends(require('credit:read'))):
    hook = crm.get_hook(hook_id)
    if not hook:
        raise HTTPException(404, 'CRM hook 不存在')
    return hook

_FRONT_DIST=os.path.normpath(os.path.join(os.path.dirname(__file__),'..','..','frontend','dist'))
if os.path.isdir(_FRONT_DIST):
    assets=os.path.join(_FRONT_DIST,'assets')
    if os.path.isdir(assets): app.mount('/assets',StaticFiles(directory=assets),name='assets')
    @app.api_route('/api/{path:path}', methods=['GET','POST','PUT','PATCH','DELETE'])
    async def _unknown_api(path: str):
        """Never let retired API paths fall through to the SPA index page."""
        raise HTTPException(404, f'未定义的 API 接口：/api/{path}')
    @app.get('/{full_path:path}')
    async def _spa(full_path: str): return FileResponse(os.path.join(_FRONT_DIST,'index.html'))
