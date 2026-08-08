# -*- coding: utf-8 -*-
"""默认演示数据 seed（幂等）。

以“启明制造”作为本 Demo 的默认示例客户，生成差异化审批路径的对照：

    客户信审已生效（额度 300 万 / 60 天 / 预付款 50%）
    ├─ 合同 A：金额 150 万 + 已有敞口 0，占用率 50% ≤ 快速路径阈值 80%
    │    → 判定 fast：审核专员复核后，主管批准即可签约（总监不出现）
    └─ 合同 B：金额 500 万 + 已有敞口 0，占用率 167% > 额度
         → 判定 blocked：不能放行，需修订合同或更新信用审核

运行：python scripts/seed_fast_track_demo.py
"""
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import store  # noqa: E402

CUSTOMER = '启明制造'
LIMIT = 3000000        # 信审额度 300 万
DAYS = 60              # 账期 60 天
PREPAY = 50            # 交付前最低收款 50%
AMOUNT_FAST = 1500000  # 合同 A：150 万 → 占用率 50%，走快速路径
AMOUNT_BLOCK = 5000000  # 合同 B：500 万 → 超额度，走阻断
SAMPLE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'docs', '00-命题与数据', '数据包-信审与合同评审', '2）合同与订单样本')


def _find(username, role):
    user = store.get_user_by_username(username)
    if user:
        return user
    candidates = [item for item in store.list_users() if item['role'] == role and item['active']]
    if candidates:
        return candidates[0]
    raise SystemExit(f'缺少 {role} 角色账号，请先创建演示账号再运行 seed')


def _report(filename, amount, credit):
    """构造一份与真实审查结构一致的合同报告（手工 seed 演示数据）。"""
    return {
        'filename': filename,
        'summary': {'overall_level': '可签约', 'n_clauses': 2, 'n_risks': 0, 'high': 0, 'mid': 0, 'low': 0},
        'contract_fields': {'business_type': 'TKP', 'total_amount': amount, 'currency': 'CNY', 'our_party': '东江精密制造有限公司'},
        'clauses': [
            {'id': 'C1', 'text': '买方应于交付后 60 天内付款，发货前支付不低于 50%。', 'start_page': 1, 'end_page': 1, 'source_ref': '第 1 页 4.2 付款条件'},
            {'id': 'C2', 'text': '本合同项下风险条款由双方按制度标准条款执行。', 'start_page': 2, 'end_page': 2, 'source_ref': '第 2 页 8.1 一般条款'},
        ],
        'risks': [], 'review_hints': [], 'steps': ['材料解析完成', '条款完整性检查通过', '信审边界核对：未超额度', '底线规则扫描：未命中'],
        'masked_entities': 0,
        'credit_decision': {
            'case_id': credit['case_id'], 'customer_name': CUSTOMER, 'version': credit['version'],
            'conditions': credit['conditions'], 'exposure_snapshot_at_review': {},
        },
    }


