"""No-network regression for clause-diff incremental review scope and carried risks."""
import os
import sys
import tempfile

from docx import Document

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.graph.review_graph import node_enforce, node_ingest


def make_doc(lines):
    path = tempfile.mktemp(suffix='.docx', prefix='contractguard-incremental-')
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(path)
    return path


def main():
    old = make_doc(['第一条 付款条件。', '第二条 知识产权归属。', '第三条 质保期限。'])
    new = make_doc(['第一条 付款条件。', '第二条 知识产权归属改为客户所有。', '第三条 质保期限。'])
    try:
        old_state = node_ingest({'path': old, 'steps': []})
        parent = {'clauses': old_state['clauses'], 'risks': [{
            'clause_id': old_state['clauses'][0]['id'], 'page': 1, 'rule_id': 'R10', 'rule_baseline': '赔偿上限',
            'dim': 'penalty_ratio', 'evidence': '付款条件', 'suggestion': '限制赔偿', 'severity': 'high', 'level': '阻断', 'numeric_note': ''
        }]}
        state = node_ingest({'path': new, 'steps': [], 'parent_report': parent})
        scope = state['review_scope']
        assert scope['mode'] == 'incremental'
        assert len(scope['changed_clause_ids']) == 1
        assert len(state['review_clause_ids']) < len(state['clauses']) or len(state['clauses']) <= 3
        state.update({'infer': [], 'rules_by_id': {}, 'dim2rule': {}})
        output = node_enforce(state)
        assert any(item.get('decision_source') == 'carried_forward_unchanged_clause' for item in output['risks'])
        print('incremental review scope checks passed')
    finally:
        for path in (old, new):
            if os.path.exists(path): os.remove(path)


if __name__ == '__main__':
    main()
