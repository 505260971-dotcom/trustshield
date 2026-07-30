"""Local, explainable decisions for the contract rules that must not depend on an LLM."""
import re


_DAYS = re.compile(r'(?:发货|交货|交付|出货|shipment|delivery)[^。；;]{0,80}?(?:后|起|within|after)?\s*(\d{1,4})\s*(?:个?工作)?(?:天|日|days?)', re.I)
_DAYS_REVERSED = re.compile(r'(\d{1,4})\s*(?:个?工作)?(?:天|日|days?)[^。；;]{0,80}?(?:后|起|within|after)?[^。；;]{0,20}(?:发货|交货|交付|出货|shipment|delivery)', re.I)
_PAYMENT_DAYS = re.compile(r'(?:付款|支付|payment|pay(?:ment)?\s+(?:shall\s+be\s+)?due|net)[^。；;]{0,60}?(\d{1,4})\s*(?:个?工作)?(?:天|日|days?)', re.I)
_PAYMENT_DAYS_REVERSED = re.compile(r'(\d{1,4})\s*(?:个?工作)?(?:天|日|days?)[^。；;]{0,60}(?:付款|支付|payment|invoice|net)', re.I)
_VALIDITY = re.compile(r'(?:有效期|合同期限|term|validity)[^。；;]{0,80}?(\d{1,2})\s*(?:个?年|years?|yr)', re.I)
_OPEN_ACCOUNT = re.compile(r'(?:月结|payment\s+terms?)[^。；;]{0,50}(?:\*+\s*(?:天|days?)\s*\+\s*)?3\s*(?:个?月|months?)', re.I)
_INDEFINITE_TERM = re.compile(r'(?:权利和义务履行完毕|rights?\s+and\s+obligations?\s+(?:are\s+)?fulfilled|until\s+.*?obligations?)', re.I)
_INDIRECT_LOSS = re.compile(r'(?:间接(?:之)?损失|indirect\s+(?:and\s+consequential\s+)?loss(?:es)?)', re.I)
_SUPPLIER_LIABILITY = re.compile(r'(?:乙方|供应商|卖方|supplier|seller)[^。；;]{0,100}(?:承担|赔偿|负责|负担|bear|liable|compensat)', re.I)
_CANCEL = re.compile(r'(?:取消|撤销|变更|调整).{0,28}(?:订单|预测|purchase\s*order|forecast)', re.I)
_NO_FAULT = re.compile(r'(?:无责任|无需承担|不承担.{0,8}(?:责任|费用|赔偿)|without\s+(?:liability|charge)|at\s+(?:its|buyer.{0,8})\s+discretion)', re.I)
_VMI = re.compile(r'\b(?:VMI|JIT|vendor\s*managed\s*inventory|just[ -]?in[ -]?time)\b|供应商管理库存|准时制', re.I)
_VMI_NEGATION = re.compile(r'(?:不(?:采用|使用|含有?|包含|涉及)|未(?:采用|使用|包含)|禁止(?:采用|使用|包含)?|不得(?:采用|使用|包含)?|无)[^。；;]{0,24}$', re.I)


def positive_vmi_match(text: str):
    """Ignore VMI/JIT terms explicitly negated by the contract clause."""
    value = text or ''
    for match in _VMI.finditer(value):
        prefix = value[max(0, match.start() - 32):match.start()]
        if not _VMI_NEGATION.search(prefix):
            return match
    return None


