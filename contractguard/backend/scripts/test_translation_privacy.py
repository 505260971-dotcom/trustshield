"""No-network regression test for privacy-preserving LLM translation.

Run with: python scripts/test_translation_privacy.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.services import translate

raw = '深圳东江精密注塑有限公司应向张三（13812345678，buyer@example.com）支付人民币 1,200,000 元。'
mapping = {
    '<MASK-COMPANY-1>': '深圳东江精密注塑有限公司',
    '<MASK-PERSON-2>': '张三',
    '<MASK-PHONE-3>': '13812345678',
    '<MASK-EMAIL-4>': 'buyer@example.com',
    '<MASK-AMOUNT-5>': '人民币 1,200,000 元',
}
captured = []

class FakeResponse:
    content = json.dumps({'items': [{'clause_id': 'C1', 'translated':
        '<MASK-COMPANY-1> shall pay <MASK-PERSON-2> at <MASK-PHONE-3> / <MASK-EMAIL-4> <MASK-AMOUNT-5>.'}]})

def fake_invoke(_llm, messages, **_kwargs):
    captured.append(messages[-1].content)
    return FakeResponse()

old_llm, old_invoke = translate.get_llm, translate.invoke_remote
translate.get_llm = lambda **_kwargs: object()
translate.invoke_remote = fake_invoke
try:
    result = translate.run_translate({'clauses': [{'id': 'C1', 'text': raw}], 'contract_fields': {'parties': {'甲方': '泄露禁止'}}},
                                     target_lang='en', mapping=mapping)
finally:
    translate.get_llm, translate.invoke_remote = old_llm, old_invoke

payload = captured[0]
for secret in mapping.values():
    assert secret not in payload, f'sensitive value leaked to translation payload: {secret}'
assert '<MASK-COMPANY-1>' in payload and '<MASK-AMOUNT-5>' in payload
item = result['translated'][0]
assert item['original'] == raw
assert '深圳东江精密注塑有限公司' in item['translated']
assert '人民币 1,200,000 元' in item['translated']
assert item['mask_restored'] is True
assert result['contract_fields_translated'] == {}
assert all('mapping' not in str(value).lower() for value in result.values())
print('translation privacy checks passed')
