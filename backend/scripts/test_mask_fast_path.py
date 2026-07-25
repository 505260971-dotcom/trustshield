"""Regression test for fast local masking and task-wide reversible mapping."""
import os, sys, time
os.environ['MASK_LLM_DEEP_SCAN'] = 'false'  # no model request in this regression test
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.services.mask import restore_text
from app.services.smart_mask import mask_clauses_smart

clauses = [
    {'id':'C1','text':'深圳东江精密注塑有限公司联系人张三，电话13812345678，报价人民币 123,456 元。'},
    {'id':'C2','text':'收款账户为6222 1234 5678 9999，邮箱 buyer@example.com，地址：深圳市南山区科技园创新大道 8 号。'},
    {'id':'C3','text':'产品图号 DWG-2026-A17 对应客户联系人李四签字确认。'},
]
started=time.perf_counter()
masked, mapping=mask_clauses_smart(clauses)
elapsed=(time.perf_counter()-started)*1000
assert len(mapping) >= 8
assert len(mapping) == len(set(mapping))
assert [restore_text(x['text_masked'], mapping) for x in masked] == [x['text'] for x in clauses]
assert all('<MASK-' in x['text_masked'] for x in masked)
print(f'fast masking checks passed: {len(mapping)} entities, {elapsed:.2f} ms, reversible task-wide mapping')