def main():
    store.init_db()
    admin = store.get_user_by_username('admin')
    if not admin:
        raise SystemExit('缺少演示管理员，无法创建演示数据')
    business = _find('aaa', 'business')
    reviewer = _find('bbb', 'reviewer')
    assigned = {item['id']: item for item in store.list_users()}

    # 幂等：该客户已有生效信审或演示案件时跳过，避免重复造数。
    existing = store.list_credit_cases(CUSTOMER)
    existing_cases = store.list_case_center(admin, scope='all', limit=500)
    if any(item['customer_name'] == CUSTOMER for item in existing_cases) or any(
            item['status'] == 'approved' for item in existing):
        print(f'已存在 {CUSTOMER} 的演示数据，跳过创建。')
        case = next((item for item in existing_cases if item['customer_name'] == CUSTOMER), None)
        if case:
            detail = store.get_case_center(case['case_id'], admin)
            route = (detail or {}).get('route_snapshot') or {}
            print('当前案件审批路径：', route.get('tier'), route.get('reasons'))
        return

    # 1. 客户信审：业务发起 → 审核专员评估 → 主管/总监审批 → 已生效。
    credit = store.create_credit_case(CUSTOMER, {
        'max_credit_amount': LIMIT, 'currency': 'CNY', 'max_payment_days': DAYS,
        'min_prepayment_ratio': PREPAY, 'allowed_payment_methods': ['bank_transfer'],
        'allow_vmi_jit': False, 'valid_from': 0, 'valid_to': 0,
    }, '演示用：常规小额客户，申请 300 万额度、60 天账期、交付前收款 50%。', business, 'TKP')
    # 案件会自动分派给负责的信用审核专员/主管/总监，按分派结果解析实际处理人。
    reviewer = assigned[store.get_credit_case(credit['case_id'])['assigned_to']]
    assessment_task = store.start_credit_assessment(credit['case_id'], reviewer)
    assessment = store.finish_credit_assessment(assessment_task['assessment_id'], {
        'runtime_mode': 'production', 'audit_runtime': {'status': 'ready_for_policy'},
        'assessment': {'model_status': 'ready_for_reviewer', 'risk_flags': [], 'business_type': 'TKP',
                       'recommendation': credit['conditions']},
    }, [])
    credit = store.record_credit_reviewer_decision(credit['case_id'], assessment, credit['conditions'], '',
                                                   'agent_recommended', reviewer)
    store.submit_credit_case(credit['case_id'], reviewer)
    director = assigned[store.get_credit_case(credit['case_id'])['assigned_to']]
    credit = store.decide_credit_case(credit['case_id'], 'approved', '额度账期均在标准范围，主管复核通过', director)
    if credit['status'] == 'pending_final':
        final_actor = assigned[store.get_credit_case(credit['case_id'])['assigned_to']]
        credit = store.decide_credit_case(credit['case_id'], 'approved', '最终批准生效', final_actor)
    assert credit['status'] == 'approved', credit['status']

    # 2. 合同案件：业务上传两份对照合同 → 系统审查完成 → 待审核专员复核。
    sample = next((str(path) for path in Path(SAMPLE_DIR).glob('*.docx') if not path.name.startswith('~$')), 'seed-demo.docx')
    contract_a = store.create_case_center(CUSTOMER, 'TKP', '演示：小额合规合同（150 万），走快速审批路径。', business, credit['case_id'])
    job_a = 'DEMO-' + uuid.uuid4().hex[:8]
    store.create_pending(job_a, '启明制造年度采购合同.docx', sample, business, 'TKP',
                         credit_case=credit, case_id=contract_a['case_id'], document_role='main')
    store.save_review(job_a, _report('启明制造年度采购合同.docx', AMOUNT_FAST, credit), actor=business)
    contract_b = store.create_case_center(CUSTOMER, 'TKP', '演示：超额度合同（500 万），走阻断路径。', business, credit['case_id'])
    job_b = 'DEMO-' + uuid.uuid4().hex[:8]
    store.create_pending(job_b, '启明制造超额度采购合同.docx', sample, business, 'TKP',
                         credit_case=credit, case_id=contract_b['case_id'], document_role='main')
    store.save_review(job_b, _report('启明制造超额度采购合同.docx', AMOUNT_BLOCK, credit), actor=business)

    # 3. 验证判定结果并输出演示指引。
    for case_id, label in ((contract_a['case_id'], '合同 A（150 万）'), (contract_b['case_id'], '合同 B（500 万）')):
        detail = store.get_case_center(case_id, admin)
        route = (detail or {}).get('route_snapshot') or {}
        print(f'{label}：{route.get("tier")} · 需总监终审：{route.get("requires_final")}')
        print('  系统理由：' + '；'.join(route.get('reasons') or []))
    print(f'已创建演示数据：{CUSTOMER}')
    print(f'  信审版本 V{credit["version"]}：额度 {LIMIT} CNY / 账期 {DAYS} 天 / 预付款 {PREPAY}%')
    print('演示路径（快速）：bbb（信用审核专员）→ 合同审查 → 打开“启明制造年度采购合同” → 提交主管复核 → ccc（财务审批主管）→ 主管批准可签约（无需总监）')
    print('演示路径（阻断）：打开“启明制造超额度采购合同” → 系统提示超额度，需修订合同或更新信审')


if __name__ == '__main__':
    main()
