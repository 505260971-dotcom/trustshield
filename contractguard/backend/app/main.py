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
from .config import CORS_ORIGINS, LLM_API_BASE, LLM_API_KEY, LLM_MODEL, UPLOAD_DIR, configured_llm, secure_runtime_ready
from .services.export_docx import export_revised_docx
from .services.integrations import APPROVAL_ROLES, crm, oa
from .services.translate import run_translate
from .services.credit import assess_credit_compliance, assess_customer_binding
from .services.parse import parse_contract

app = FastAPI(title='ContractGuard 合同评审协作中心', version='3.0')
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=['GET','POST','PATCH','DELETE'], allow_headers=['Authorization','Content-Type'])
app.include_router(auth_router)

# Short-lived runtime state only; sensitive report and mapping are persisted encrypted.
JOBS: dict[str, dict] = {}
TJOBS: dict[str, dict] = {}
ALLOWED_CONTRACT = {'.docx','.pdf','.txt','.xlsx','.xls','.png','.jpg','.jpeg','.webp','.bmp'}
ALLOWED_ATTACHMENT = ALLOWED_CONTRACT
EXPORT_MODES = {'revised', 'plain', 'bilingual'}

@app.on_event('startup')
def _startup():
    store.init_db()

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

# Credit review is deliberately separate from contract review.  A contract can
# read a published decision but cannot create, alter, or approve one.
@app.get('/api/credit/decisions')
async def credit_decisions(active_only: bool=True, user=Depends(require('credit:read'))):
    return {'items': store.list_credit_cases(active_only=active_only)}

@app.get('/api/credit/cases')
async def credit_cases(customer: str='', user=Depends(require('credit:read'))):
    if user.get('role') == 'business':
        return {'items': store.list_credit_cases(customer, active_only=True)}
    return {'items': store.list_credit_cases(customer)}

@app.post('/api/credit/cases')
async def credit_case_create(body: dict, user=Depends(require('credit:create'))):
    try:
        result = store.create_credit_case(body.get('customer_name', ''), body.get('conditions') or {}, body.get('request_note', ''), user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'credit.create', 'credit_case', result['case_id'], {'customer': result['customer_name'], 'version': result['version']})
    return result

@app.patch('/api/credit/cases/{case_id}')
async def credit_case_update(case_id: str, body: dict, user=Depends(require('credit:manage'))):
    try:
        result = store.update_credit_case(case_id, body.get('conditions') or {}, body.get('request_note', ''), user)
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
async def credit_case_decision(case_id: str, body: dict, user=Depends(require('credit:manage'))):
    try: result = store.decide_credit_case(case_id, body.get('decision', ''), body.get('note', ''), user)
    except ValueError as e: raise HTTPException(400, str(e))
    store.audit(user, 'credit.decision', 'credit_case', case_id, {'decision': body.get('decision')})
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
        from .graph.review_graph import run_review
        report=run_review(path,on_step=lambda s:JOBS[job_id]['steps'].append(s),business_type_hint=job.get('business_type',''),rule_snapshot=job.get('rule_snapshot'),parent_report=job.get('parent_report'))
        credit_case = job['credit_case']
        credit_risks = [
            *assess_customer_binding(report.get('contract_fields', {}), credit_case['customer_name']),
            *assess_credit_compliance(report.get('clauses', []), credit_case['conditions']),
        ]
        report['credit_decision'] = {
            'case_id': credit_case['case_id'], 'customer_name': credit_case['customer_name'],
            'version': credit_case['version'], 'conditions': credit_case['conditions'],
        }
        if credit_risks:
            report['risks'] = [*report.get('risks', []), *credit_risks]
            summary = report.setdefault('summary', {})
            summary['n_risks'] = len(report['risks'])
            summary['high'] = sum(1 for item in report['risks'] if item.get('severity') == 'high')
            summary['mid'] = sum(1 for item in report['risks'] if item.get('severity') == 'mid')
            summary['low'] = sum(1 for item in report['risks'] if item.get('severity') == 'low')
            summary['overall_level'] = '信审阻断·须先更新信审条件'
            report['steps'].append(f'信审前置校验: 绑定 {credit_case["customer_name"]} / V{credit_case["version"]}，发现 {len(credit_risks)} 项越界')
        else:
            report['steps'].append(f'信审前置校验: 绑定 {credit_case["customer_name"]} / V{credit_case["version"]}，合同未突破已生效条件')
        report['_created_at']=created_at; report['_path']=path; report['filename']=job.get('filename') or report.get('filename','')
        mapping=report.pop('_mask_mapping',{})
        store.save_review(job_id,report,status='done',actor=job['actor'],mapping=mapping,rule_version=job['rule_version'],rules_by_id=job['rules_by_id'])
        job['result']=_safe_result(report); job['status']='done'
        store.audit(job['actor'],'review.complete','review',job_id,{'risks':report.get('summary',{}).get('n_risks',0)})
    except Exception as e:
        job['status']='error'; job['error']=str(e)
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

