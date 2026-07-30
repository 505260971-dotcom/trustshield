"""No-network regression tests for the local R02/R06/R16 policy decisions."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.services.deterministic_rules import applicable_rule_ids, assess_clause


def main():
    r02 = assess_clause('乙方发货后 120 天内，甲方支付全部货款。', '模塑一体')
    assert r02['R02']['facts']['term_days'] == 120
    assert 'R02' not in assess_clause('乙方发货后 60 天内，甲方支付全部货款。', '模塑一体')
    assert 'R02' not in assess_clause('乙方发货后 120 天内，甲方支付全部货款。', '一般')
    assert assess_clause('Payment shall be due net 120 days from invoice.', '模塑一体')['R02']['facts']['term_days'] == 120
    assert 'R02' in assess_clause('卖方同意买方在收到发票后以月结 **天+3 个月米信付款。', '模塑一体')

    r06 = assess_clause('买方可无责任取消或调整采购订单，供应商不得要求赔偿。', '一般')
    assert r06['R06']['facts']['without_liability'] is True
    assert 'R06' not in assess_clause('订单取消须提前 30 天通知，并补偿已产生的原材料成本。', '一般')

    r16 = assess_clause('供应商应按照 VMI 模式维持安全库存。', '模塑一体')
    assert r16['R16']['facts']['approval_role'] == '财务审批主管'
    assert 'R16' not in assess_clause('供应商应按照 VMI 模式维持安全库存。', '一般')
    assert 'R16' not in assess_clause('双方采用普通送货方式，不采用 VMI、JIT、供应商管理库存或准时制交付模式。', '模塑一体')
    assert 'R16' not in applicable_rule_ids('双方采用普通送货方式，不采用 VMI、JIT、供应商管理库存或准时制交付模式。', '模塑一体')
    assert assess_clause('本合同有效期为 8 年。', '一般')['R11']['facts']['validity_years'] == 8
    assert 'R11' in assess_clause('本协议有效期至双方权利和义务履行完毕之日止。', '一般')
    assert 'R12' in assess_clause('供应商应承担采购方遭受的所有直接损失及间接损失。', '一般')
    assert 'R14' not in applicable_rule_ids('公司注册地址和联系人信息', '一般')
    assert 'R14' in applicable_rule_ids('知识产权及专利许可归属约定', '一般')
    print('deterministic rule checks passed')


if __name__ == '__main__':
    main()
