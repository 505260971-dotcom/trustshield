# -*- coding: utf-8 -*-
"""效果验证脚本: 用 4 份样本合同回放审查,对照人工金标计算命中/误报/漏报。
用法: python scripts/validate.py [--quick]
  --quick 仅跑例1(主合同骨架)。
金标依据: 合同样本人工风险判定 + 销售合同底限条款。
"""
import os, sys, json, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.graph.review_graph import run_review

DATA = os.path.join(os.path.dirname(__file__), '..', '..', 'docs', '00-命题与数据', '数据包-信审与合同评审', '2）合同与订单样本')

SAMPLES = [
    ('销售合同 例1（客户的采购合同）Sales Contract #1.docx', '模塑一体',
     {'R16', 'R06', 'R12', 'R04', 'R10'}),   # VMI/JIT, 取消订单, 间接损失, 连带, 高比例赔偿
    ('销售合同 例2（客户的采购合同）Sales Contract #2.docx', '模塑一体',
     {'R02', 'R11', 'R10'}),                   # 复杂付款/期限/赔偿
    ('销售合同 例3（客户的采购合同）Sales Contract #3.docx', '一般',
     {'R14', 'R09', 'R07'}),                   # 知识产权/法律识别/质保(多语言样例)
    ('销售订单 例1（客户的采购订单）Sales PO #1.docx', '采购订单',
     {'R06'}),                                  # PO 调整/取消
]

def main():
    quick = '--quick' in sys.argv
    only = next((arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--only=')), '')
    rows = SAMPLES[:1] if quick else SAMPLES
    if only:
        rows = [row for row in SAMPLES if only in row[0]]
        if not rows:
            raise SystemExit(f'未匹配样本: {only}')
    total_hit = total_gold = total_extra = 0
    print('='*80)
    print('TrustShield 效果验证  (样本 -> Agent 命中 vs 人工金标)')
    print('='*80)
    for fname, business_type, gold in rows:
        p = os.path.join(DATA, fname)
        if not os.path.exists(p):
            print(f'[skip] 未找到: {fname}'); continue
        t0 = time.time()
        try:
            rep = run_review(p, business_type_hint=business_type)
        except Exception as e:
            print(f'[ERR] {fname}: {e}'); continue
        hits = {r.get('rule_id') for r in rep.get('risks', []) if r.get('rule_id')}
        hit = gold & hits
        miss = gold - hits           # 漏报
        extra = hits - gold           # 误报
        sm = rep.get('summary', {})
        print(f'\n>> {fname}')
        print(f'   条款 {sm.get("n_clauses",0)} | 风险 {sm.get("n_risks",0)} (高{sm.get("high",0)} 中{sm.get("mid",0)} 低{sm.get("low",0)}) | 耗时 {time.time()-t0:.1f}s')
        print(f'   金标: {sorted(gold)}')
        print(f'   命中: {sorted(hit)}   漏报: {sorted(miss)}   误报: {sorted(extra)}')
        print(f'   命中率 {len(hit)/max(1,len(gold))*100:.0f}%   精确率 {len(hits & gold)/max(1,len(hits))*100:.0f}%')
        total_hit += len(hit); total_gold += len(gold); total_extra += len(extra)
    print('\n' + '='*80)
    if total_gold:
        print(f'总体: 金标项 {total_gold}  命中 {total_hit}  漏报 {total_gold-total_hit}  误报 {total_extra}')
        print(f'召回率(Recall) {total_hit/total_gold*100:.0f}%   '
              f'精确率(Precision) {total_hit/max(1,total_hit+total_extra)*100:.0f}%')
    print('说明: 召回=应报风险中Agent报到比例; 精确=Agent所报风险中正确的比例;')
    print('      低置信命中(evidence空)已降级为low但仍可见,计入hits。')
    print('='*80)

if __name__ == '__main__':
    main()