@app.post('/api/review')
async def review(file: UploadFile=File(...), business_type: str=Form(''), credit_case_id: str=Form(''), parent_job_id: str=Form(''), assignee_id: str=Form(''), priority: str=Form('normal'), due_at: str=Form(''), request_note: str=Form(''), user=Depends(require('review:create'))):
    if not secure_runtime_ready(): raise HTTPException(503,'安全运行环境未就绪：请配置 AUTH_SECRET 与 DATA_ENCRYPTION_KEY')
    try: credit_case = store.require_active_credit_case(credit_case_id)
    except ValueError as e: raise HTTPException(409, str(e))
    metadata=_review_metadata(assignee_id,priority,due_at,request_note); job_id,path=_start_review(file,user); await _write_upload(file,path); created=time.time(); catalog=store.get_rule_version(); parent_report={}
    if parent_job_id:
        _assert_case_access(parent_job_id, user); parent = store.get_review(parent_job_id)
        if not parent or parent.get('status') != 'done': raise HTTPException(400, '上一版本尚未完成，不能增量复审')
        parent_report = parent.get('report') or {}
    case_id=store.create_pending(job_id,file.filename,path,user,business_type,parent_job_id=parent_job_id,rule_version=catalog['version'],credit_case=credit_case,**metadata)
    JOBS[job_id]={'status':'running','steps':[],'result':None,'path':path,'filename':file.filename,'actor':user,'case_id':case_id,'business_type':business_type,'rule_version':catalog['version'],'rule_snapshot':catalog['rules'],'rules_by_id':{rule['id']:rule for rule in catalog['rules']},'parent_report':parent_report,'credit_case':credit_case}
    threading.Thread(target=_run,args=(path,job_id,created),daemon=True).start()
    store.audit(user,'review.create','case',case_id,{'job_id':job_id,'filename':file.filename})
    return {'job_id':job_id,'case_id':case_id}

@app.post('/api/review/batch')
async def review_batch(files: list[UploadFile]=File(...), business_type: str=Form('一般'), credit_case_id: str=Form(''), assignee_id: str=Form(''), priority: str=Form('normal'), due_at: str=Form(''), request_note: str=Form(''), user=Depends(require('review:create'))):
    if not secure_runtime_ready(): raise HTTPException(503,'安全运行环境未就绪：请配置 AUTH_SECRET 与 DATA_ENCRYPTION_KEY')
    try: credit_case = store.require_active_credit_case(credit_case_id)
    except ValueError as e: raise HTTPException(409, str(e))
    jobs=[]; metadata=_review_metadata(assignee_id,priority,due_at,request_note)
    for file in files:
        try:
            job_id,path=_start_review(file,user); await _write_upload(file,path); created=time.time(); catalog=store.get_rule_version(); case_id=store.create_pending(job_id,file.filename,path,user,business_type,rule_version=catalog['version'],credit_case=credit_case,**metadata)
            JOBS[job_id]={'status':'running','steps':[],'result':None,'path':path,'filename':file.filename,'actor':user,'case_id':case_id,'business_type':business_type,'rule_version':catalog['version'],'rule_snapshot':catalog['rules'],'rules_by_id':{rule['id']:rule for rule in catalog['rules']},'credit_case':credit_case}
            threading.Thread(target=_run,args=(path,job_id,created),daemon=True).start(); jobs.append({'job_id':job_id,'case_id':case_id,'filename':file.filename})
        except HTTPException: continue
    store.audit(user,'review.batch_create','review','',{'count':len(jobs)})
    return {'jobs':jobs}

