# 东江销售合同底限条款（16 条）结构化规则库
# dim: 与抽取字段对应的语义维度，用于确定性校验与 LLM 归类

RULES = [
    {'id': 'R01', 'dim': 'pay_before_delivery', 'baseline': '模具交付前，公司必须收到不少于货款60%的款项', 'check': '模具交付前收款比例低于60%即为风险', 'applies_to':['模塑一体','TKM','TKP'], 'approval_role':'', 'template':'模具交付前，甲方应支付不少于对应货款的60%。'},
    {'id': 'R02', 'dim': 'pay_after_delivery_days', 'baseline': '模塑一体业务的收款期限不得超过发货后90天', 'check': '发货后收款账期超过90天即为风险', 'applies_to':['模塑一体'], 'approval_role':'', 'template':'甲方应于货物发出后90日内完成全部付款。'},
    {'id': 'R03', 'dim': 'pay_method_acceptance', 'baseline': '付款方式为银行承兑汇票时须经集团财务总监批准', 'check': '出现银行承兑汇票且未经最终审批即风险', 'applies_to':['全部'], 'approval_role':'final_approver', 'template':'付款方式为银行承兑汇票的，须取得集团财务总监书面批准后方可生效。'},
    {'id': 'R04', 'dim': 'joint_liability', 'baseline': '未经集团财务总监批准不可签订有连带责任条款的合同', 'check': '出现连带责任且未经最终审批即风险', 'applies_to':['全部'], 'approval_role':'final_approver', 'template':'删除连带责任约定；任何例外须取得集团财务总监书面批准。'},
    {'id': 'R05', 'dim': 'exclusivity', 'baseline': '未经集团财务总监批准，不可签订含有排他性内容的合同', 'check': '出现排他或独家安排且未经最终审批即为风险', 'applies_to':['全部'], 'approval_role':'final_approver', 'template':'本合同不构成排他、独家或最惠合作安排；任何例外须取得集团财务总监书面批准。'},
    {'id': 'R06', 'dim': 'cancel_order', 'baseline': '客户可无责任取消订单或预测的合同', 'check': '客户可无责取消订单/预测即风险提示', 'applies_to':['全部'], 'approval_role':'', 'template':'订单取消应提前书面通知，并赔偿已发生且不可转移的原料、生产及物流成本。'},
    {'id': 'R07', 'dim': 'warranty', 'baseline': '质保期应同时约定啤次和期限，并以先到者为准', 'check': '质保期只约定啤次或期限之一，或未约定以先到者为准，即为风险', 'applies_to':['全部'], 'approval_role':'', 'template':'质保期以交付后 X 个月或 Y 啤次先到者为准。'},
    {'id': 'R08', 'dim': 'warranty_replacement', 'baseline': '模塑一体业务中，替代品或替换品的质保期重新计算，或从终端成品时间起算', 'check': '替代品或替换品的质保期起算方式不符合要求即为风险', 'applies_to':['模塑一体'], 'approval_role':'', 'template':'替代品或替换品不重新起算质保期，除非双方另有书面约定。'},
    {'id': 'R09', 'dim': 'law_identify_obligation', 'baseline': '将产品销售国适用法律法规的识别义务归于我方的合同', 'check': '销售国法律识别义务归属于我方即为风险', 'applies_to':['全部'], 'approval_role':'', 'template':'销售国适用法律法规的识别及合规要求应由需求提出方提供并确认。'},
    {'id': 'R10', 'dim': 'penalty_ratio', 'baseline': '有交易金额的合同，违约金与损失赔偿合计不得超过合同金额的50%', 'check': '违约金与赔偿合计超过合同金额50%即为风险', 'applies_to':['全部'], 'approval_role':'', 'template':'违约金及损失赔偿累计不超过相关合同金额的50%。'},
    {'id': 'R11', 'dim': 'validity_years', 'baseline': '合同有效期不得超过5年', 'check': '合同有效期 > 5年即风险', 'applies_to':['全部'], 'approval_role':'', 'template':'本合同有效期不超过五年，续期须经双方书面确认。'},
    {'id': 'R12', 'dim': 'penalty_no_amount', 'baseline': '没有具体交易金额的合同，违约金与损失赔偿合计须低于港币100万元，且不得承担客户的间接损失', 'check': '没有具体金额的合同，索赔达到或超过港币100万元，或承担间接损失，即为风险', 'applies_to':['全部'], 'approval_role':'', 'template':'不承担间接、附带、惩罚性或预期利益损失；赔偿总额低于港币100万元。'},
    {'id': 'R13', 'dim': 'scope_spillover', 'baseline': '合同义务应仅限于签约主体，不得扩展至关联公司或其他主体', 'check': '合同义务扩展至关联公司或其他主体即为风险', 'applies_to':['全部'], 'approval_role':'', 'template':'本合同仅约束签约双方，不对任何关联公司或其他主体产生义务。'},
    {'id': 'R14', 'dim': 'ip_ownership', 'baseline': '知识产权应归我方、双方共有或各自所有；履约中，我方知识产权仅向客户授予有期限、免费且不可转让的有限许可', 'check': '知识产权归客户所有，或存在知识产权流失风险，即为风险', 'applies_to':['全部'], 'approval_role':'', 'template':'各方既有知识产权归各自所有；我方仅授予客户履约所需、有限期、免费且不可转让的许可。'},
    {'id': 'R15', 'dim': 'price_lock', 'baseline': '模塑一体业务合同约定不得提价，或提价未达成一致时，持续供货不得超过3个月', 'check': '不得提价，或未达成价格调整协议却持续供货超过3个月，即为风险', 'applies_to':['模塑一体'], 'approval_role':'', 'template':'价格调整未能达成一致时，按原价持续供货不超过三个月。'},
    {'id': 'R16', 'dim': 'vmi_jit', 'baseline': '模塑一体业务未经财务审批主管批准，不得包含 VMI/JIT 交货模式条款', 'check': '出现 VMI/JIT 且未经主管批准即为风险', 'applies_to':['模塑一体'], 'approval_role':'director', 'template':'删除 VMI/JIT 交货模式；任何例外须取得财务审批主管书面批准。'},
]

DIMENSIONS = [r['dim'] for r in RULES]
RULE_BY_ID = {r['id']: r for r in RULES}
