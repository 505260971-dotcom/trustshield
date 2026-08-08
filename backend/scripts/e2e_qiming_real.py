# -*- coding: utf-8 -*-
"""“启明智造”模拟材料包全流程真实演示（可断点续跑）。

使用 docs/03-演示与交付/模拟测试材料-v2-启明智造场景 的真实 DOCX：
  02-客户财务报告          → 信审财报材料
  04-首版销售合同-风险     → 首版合同（故意越界，预期 5 类 CREDIT_* 阻断）
  06-修订销售合同-复审     → V2 修订（修正条款但额度仍超，预期二次阻断）
  11-最终销售合同-可签约V3 → V3 最终（金额降至 45 万，预期通过信审门禁）

完整闭环：信审生效 → 首版阻断 → V2 二次阻断 → V3 复审通过 →
风险处置 → 分级审批 → 可签约 → 归档。

- 认证 token 由内部签发（不依赖登录密码），其余全部走真实 HTTP API。
- 支持断点续跑：已完成的步骤自动跳过，重复运行同一命令即可续跑。
- 每次运行建议控制在 10 分钟内，未完成时再次运行即可。

运行：python scripts/e2e_qiming_real.py [--reset]
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app import store  # noqa: E402
from app.services.security import issue_token  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
MATERIAL_DIR = os.path.join(ROOT, 'docs', '03-演示与交付', '模拟测试材料-v2-启明智造场景')

CUSTOMER = '启明智造（模拟）有限公司'
BUSINESS_TYPE = 'TKM'
CREDIT_LIMIT = 1800000
CREDIT_DAYS = 60
CREDIT_PREPAY = 40

CREDIT_TIMEOUT = 600   # 信审 Agent 评估最长等待（秒）
REVIEW_TIMEOUT = 540   # 合同 Agent 审查最长等待（秒）


def material(name: str) -> str:
    path = os.path.join(MATERIAL_DIR, name)
    if not os.path.isfile(path):
        raise SystemExit(f'缺少材料文件：{path}')
    return path


def token_for(username: str) -> str:
    user = store.get_user_by_username(username)
    if not user:
        raise SystemExit(f'缺少账号 {username}，请先创建演示账号')
    return issue_token(user)


def call(client, method, path, token, expect=(200,), **kwargs):
    response = getattr(client, method)(path, headers={'Authorization': f'Bearer {token}'}, **kwargs)
    if response.status_code not in expect:
        raise RuntimeError(f'{method.upper()} {path} → {response.status_code}: {response.text[:500]}')
    return response.json() if response.content else None


def find_credit(client, admin_token):
    items = call(client, 'get', '/api/credit/cases', admin_token).get('items', [])
    return next((item for item in items if item['customer_name'] == CUSTOMER), None)


def wait_status(client, token, url, timeout, done_values):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status = call(client, 'get', url, token)
        last = status
        value = status.get('status')
        print(f'  · 状态={value} 步骤={len(status.get("steps") or [])}', flush=True)
        if value in done_values:
            return status
        time.sleep(8)
    raise TimeoutError(f'等待超时（{timeout}s），最后状态：{last.get("status")}')


def upload_case_document(client, token, case_id, file_path, credit_case_id, business_type, document_role, parent_job_id=''):
    filename = os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()
    mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' if ext == '.docx' else 'application/octet-stream'
    with open(file_path, 'rb') as handle:
        call(client, 'post', f'/api/case-center/cases/{case_id}/documents', token,
             files={'file': (filename, handle, mime)},
             data={'credit_case_id': credit_case_id, 'business_type': business_type,
                   'document_role': document_role, 'parent_job_id': parent_job_id})


def wait_case_review(client, token, case_id, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = call(client, 'get', f'/api/case-center/cases/{case_id}', token)
        docs = detail.get('documents') or []
        top = docs[0] if docs else {}
        stage = detail.get('current_stage')
        status = top.get('review_status')
        print(f'  · 版本 {top.get("version_label", "—")} 审查={status} 阶段={stage}', flush=True)
        if status in ('done', 'error') or stage in ('legal_review', 'ready_to_sign', 'archived', 'cancelled'):
            return detail
        time.sleep(10)
    raise TimeoutError(f'合同审查超时（{timeout}s）')


def print_route(detail, label):
    route = (detail or {}).get('route_snapshot') or {}
    print(f'  [{label}] 审批路径={route.get("tier")} 需总监终审={route.get("requires_final")}')
    for reason in route.get('reasons') or []:
        print(f'    · {reason}')
    return route


def main():
    import argparse
    parser = argparse.ArgumentParser(description='启明智造场景真实数据全流程')
    parser.add_argument('--reset', action='store_true', help='先清空本地业务数据再跑')
    args = parser.parse_args()

    store.init_db()
    admin_t = token_for('admin')
    business_t = token_for('aaa')
    client = TestClient(app)
    users = {item['id']: item['username'] for item in store.list_users()}

    with client:
        if args.reset:
            print('== 0. 清空本地业务数据 ==')
            reset = call(client, 'post', '/api/admin/data/reset', admin_t)
            print('   reset 完成：', reset.get('deleted_total'), '条记录被清除')

        credit = find_credit(client, admin_t)

        # ---- 1. 创建信审 V1（TKM）----
        if credit:
            print('== 1. 信审已存在，跳过创建 ==')
        else:
            print('== 1. 创建“启明智造（模拟）有限公司”信审 V1（TKM）==')
            credit = call(client, 'post', '/api/credit/cases', business_t, json={
                'customer_name': CUSTOMER, 'business_type': BUSINESS_TYPE,
                'request_note': '为启明智造结构件模具、试制件和量产导入建立客户信用边界，并验证 CRM/ERP 既有敞口与合同金额的合并控制。',
                'conditions': {
                    'max_credit_amount': CREDIT_LIMIT, 'currency': 'CNY',
                    'max_payment_days': CREDIT_DAYS, 'min_prepayment_ratio': CREDIT_PREPAY,
                    'allowed_payment_methods': ['bank_transfer'], 'allow_vmi_jit': False,
                    'valid_from': 0, 'valid_to': 0,
                },
            })
            print(f'   创建成功：{credit["case_id"]} V{credit["version"]}')
        case_id = credit['case_id']
        reviewer_name = users.get(credit.get('assigned_to')) or 'bbb'
        reviewer_t = token_for(reviewer_name)

        # ---- 2. 上传财报 + 录入 CRM/ERP 敞口 ----
        documents = call(client, 'get', f'/api/credit/cases/{case_id}/documents', reviewer_t).get('items', [])
        if not documents:
            print('== 2. 上传客户财报（02-客户财务报告-启明智造.docx）==')
            with open(material('02-客户财务报告-启明智造.docx'), 'rb') as handle:
                uploaded = call(client, 'post', f'/api/credit/cases/{case_id}/documents', reviewer_t,
                                files={'file': ('02-客户财务报告-启明智造.docx', handle, 'application/octet-stream')},
                                data={'document_type': 'financial_report'})
            print('   解析状态：', uploaded.get('text_status'), '记录数：', uploaded.get('text_record_count'))
        else:
            print('== 2. 财报已上传，跳过 ==')
        exposure = call(client, 'get', f'/api/credit/cases/{case_id}/exposure', reviewer_t)
        if not exposure.get('payload'):
            print('   录入 CRM/ERP 敞口：应收 350000 + 已入单 450000')
            call(client, 'post', f'/api/credit/cases/{case_id}/exposure', reviewer_t, json={
                'current_receivables': 350000, 'booked_order_amount': 450000,
                'overdue_amount': 0, 'overdue_days': 0, 'currency': 'CNY', 'source': 'manual',
            })

        # ---- 3. 运行真实 Agent 评估 ----
        latest = call(client, 'get', f'/api/credit/cases/{case_id}/assessments/latest', reviewer_t)
        model_ready = bool(latest) and latest.get('status') == 'done' \
            and ((latest.get('report') or {}).get('assessment') or {}).get('model_status') == 'ready_for_reviewer'
        if model_ready:
            print('== 3. Agent 评估已有可用建议，跳过 ==')
            assessment = latest
        else:
            print('== 3. 启动真实 Agent 评估（DeepSeek LLM）==')
            started = call(client, 'post', f'/api/credit/cases/{case_id}/assessments', reviewer_t, json={})
            aid = started['assessment_id']
            print(f'   assessment={aid}，轮询中（最长 {CREDIT_TIMEOUT}s）…')
            status = wait_status(client, reviewer_t, f'/api/credit/cases/{case_id}/assessments/{aid}/status', CREDIT_TIMEOUT, {'done', 'error'})
            if status.get('status') == 'error':
                print('   评估失败：', status.get('error', '')[:300])
                assessment = {'status': 'error', 'assessment_id': aid}
            else:
                assessment = call(client, 'get', f'/api/credit/cases/{case_id}/assessments/latest', reviewer_t)
            if assessment and assessment.get('status') == 'done':
                asmt = (assessment.get('report') or {}).get('assessment') or {}
                rec = asmt.get('recommendation') or {}
                print('   评估完成：model_status=', asmt.get('model_status'),
                      '建议额度=', rec.get('max_credit_amount'), '账期=', rec.get('max_payment_days'),
                      '预付款=', rec.get('min_prepayment_ratio'))

        # ---- 4. 确认并提交审批 → 生效 ----
        credit = find_credit(client, admin_t)
        report = (assessment or {}).get('report') or {}
        model_status = ((report.get('assessment') or {}).get('model_status')) if isinstance(report, dict) else ''
        if credit['status'] != 'approved':
            print('== 4. 审批流转 ==')
            if assessment and assessment.get('status') == 'done' and model_status == 'ready_for_reviewer':
                print('   采用 Agent 建议并提交主管复核')
                try:
                    call(client, 'post', f'/api/credit/cases/{case_id}/assessments/{assessment["assessment_id"]}/apply', reviewer_t)
                except RuntimeError as exc:
                    print('   apply 跳过（可能已采用）：', str(exc)[:120])
                # 与前端一致：apply 记录采用，submit 才提交主管复核。
                try:
                    call(client, 'post', f'/api/credit/cases/{case_id}/submit', reviewer_t, expect=(200, 400))
                except RuntimeError as exc:
                    print('   submit 跳过（可能已提交）：', str(exc)[:120])
            else:
                print('   Agent 建议不可用，按人工条件提交（manual_override）')
                call(client, 'post', f'/api/credit/cases/{case_id}/assessments/{assessment["assessment_id"]}/reviewer-decision', reviewer_t, json={
                    'conditions': {
                        'max_credit_amount': CREDIT_LIMIT, 'currency': 'CNY',
                        'max_payment_days': CREDIT_DAYS, 'min_prepayment_ratio': CREDIT_PREPAY,
                        'allowed_payment_methods': ['bank_transfer'], 'allow_vmi_jit': False,
                    },
                    'reviewer_note': '真实数据演示：Agent 未能生成可采纳建议，按申请条件提交审批。',
                    'mode': 'manual_override',
                })
                call(client, 'post', f'/api/credit/cases/{case_id}/submit', reviewer_t)
            credit = find_credit(client, admin_t)
            if credit['status'] == 'pending_director':
                director_t = token_for(users.get(credit.get('assigned_to')) or 'ccc')
                credit = call(client, 'post', f'/api/credit/cases/{case_id}/decision', director_t, json={
                    'decision': 'approved', 'note': '已复核财报事实、CRM/ERP 既有敞口、Agent 建议及审核专员确认依据，同意按当前信用边界进入最终审批。'})
                print('   主管复核后状态：', credit['status'])
            if credit['status'] == 'pending_final':
                final_t = token_for(users.get(credit.get('assigned_to')) or 'admin')
                credit = call(client, 'post', f'/api/credit/cases/{case_id}/decision', final_t, json={
                    'decision': 'approved', 'note': '已核对客户信用边界及前序审批意见，同意该信用审核版本生效；合同端不得通过例外审批绕过信用条件。'})
                print('   总监终审后状态：', credit['status'])
        else:
            print('== 4. 信审已生效，跳过 ==')
        assert credit['status'] == 'approved', credit['status']
        print(f'   信审已生效：V{credit["version"]} 额度 {credit["conditions"]["max_credit_amount"]} / 账期 {credit["conditions"]["max_payment_days"]} 天 / 预付款 {credit["conditions"]["min_prepayment_ratio"]}%')

        # ---- 5. 合同案件：首版 → V2 → V3 ----
        cases = call(client, 'get', '/api/case-center/cases', admin_t).get('items', [])
        contract = next((item for item in cases if item['customer_name'] == CUSTOMER), None)
        if contract:
            print('== 5. 合同案件已存在，跳过创建 ==')
        else:
            print('== 5. 创建合同案件并上传首版风险合同 ==')
            contract = call(client, 'post', '/api/case-center/cases', business_t, json={
                'customer_name': CUSTOMER, 'business_type': '模塑一体', 'credit_case_id': case_id,
                'request_note': '启明智造结构件模具与量产导入销售合同（模拟演练材料）。', 'priority': 'normal',
            })
            print('   案件：', contract['case_id'])
        cid = contract['case_id']

        staged = [
            ('04-首版销售合同-风险.docx', 'main', '首版（预期阻断）'),
            ('06-修订销售合同-复审.docx', 'revision', 'V2 修订（预期二次阻断）'),
            ('11-最终销售合同-可签约V3.docx', 'revision', 'V3 最终（预期通过）'),
        ]
        for filename, role, label in staged:
            detail = call(client, 'get', f'/api/case-center/cases/{cid}', admin_t)
            docs = detail.get('documents') or []
            current_job = docs[0].get('job_id') if docs else ''
            top_name = docs[0].get('original_name') if docs else ''
            if top_name == filename:
                print(f'== 6. {label}（{filename}）已是当前版本，跳过上传 ==')
                continue
            print(f'== 6. 上传 {label}：{filename} ==')
            upload_case_document(client, business_t, cid, material(filename), case_id, '模塑一体', role,
                                 parent_job_id=current_job if role == 'revision' else '')
            detail = wait_case_review(client, admin_t, cid, REVIEW_TIMEOUT)
            print_route(detail, label)
            docs = detail.get('documents') or []
            top = docs[0] if docs else {}
            print(f'   审查结论：{top.get("overall_level", "—")}')

        # ---- 7. 结果汇总 ----
        print('== 7. 结果汇总 ==')
        detail = call(client, 'get', f'/api/case-center/cases/{cid}', admin_t)
        docs = detail.get('documents') or []
        route = detail.get('route_snapshot') or {}
        print(f'客户：{CUSTOMER}')
        print(f'信审：V{credit["version"]} 已生效')
        print(f'合同当前版本：{docs[0].get("original_name") if docs else "—"} · 阶段 {detail.get("current_stage")}')
        print(f'审批路径：{route.get("tier")} · 需总监终审：{route.get("requires_final")}')
        print('版本链：' + ' → '.join(f'{d.get("version_label")}({d.get("original_name","")[:14]})' for d in docs) or '—')
        print('演示入口：aaa（业务）/ bbb（审核专员）/ ccc（主管）/ admin 登录查看')


if __name__ == '__main__':
    main()
