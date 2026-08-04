"""Regression for the production RAG + ReAct contract-review agent.

Stubs the remote Agent boundary like the credit ReAct test; proves tool
routing, claim validation, deterministic credit-boundary comparison and
fail-closed behaviour.  Not a substitute for a live LLM / DashScope run.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services import contract_react_agent as agent
from app.services.rules import RULES


class _Response:
    def __init__(self, content): self.content = content


RULES_BY_ID = {r['id']: r for r in RULES}

CREDIT_SNAPSHOT = {
    'case_id': 'credit-case-1', 'customer_name': '深圳东江精密注塑有限公司', 'version': 3,
    'conditions': {'max_credit_amount': 1_000_000, 'currency': 'CNY', 'max_payment_days': 90,
                   'min_prepayment_ratio': 60, 'allowed_payment_methods': ['bank_transfer'],
                   'allow_vmi_jit': False},
}


def _clauses():
    rows = [
        {'clause_id': 'C1', 'text': '甲方（买方）：深圳东江精密注塑有限公司；乙方（卖方）：东江集团。项目名称：模具开发合同。合同总金额：人民币 1,200,000 元。',
         'source_ref': '第1条', 'start_page': 1},
        {'clause_id': 'C2', 'text': '付款方式：甲方应于货物发出后 120 日内完成全部付款，银行承兑汇票支付。',
         'source_ref': '第2条', 'start_page': 1},
        {'clause_id': 'C3', 'text': '交货模式：本合同适用 VMI/JIT 交货模式。',
         'source_ref': '第3条', 'start_page': 2},
        {'clause_id': 'C4', 'text': '违约金及损失赔偿累计不超过相关合同金额的 60%。',
         'source_ref': '第4条', 'start_page': 2},
    ]
    return [{**row, 'text_masked': row['text']} for row in rows]


def _claims():
    return [
        {'claim_id': 'f_amount', 'type': 'clause_field', 'field': 'contract_total_amount', 'value': '1,200,000',
         'evidence_id': 'C1', 'evidence_quote': '合同总金额：人民币 1,200,000 元'},
        {'claim_id': 'f_days', 'type': 'clause_field', 'field': 'payment_days', 'value': '120',
         'evidence_id': 'C2', 'evidence_quote': '货物发出后 120 日内完成全部付款'},
        {'claim_id': 'f_method', 'type': 'clause_field', 'field': 'payment_method', 'value': '银行承兑汇票支付',
         'evidence_id': 'C2', 'evidence_quote': '银行承兑汇票支付'},
        {'claim_id': 'f_delivery', 'type': 'clause_field', 'field': 'delivery_mode', 'value': 'VMI/JIT 交货模式',
         'evidence_id': 'C3', 'evidence_quote': 'VMI/JIT 交货模式'},
        {'claim_id': 'r_days', 'type': 'clause_risk', 'rule_id': 'R02', 'status': 'risk',
         'evidence_id': 'C2', 'evidence_quote': '货物发出后 120 日内完成全部付款', 'facts': {'term_days': '120'}},
        {'claim_id': 'r_penalty', 'type': 'clause_risk', 'rule_id': 'R10', 'status': 'risk',
         'evidence_id': 'C4', 'evidence_quote': '违约金及损失赔偿累计不超过相关合同金额的 60%', 'facts': {'penalty_ratio': '60'}},
    ]


def main():
    assert agent._claim_kind({'rule_id': 'R02', 'status': 'risk'}) == 'clause_risk'
    assert agent._claim_kind({'field': 'payment_days', 'value': 1}) == 'clause_field'
    assert agent._claim_kind({'category': 'entity', 'summary': 'x'}) == 'observation'

    clauses_by_id = {c['clause_id']: c for c in _clauses()}
    # Placeholder values resolve through the local mapping; quotes must be
    # contiguous fragments of the masked text the model saw.
    masked = dict(clauses_by_id)
    masked['C1'] = dict(clauses_by_id['C1'])
    masked['C1']['text_masked'] = '合同总金额：人民币 <MASK-AMOUNT-1> 元'
    placeholder_claim = [{'claim_id': 'f_ph', 'type': 'clause_field', 'field': 'contract_total_amount',
                          'value': '<MASK-AMOUNT-1>', 'evidence_id': 'C1',
                          'evidence_quote': '合同总金额：人民币 <MASK-AMOUNT-1> 元'}]
    valid, rejected, _ = agent._validate_claims(placeholder_claim, masked, {'C1'}, RULES_BY_ID, CREDIT_SNAPSHOT,
                                                {'<MASK-AMOUNT-1>': '人民币 1,200,000 元'})
    assert len(valid) == 1 and valid[0]['source_value'] == 1_200_000, (valid, rejected)

    valid, rejected, boundary = agent._validate_claims(_claims(), clauses_by_id, {'C1', 'C2', 'C3', 'C4'},
                                                       RULES_BY_ID, CREDIT_SNAPSHOT, {})
    assert len(valid) == 6 and not rejected, (valid, rejected)
    verdicts = {item['dimension']: item['verdict'] for item in boundary}
    assert verdicts == {'payment_days': 'exceeded', 'credit_amount': 'exceeded',
                        'acceptance_bill': 'needs_approval', 'vmi_jit': 'needs_approval'}, boundary
    assert boundary[0]['clause_id'] == 'C2'

    # A quote that is not in the visible evidence is rejected; a numeric fact
    # not present in the original clause is rejected.
    bad = [{'claim_id': 'f_bad', 'type': 'clause_field', 'field': 'payment_days', 'value': '30',
            'evidence_id': 'C2', 'evidence_quote': '不存在的原文片段'},
           {'claim_id': 'f_fake', 'type': 'clause_field', 'field': 'payment_days', 'value': '999',
            'evidence_id': 'C2', 'evidence_quote': '货物发出后 120 日内完成全部付款'}]
    _, rejected, _ = agent._validate_claims(bad, clauses_by_id, {'C2'}, RULES_BY_ID, CREDIT_SNAPSHOT, {})
    assert len(rejected) == 2, rejected

    # Full ReAct loop with stubbed model and reranker.
    old = agent.configured_llm, agent.get_llm, agent.invoke_remote, agent.rerank_required
    try:
        agent.configured_llm = lambda: True
        agent.get_llm = lambda **_: object()
        turns = []

        def invoke(_llm, _messages, **_kwargs):
            turns.append(1)
            if len(turns) == 1:
                return _Response(json.dumps({'reason_summary': '先检索付款与金额条款', 'action': 'tool', 'tool': 'search_clauses',
                                             'arguments': {'query': '付款账期 金额 交货模式'}, 'claims': [], 'material_requests': []}, ensure_ascii=False))
            if len(turns) == 2:
                return _Response(json.dumps({'reason_summary': '证据完整，提交可验证Claim', 'action': 'submit_claims', 'tool': '',
                                             'arguments': {}, 'claims': _claims(), 'material_requests': []}, ensure_ascii=False))
            return _Response(json.dumps({'reason_summary': '审查完成', 'action': 'finish', 'tool': '',
                                         'arguments': {}, 'claims': [], 'material_requests': []}, ensure_ascii=False))

        agent.invoke_remote = invoke
        rerank_calls = []

        def rerank(_query, pool):
            rerank_calls.append(_query)
            return {'mode': 'qwen3-rerank', 'request_id': 'mock-rerank', 'results': pool}
        agent.rerank_required = rerank
        result = agent.run_contract_react_audit(_clauses(), RULES_BY_ID, CREDIT_SNAPSHOT, '模塑一体', '乙方')
        assert result['status'] == 'ready_for_policy', result
        assert len(rerank_calls) == 1
        assert len(result['claims']) == 6
        assert len(result['trace']) == 3
        assert result['trace'][0]['tool'] == 'search_clauses'
        verdicts = {item['dimension']: item['verdict'] for item in result['boundary_checks']}
        assert verdicts['payment_days'] == 'exceeded' and verdicts['credit_amount'] == 'exceeded'
    finally:
        agent.configured_llm, agent.get_llm, agent.invoke_remote, agent.rerank_required = old

    # Fail closed: unmasked clauses never leave, and a missing Agent fails.
    old = agent.configured_llm
    try:
        agent.configured_llm = lambda: True
        unmasked = [dict(c) for c in _clauses()]
        for c in unmasked:
            c['text_masked'] = ''
        failed = agent.run_contract_react_audit(unmasked, RULES_BY_ID, CREDIT_SNAPSHOT, '模塑一体', '乙方')
        assert failed['status'] == 'execution_failed' and failed['reason'] == 'clauses_not_masked', failed

        agent.configured_llm = lambda: False
        skipped = agent.run_contract_react_audit(_clauses(), RULES_BY_ID, CREDIT_SNAPSHOT, '模塑一体', '乙方')
        assert skipped['status'] == 'execution_failed' and skipped['reason'] == 'agent_not_configured', skipped
    finally:
        agent.configured_llm = old

    print('contract ReAct agent validates claims, compares credit boundary and fails closed')


if __name__ == '__main__':
    main()
