"""Regression for audited-statement extraction from the supplied 2024 annual report."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.graph.credit_graph import _extract_from_document


REPORT = (Path(__file__).parent.parent.parent / 'docs' / '00-命题与数据' /
          '数据包-信审与合同评审' / '1）年报' / '东江集团 2024年年报.pdf')


def main():
    assert REPORT.is_file(), f'缺少官方年报样例: {REPORT}'
    facts, evidence = _extract_from_document({'document_id': 'annual-2024', 'stored_path': str(REPORT)})
    expected = {
        'revenue': 2_358_290_000, 'prior_revenue': 1_945_721_000,
        'net_profit': 261_850_000, 'prior_net_profit': 204_191_000,
        'current_assets': 2_038_669_000, 'current_liabilities': 773_977_000,
        'total_assets': 2_576_743_000, 'total_liabilities': 865_456_000,
        'operating_cashflow': 374_121_000,
    }
    for field, value in expected.items():
        assert facts.get(field) == value, f'{field}: expected {value}, got {facts.get(field)}'
    assert facts.get('financial_currency') == 'HKD'
    assert facts.get('financial_unit') == 'HKD'
    assert facts.get('financial_source_unit') == 'HKD thousand'
    rows = [item for item in evidence if item.get('category') == 'audited_financial_statement']
    assert len(rows) >= 7 and all(item.get('source_ref', '').startswith('第') for item in rows)
    print('annual-report audited-statement extraction passed')


if __name__ == '__main__':
    main()
