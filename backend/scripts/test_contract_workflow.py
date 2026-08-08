# -*- coding: utf-8 -*-
"""End-to-end persistence checks for approvals, materials, and source DOCX export."""
import os
import sys
import tempfile
import uuid
from pathlib import Path
import shutil
import zipfile

from docx import Document

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import store
from app.services.export_docx import export_revised_docx


DATA = os.path.join(os.path.dirname(__file__), '..', '..', 'docs', '00-命题与数据', '数据包-信审与合同评审', '2）合同与订单样本')


def source_path():
    candidates = sorted(path for path in Path(DATA).glob('*.docx') if not path.name.startswith('~$'))
    if not candidates:
        raise SystemExit(f'未找到 DOCX 验收样例: {DATA}')
    return str(candidates[0])


def main():
    store.init_db()
    source = source_path()
    source_document = Document(source)
    evidence = next((paragraph.text.strip()[:40] for paragraph in source_document.paragraphs if paragraph.text.strip()), '')
    if not evidence:
        raise SystemExit('验收样例没有可用于高亮验证的正文文本')
    upload_copy = os.path.join(tempfile.gettempdir(), f'contractguard-workflow-{uuid.uuid4().hex}.docx')
    shutil.copy2(source, upload_copy)
    system_admin = store.get_user_by_username('admin')
    if not system_admin:
        raise SystemExit('缺少系统管理员，无法运行工作流回归')
    job_id = 'TEST-' + uuid.uuid4().hex[:12]
    revision_job = ''
    standard_job = ''
    try:
        reviewer = store.get_user_by_username('workflow-reviewer') or store.create_user('workflow-reviewer', '工作流信用审核专员', 'reviewer', 'ReviewerPassword2026!')
        director = store.get_user_by_username('workflow-director') or store.create_user('workflow-director', '工作流财务审批主管', 'director', 'DirectorPassword2026!')
        final_actor = store.get_user_by_username('workflow-final') or store.create_user('workflow-final', '工作流集团财务总监', 'final_approver', 'FinalPassword2026!')
        actor = store.get_user_by_username('workflow-business') or store.create_user('workflow-business', '工作流业务申请人', 'business', 'BusinessPassword2026!')
        credit = store.create_credit_case('合同工作流测试客户', {'max_credit_amount': 1000000, 'max_payment_days': 90, 'min_prepayment_ratio': 0, 'allowed_payment_methods': ['bank_transfer'], 'allow_vmi_jit': True}, '工作流验收信审', reviewer)
        assessment_task = store.start_credit_assessment(credit['case_id'], reviewer)
        assessment = store.finish_credit_assessment(assessment_task['assessment_id'], {
            'runtime_mode': 'production', 'audit_runtime': {'status': 'ready_for_policy'},
            'assessment': {'model_status': 'ready_for_reviewer', 'risk_flags': [], 'business_type': '一般', 'recommendation': credit['conditions']},
        }, [])
        credit = store.record_credit_reviewer_decision(credit['case_id'], assessment, credit['conditions'], '', 'agent_recommended', reviewer)
        credit = store.submit_credit_case(credit['case_id'], reviewer)
        # 信审专员确认额度与已纳入的公开尽调材料后，授信版本直接生效。
        # 财务审批主管和集团财务总监保留在具体合同的例外审批链路中，
        # 因此不应再为同一授信重复走两级审批。
        assert credit['status'] == 'approved', f'信审专员确认后应直接生效: {credit}'
        assert not credit.get('assigned_to'), f'已生效授信不应继续占用审批队列: {credit}'
        assigned = {item['id']: item for item in store.list_users()}

        def active_assignee(task_type: str) -> dict:
            detail = store.get_case_center(case_id, reviewer)
            task = next(item for item in detail['tasks'] if item['status'] == 'open' and item['task_type'] == task_type)
            return assigned[task['assignee_id']]

        contract = store.create_case_center('合同工作流测试客户', '模塑一体', '工作流合同测试', actor, credit['case_id'])
        case_id = store.create_pending(job_id, 'workflow-fixture.docx', upload_copy, actor, '模塑一体', credit_case=credit, case_id=contract['case_id'])
        report = {
            'filename': 'workflow-fixture.docx',
            'summary': {'overall_level': '阻断·须财务审批主管或集团财务总监审批', 'n_clauses': 1, 'n_risks': 3, 'high': 3, 'mid': 0, 'low': 0},
            'contract_fields': {'business_type': '模塑一体'},
            'clauses': [{'id': 'C1', 'text': 'TEST_WORKFLOW_FIXTURE', 'start_page': 1, 'end_page': 1, 'source_ref': '正文第1段'}],
            'risks': [
                {'clause_id': 'C1', 'page': 1, 'rule_id': 'R04', 'rule_baseline': '未经集团财务总监批准不可签订有连带责任条款的合同', 'evidence': evidence, 'suggestion': '删除连带责任', 'severity': 'high', 'level': '阻断', 'numeric_note': '', 'decision_source': 'test'},
                {'clause_id': 'C1', 'page': 1, 'rule_id': 'R16', 'rule_baseline': '未经财务审批主管批准不可含有VMI/JIT', 'evidence': evidence, 'suggestion': '删除 VMI', 'severity': 'high', 'level': '阻断', 'numeric_note': '', 'decision_source': 'test'},
                {'clause_id': 'C1', 'page': 1, 'rule_id': 'R16', 'rule_baseline': '未经财务审批主管批准不可含有VMI/JIT', 'evidence': evidence, 'suggestion': '删除 JIT 约定', 'severity': 'high', 'level': '阻断', 'numeric_note': '', 'decision_source': 'test'},
            ],
            'review_hints': [{'rule_id': 'R07', 'suggestion': '请补充质保次数及期限附件。'}],
            'steps': [], 'masked_entities': 0,
        }
        store.save_review(job_id, report, actor=actor)
        # Case-level approval must remain a reversible four-role flow, not a
        # one-way "approve or reject" button.  The per-finding approvals below
        # are deliberately kept as the separate hard gate for signing.
        store.transition_case(case_id, 'claim', reviewer, '领取合同初审')
        store.transition_case(case_id, 'submit_approval', reviewer, '请主管复核合同例外')
        approval_actor = active_assignee('approval')
        returned_case = store.transition_case(case_id, 'return_to_reviewer', approval_actor, '请核对付款条件和例外依据')
        assert returned_case['current_stage'] == 'legal_review'
        store.transition_case(case_id, 'submit_approval', reviewer, '已按主管意见修订并重新报送')
        approval_actor = active_assignee('approval')
        final_case = store.transition_case(case_id, 'escalate_final', approval_actor, '上报集团财务总监最终审批')
        assert final_case['current_stage'] == 'final_approval'
        final_actor = active_assignee('final_approval')
        returned_business = store.transition_case(case_id, 'return_to_business', final_actor, '请业务补充对方盖章确认函')
        assert returned_business['current_stage'] == 'awaiting_business'

        # A new revision becomes the current business version.  Historical V1
        # approvals/material requests remain auditable but must not block V2
        # from reaching the signing gate.
        revision_job = 'TEST-' + uuid.uuid4().hex[:12]
        revision_case = store.create_pending(revision_job, 'workflow-revision.docx', upload_copy, actor, '模塑一体', parent_job_id=job_id, credit_case=credit, case_id=case_id, document_role='revision')
        assert revision_case == case_id
        # V2 是低风险小额版本：合同金额 + 敞口远低于信审额度，差异化审批
        # 路径判定为快速档，审核员可直放（真实审查会注入 credit_decision，
        # 这里手工构造时补全，与 _run 的行为保持一致）。
        store.save_review(revision_job, {
            'filename': 'workflow-revision.docx',
            'summary': {'overall_level': '低风险', 'n_clauses': 1, 'n_risks': 0, 'high': 0, 'mid': 0, 'low': 0},
            'contract_fields': {'business_type': '模塑一体', 'total_amount': 100000},
            'credit_decision': {'case_id': credit['case_id'], 'customer_name': '合同工作流测试客户', 'version': credit['version'],
                                'conditions': credit['conditions'], 'exposure_snapshot_at_review': {}},
            'clauses': [], 'risks': [], 'review_hints': [], 'steps': [], 'masked_entities': 0,
        }, actor=actor)
        revision_case_detail = store.get_case_center(case_id, reviewer)
        assert revision_case_detail['documents'][0]['is_current_version'] is True
        assert revision_case_detail['documents'][0]['job_id'] == revision_job
        route = revision_case_detail.get('route_snapshot') or {}
        assert route.get('tier') == 'fast', f'低风险小额版本应判定快速路径: {route}'
        active_task = next(task for task in revision_case_detail['tasks'] if task['status'] == 'open')
        reviewer = assigned[active_task['assignee_id']]
        ready_case = store.transition_case(case_id, 'ready_for_signing', reviewer, 'V2 已完成审查，历史版本仅留档')
        assert ready_case['current_stage'] == 'ready_to_sign'

        # 差异化审批路径强制校验：缺失金额等 fail-safe 场景判定标准档，
        # 审核员不得直放，必须提交主管复核。
        standard_job = 'TEST-' + uuid.uuid4().hex[:12]
        store.create_pending(standard_job, 'workflow-standard.docx', upload_copy, actor, '模塑一体', parent_job_id=job_id, credit_case=credit, case_id=case_id, document_role='revision')
        store.save_review(standard_job, {
            'filename': 'workflow-standard.docx',
            'summary': {'overall_level': '低风险', 'n_clauses': 1, 'n_risks': 0, 'high': 0, 'mid': 0, 'low': 0},
            'contract_fields': {'business_type': '模塑一体'}, 'clauses': [], 'risks': [], 'review_hints': [], 'steps': [], 'masked_entities': 0,
        }, actor=actor)
        standard_detail = store.get_case_center(case_id, reviewer)
        assert (standard_detail.get('route_snapshot') or {}).get('tier') == 'standard', '缺金额版本应保守判定标准档'
        try:
            store.transition_case(case_id, 'ready_for_signing', reviewer, '不应允许直放')
            raise AssertionError('标准档不应允许审核专员直放')
        except ValueError:
            pass
        # 标准档只能走“提交主管复核 → 提交最终审批”，主管也不得直接批准。
        store.transition_case(case_id, 'submit_approval', reviewer, '标准档：复核完成，提交主管复核')
        approval_actor = active_assignee('approval')
        try:
            store.transition_case(case_id, 'approve_for_signing', approval_actor, '标准档不应允许主管直接批准')
            raise AssertionError('标准档不应允许主管直接批准可签约')
        except ValueError:
            pass
        escalated = store.transition_case(case_id, 'escalate_final', approval_actor, '标准档：提交集团财务总监最终审批')
        assert escalated['current_stage'] == 'final_approval', '标准档应进入总监终审'

        approvals = store.list_approvals(job_id)
        materials = store.list_material_requests(job_id)
        assert {x['required_role'] for x in approvals} == {'final_approver', 'director'}
        assert len([x for x in approvals if x['required_role'] == 'director']) == 2
        assert len(materials) == 1 and materials[0]['status'] == 'open'
        try:
            director_item = next(x for x in approvals if x['required_role'] == 'director')
            store.decide_approval(job_id, director_item['approval_id'], 'approved', '不应允许最终审批人代主管处理', final_actor)
            raise AssertionError('最终审批人不得代办主管级条款例外')
        except ValueError as exc:
            assert '无权' in str(exc)
        batch = store.decide_approvals_batch(job_id, 'approved', '同级例外统一批准', director)
        assert batch == {'count': 2, 'status': 'approved', 'required_role': 'director'}
        for approval in approvals:
            if approval['required_role'] == 'director':
                continue
            approver = final_actor if approval['required_role'] == 'final_approver' else director
            store.decide_approval(job_id, approval['approval_id'], 'approved', '自动化验收批准', approver)
        store.resolve_material_request(job_id, materials[0]['request_id'], '已补充质保附件', actor)
        finding = store.list_findings(job_id)[0]
        store.record_finding_action(job_id, finding['finding_id'], 'edit', '采用模板改写', actor, '建议替换文本')
        output = os.path.join(tempfile.gettempdir(), f'{job_id}.docx')
        export_revised_docx(report, output, source_path=source)
        assert os.path.exists(output) and os.path.getsize(output) > 0, '应生成原合同修订副本'
        with zipfile.ZipFile(output) as archive:
            document_xml = archive.read('word/document.xml')
            names = archive.namelist()
        assert b'w:highlight' in document_xml, '修订稿应高亮原合同中的风险证据'
        assert 'word/comments.xml' in names, '修订稿应含 Word 原生批注'
        assert b'w:ins' in document_xml or b'w:del' in document_xml, '修订稿应包含 Word 原生修订痕迹'
        os.remove(output)
        print('OK: approvals, materials, and source-contract export')
    finally:
        for stale_job in (standard_job, revision_job):
            if stale_job:
                store.delete_review(stale_job)
        store.delete_review(job_id)
        if os.path.exists(upload_copy):
            os.remove(upload_copy)


if __name__ == '__main__':
    main()
