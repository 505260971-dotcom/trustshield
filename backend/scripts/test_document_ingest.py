# -*- coding: utf-8 -*-
"""Regression checks for table-based contract and purchase-order clauses."""
import os
import sys
from pathlib import Path
import tempfile

from docx import Document

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.parse import parse_contract


DATA = os.path.join(
    os.path.dirname(__file__), '..', '..', 'docs', '00-命题与数据', '数据包-信审与合同评审', '2）合同与订单样本'
)


def sample_path():
    candidates = sorted(path for path in Path(DATA).glob('*.docx') if not path.name.startswith('~$'))
    if not candidates:
        raise SystemExit(f'未找到 DOCX 验收样例: {DATA}')
    preferred = next((path for path in candidates if '销售订单' in path.name), candidates[0])
    return str(preferred)


def fixture_path():
    path = os.path.join(tempfile.gettempdir(), 'contractguard-table-ingest-fixture.docx')
    document = Document()
    document.add_paragraph('采购订单')
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = '注意事项'
    table.cell(0, 1).text = '供应商承担所有直接及间接损失。'
    table.cell(1, 0).text = '知识产权'
    table.cell(1, 1).text = '供应商保证知识产权归其所有。'
    document.save(path)
    return path


def main():
    path = fixture_path()
    result = parse_contract(path)
    clauses = result['clauses']
    table_clauses = [c for c in clauses if '表格' in c.get('source_ref', '')]
    risk_terms = [c for c in table_clauses if any(term in c.get('text', '') for term in ('间接损失', '知识产权', '连带责任', '违约金'))]

    assert clauses, '采购订单应至少产生一条条款'
    assert table_clauses, 'DOCX 表格内容必须进入条款列表'
    assert risk_terms, '表格内风险相关条款不得漏读'
    assert all(c.get('source_ref') for c in clauses), '每条条款必须保留来源锚点'
    if os.name == 'nt':
        assert any(c.get('source_ref', '').startswith('第') for c in clauses), 'Word 可用时 DOCX 条款应映射真实页码'

    print(f'OK: {os.path.basename(path)} -> {result["n_clauses"]} 条条款，其中 {len(table_clauses)} 条含表格来源锚点')
    print(f'OK: 表格风险条款定位 {risk_terms[0]["source_ref"]}')
    os.remove(path)


if __name__ == '__main__':
    main()