@app.get('/api/jobs/{job_id}')
async def job_status(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    j=JOBS.get(job_id)
    if j:return {k:v for k,v in j.items() if k not in {'actor','path'}}
    rec=store.get_review(job_id)
    if not rec: raise HTTPException(404,'任务不存在')
    return {'status':rec['status'],'steps':[],'result':rec['report'],'case_id':rec.get('case_id')}

@app.get('/api/stream/{job_id}')
async def stream(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    j=JOBS.get(job_id)
    if not j: raise HTTPException(404,'任务不存在')
    async def gen():
        last=0
        while True:
            for step in j['steps'][last:]: yield f'event: step\ndata: {json.dumps(step,ensure_ascii=False)}\n\n'
            last=len(j['steps'])
            if j['status'] in ('done','error'):
                event='done' if j['status']=='done' else 'error'; payload=j['result'] if event=='done' else j['error']
                yield f'event: {event}\ndata: {json.dumps(payload,ensure_ascii=False)}\n\n'; break
            await asyncio.sleep(1)
    return StreamingResponse(gen(),media_type='text/event-stream')

@app.get('/api/history')
async def history(limit: int=50,offset: int=0,user=Depends(require('review:read'))): return {'items':store.list_history(limit,offset)}

@app.get('/api/cases')
async def cases(limit: int=100,user=Depends(require('review:read'))): return {'items':store.list_cases(user,min(max(limit,1),500))}

@app.patch('/api/cases/{job_id}')
async def case_update(job_id: str,body: dict,user=Depends(require('review:manage'))):
    try: result=store.update_case(job_id,body,user)
    except ValueError as e: raise HTTPException(400,str(e))
    store.audit(user,'case.update','case',result['case_id'],{'job_id':job_id,'fields':list(body.keys())})
    return result

@app.get('/api/reviewers')
async def reviewers(user=Depends(require('review:read'))): return {'items':store.list_reviewers()}

@app.get('/api/history/{job_id}')
async def history_detail(job_id: str,user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    rec=store.get_review(job_id)
    if not rec: raise HTTPException(404,'not found')
    rec['findings']=store.list_findings(job_id)
    rec['approvals']=store.list_approvals(job_id, user)
    rec['material_requests']=store.list_material_requests(job_id)
    store.audit(user,'review.view','review',job_id)
    return rec

@app.delete('/api/history/{job_id}')
async def history_delete(job_id: str,user=Depends(require('admin:cases'))):
    store.delete_review(job_id); store.audit(user,'review.delete','review',job_id); return {'ok':True}

@app.get('/api/stats')
async def dashboard_stats(user=Depends(current_user)): return store.stats(user)

@app.get('/api/contracts/cases/{job_id}/findings')
async def findings(job_id: str,user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    return {'items':store.list_findings(job_id),'rule_version':'contract-v1'}

@app.get('/api/contracts/cases/{job_id}/approvals')
async def approvals(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    return {'items': store.list_approvals(job_id, user)}

@app.post('/api/contracts/cases/{job_id}/approvals/{approval_id}')
async def approval_decision(job_id: str, approval_id: str, body: dict, user=Depends(require('review:action'))):
    _assert_case_access(job_id, user)
    try:
        result = store.decide_approval(job_id, approval_id, body.get('decision', ''), body.get('note', ''), user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'review.approval_decision', 'approval', approval_id, {'job_id': job_id, 'decision': body.get('decision')})
    return result

@app.get('/api/contracts/cases/{job_id}/materials')
async def material_requests(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    return {'items': store.list_material_requests(job_id)}

@app.post('/api/contracts/cases/{job_id}/materials/{request_id}/resolve')
async def material_resolve(job_id: str, request_id: str, body: dict, user=Depends(require('review:action'))):
    _assert_case_access(job_id, user)
    try:
        result = store.resolve_material_request(job_id, request_id, body.get('note', ''), user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store.audit(user, 'review.material_resolve', 'material', request_id, {'job_id': job_id})
    return result

@app.post('/api/contracts/cases/{job_id}/materials/{request_id}/files')
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

@app.get('/api/contracts/cases/{job_id}/materials/{request_id}/files/{file_id}')
async def material_download(job_id: str, request_id: str, file_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    item = store.get_material_file(job_id, request_id, file_id)
    if not item or not os.path.isfile(item['stored_path']):
        raise HTTPException(404, '附件不存在')
    return FileResponse(item['stored_path'], filename=item['original_name'])

@app.get('/api/contracts/knowledge')
async def clause_knowledge(rule_id: str='', limit: int=3, user=Depends(require('review:read'))):
    return {'items': store.list_knowledge(rule_id, min(max(limit, 1), 10))}

@app.get('/api/contracts/cases/{job_id}/findings/{finding_id}/knowledge')
async def finding_knowledge(job_id: str, finding_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    try:
        return {'items': store.similar_knowledge(job_id, finding_id, 3)}
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.get('/api/contracts/cases/{job_id}/compare/{baseline_job_id}')
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

@app.post('/api/contracts/cases/{job_id}/findings/{finding_id}/actions')
async def finding_action(job_id: str,finding_id: str,body: dict,user=Depends(require('review:action'))):
    try: result=store.record_finding_action(job_id,finding_id,body.get('action',''),body.get('reason',''),user,body.get('edited_suggestion',''))
    except ValueError as e: raise HTTPException(400,str(e))
    store.audit(user,'review.finding_action','finding',finding_id,{'job_id':job_id,'action':body.get('action')})
    return result

@app.get('/api/export/{job_id}')
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
            raise HTTPException(409, '合同存在信审越界项，必须先更新信审并基于新版本重新复审，不能在合同端放行')
        pending = [x for x in store.list_approvals(job_id) if x['status'] != 'approved']
        if pending:
            raise HTTPException(409, '存在未完成或未通过的 CEO/总监审批，不能导出可签约修订稿')
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

@app.post('/api/translate/{job_id}')
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
            TJOBS[tfid]={'status':'done','steps':['翻译Agent: 命中已持久化结果'],'result':cached['result']}
            store.audit(user,'review.translate_cache','review',job_id,{'target_lang':target_lang})
            return {'tfid':tfid,'cached':True}
    tfid=uuid.uuid4().hex[:12]
    TJOBS[tfid]={'status':'running','steps':[],'result':None}
    store.save_translation(job_id, target_lang, None, 'running', actor=user)
    threading.Thread(target=_run_translate,args=(rec['report'],mapping,tfid,target_lang,job_id,user),daemon=True).start()
    store.audit(user,'review.translate','review',job_id,{'target_lang':target_lang}); return {'tfid':tfid,'cached':False}

@app.get('/api/translate/{job_id}')
async def translate_get(job_id: str, lang: str='en', user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    if lang not in ('en','vi','ja','es'):
        raise HTTPException(400,'不支持的目标语言')
    saved = store.get_translation(job_id, lang)
    if not saved:
        raise HTTPException(404,'尚无该语言的翻译结果')
    return saved

@app.get('/api/translate/{job_id}/list')
async def translate_list(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    return {'items': store.list_translations(job_id)}

@app.get('/api/translate/stream/{tfid}')
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

@app.post('/api/cases/{job_id}/attachments')
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

@app.get('/api/cases/{job_id}/attachments')
async def case_attachment_list(job_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    return {'items': store.list_case_attachments(job_id)}

@app.get('/api/cases/{job_id}/attachments/{file_id}')
async def case_attachment_get(job_id: str, file_id: str, user=Depends(require('review:read'))):
    _assert_case_access(job_id, user)
    item=store.get_case_attachment(job_id, file_id)
    if not item: raise HTTPException(404,'附件不存在')
    # Do not expose absolute stored_path to non-admin clients.
    safe={k:v for k,v in item.items() if k != 'stored_path'}
    return safe

@app.get('/api/cases/{job_id}/attachments/{file_id}/download')
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
    role = str(body.get('role') or user.get('role') or '法务')
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
    """CRM 预留端口：接收客户主数据并可选创建信审草稿（不执行授信测算）。"""
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
            'integration_note': '此端口供 CRM 推送信用申请占位；额度/账期测算由信审 Agent 后续填充并走审批生效'}

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
    @app.get('/{full_path:path}')
    async def _spa(full_path: str): return FileResponse(os.path.join(_FRONT_DIST,'index.html'))