def applicable_rule_ids(text: str, business_type: str) -> list[str]:
    """Cheap lexical gate before semantic retrieval. It deliberately favors recall."""
    value = text or ''
    lower = value.lower()
    result = []
    patterns = {
        'R01': r'付款|货款|预付|定金|delivery|payment',
        'R02': r'付款|账期|payment|发货|交付|delivery|shipment',
        'R03': r'承兑|汇票|acceptance',
        'R04': r'连带(?:责任)?|joint(?:\s+and\s+several)?\s+liabilit',
        'R05': r'排他|独家|exclusive|exclusiv',
        'R06': r'取消|撤销|变更|调整|订单|预测|cancel|forecast',
        'R07': r'质保|保修|warranty',
        'R08': r'替代品|替换品|重新起算|replacement',
        'R09': r'法律|法规|合规|law|regulation',
        'R10': r'违约金|赔偿|损失|penalty|damages',
        'R11': r'有效期|期限|年|term|validity',
        'R12': r'间接损失|赔偿|损失|indirect\s+loss',
        'R13': r'关联公司|关联方|附属|affiliate',
        'R14': r'知识产权|专利|著作权|许可|intellectual\s+property|license',
        'R15': r'提价|价格调整|原价|price',
        'R16': r'\bVMI\b|\bJIT\b|库存|供应商管理库存|准时制',
    }
    molding_only = {'R01', 'R02', 'R08', 'R15', 'R16'}
    for rule_id, pattern in patterns.items():
        if rule_id in molding_only and business_type not in {'模塑一体', 'TKM', 'TKP'}:
            continue
        if rule_id in {'R02', 'R08', 'R15', 'R16'} and business_type != '模塑一体':
            continue
        if rule_id == 'R16' and not positive_vmi_match(value):
            continue
        if re.search(pattern, value, re.I):
            result.append(rule_id)
    return result


def assess_clause(text: str, business_type: str) -> dict[str, dict]:
    """Return rule-id keyed proven findings with evidence and structured facts."""
    value = text or ''
    findings: dict[str, dict] = {}
    if business_type == '模塑一体':
        match = _DAYS.search(value) or _DAYS_REVERSED.search(value) or _PAYMENT_DAYS.search(value) or _PAYMENT_DAYS_REVERSED.search(value)
        if match and int(match.group(1)) > 90:
            days = int(match.group(1))
            findings['R02'] = {
                'evidence': match.group(0)[:160],
                'facts': {'term_days': days, 'payment_trigger': 'delivery'},
                'note': f'本地提取：交付/发货后付款账期 {days} 天，超过 90 天底线',
            }
        elif _OPEN_ACCOUNT.search(value):
            findings['R02'] = {
                'evidence': _OPEN_ACCOUNT.search(value).group(0)[:160],
                'facts': {'term_days': 91, 'payment_trigger': 'invoice'},
                'note': '本地提取：月结天数叠加 3 个月信用期，付款账期超过 90 天底线',
            }
        vmi = positive_vmi_match(value)
        if vmi:
            findings['R16'] = {
                'evidence': vmi.group(0),
                'facts': {'delivery_mode': vmi.group(0), 'approval_role': '财务审批主管'},
                'note': '本地提取：存在 VMI/JIT/供应商管理库存交付模式，需财务审批主管书面审批',
            }
    validity = _VALIDITY.search(value)
    if validity and int(validity.group(1)) > 5:
        years = int(validity.group(1))
        findings['R11'] = {
            'evidence': validity.group(0)[:160],
            'facts': {'validity_years': years},
            'note': f'本地提取：合同有效期 {years} 年，超过 5 年上限',
        }
    elif _INDEFINITE_TERM.search(value):
        findings['R11'] = {
            'evidence': _INDEFINITE_TERM.search(value).group(0)[:160],
            'facts': {'validity_years': None, 'indefinite_term': True},
            'note': '本地提取：合同期限以权利义务履行完毕为止，未设五年以内的固定上限',
        }
    cancel = _CANCEL.search(value)
    if cancel and _NO_FAULT.search(value):
        findings['R06'] = {
            'evidence': value[max(0, cancel.start()-50):min(len(value), cancel.end()+80)][:180],
            'facts': {'customer_can_cancel': True, 'without_liability': True},
            'note': '本地提取：客户可无责任取消、撤销或调整订单/预测',
        }
    indirect = _INDIRECT_LOSS.search(value)
    if indirect and _SUPPLIER_LIABILITY.search(value):
        findings['R12'] = {
            'evidence': value[max(0, indirect.start()-80):min(len(value), indirect.end()+100)][:180],
            'facts': {'undertakes_indirect_loss': True},
            'note': '本地提取：我方承担间接损失，违反无金额合同的赔偿底线',
        }
    return findings
