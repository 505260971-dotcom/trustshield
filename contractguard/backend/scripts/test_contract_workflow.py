# -*- coding: utf-8 -*-
"""End-to-end persistence checks for approvals, materials, knowledge, and source DOCX export."""
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


DATA = os.path.join(os.path.dirname(__file__), '..', '..', '..', '数据包-信审与合同评审', '2）合同与订单样本')


def source_path():
    candidates = sorted(Path(DATA).glob('*.docx'))
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
    actor = store.get_user_by_username('admin')
    if not actor:
        raise SystemExit('缺少演示管理员，无法运行工作流回归')
    job_id = 'TEST-' + uuid.uuid4().hex[:12]
    try:
        credit = store.create_credit_case('合同工作流测试客户', {'max_credit_amount': 1000000, 'max_payment_days': 90, 'min_prepayment_ratio': 0, 'allowed_payment_methods': ['bank_transfer'], 'allow_vmi_jit': True}, '工作流验收信审', actor)
        store.submit_credit_case(credit['case_id'], actor)
        credit = store.decide_credit_case(credit['case_id'], 'approved', '工作流验收信审批准', actor)
        store.create_pending(job_id, 'workflow-fixture.docx', upload_copy, actor, '模塑一体', credit_case=credit)
        report = {
            'filename': 'workflow-fixture.docx',
            'summary': {'overall_level': '阻断·需CEO/总监审批', 'n_clauses': 1, 'n_risks': 2, 'high': 2, 'mid': 0, 'low': 0},
            'contract_fields': {'business_type': '模塑一体'},
            'clauses': [{'id': 'C1', 'text': 'TEST_WORKFLOW_FIXTURE', 'start_page': 1, 'end_page': 1, 'source_ref': '正文第1段'}],
            'risks': [
                {'clause_id': 'C1', 'page': 1, 'rule_id': 'R04', 'rule_baseline': '未经CEO批准不可签订有连带责任条款的合同', 'evidence': evidence, 'suggestion': '删除连带责任', 'severity': 'high', 'level': '阻断', 'numeric_note': '', 'decision_source': 'test'},
                {'clause_id': 'C1', 'page': 1, 'rule_id': 'R16', 'rule_baseline': '未经总监批准不可含有VMI/JIT', 'evidence': evidence, 'suggestion': '删除 VMI', 'severity': 'high', 'level': '阻断', 'numeric_note': '', 'decision_source': 'test'},
            ],
            'review_hints': [{'rule_id': 'R07', 'suggestion': '请补充质保次数及期限附件。'}],
            'steps': [], 'masked_entities': 0,
        }
        store.save_review(job_id, report, actor=actor)
        approvals = store.list_approvals(job_id)
        materials = store.list_material_requests(job_id)
        assert {x['required_role'] for x in approvals} == {'ceo', 'director'}
        assert len(materials) == 1 and materials[0]['status'] == 'open'
        for approval in approvals:
            store.decide_approval(job_id, approval['approval_id'], 'approved', '自动化验收批准', actor)
        store.resolve_material_request(job_id, materials[0]['request_id'], '已补充质保附件', actor)
        finding = store.list_findings(job_id)[0]
        store.record_finding_action(job_id, finding['finding_id'], 'edit', '采用模板改写', actor, '建议替换文本')
        assert store.list_knowledge(finding['rule_id'], 10), '采纳条款应进入知识库'
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
        print('OK: approvals, materials, knowledge, and source-contract export')
    finally:
        store.delete_review(job_id)
        store.purge_knowledge_by_source('TEST_WORKFLOW_FIXTURE')
        if os.path.exists(upload_copy):
            os.remove(upload_copy)


if __name__ == '__main__':
    main()
