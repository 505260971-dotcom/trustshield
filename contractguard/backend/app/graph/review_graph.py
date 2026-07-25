import os, json, concurrent.futures, re, difflib
from typing import TypedDict, List, Dict, Any, Annotated
from langgraph.graph import StateGraph, START, END

from ..config import ENABLE_MASKING, SMART_MASK, MASK_LLM_MODEL
from ..services.llm import get_llm, invoke_remote
from ..services.rules import RULES, RULE_BY_ID
from ..services.parse import parse_contract
from ..services.mask import mask_clauses
from ..services.smart_mask import mask_clauses_smart, restore_report, restore_text
from ..services.numerics import extract_numerics
from ..services.deterministic_rules import applicable_rule_ids, assess_clause
from langchain_core.messages import HumanMessage, SystemMessage

GLOBAL_DIMS = [r['dim'] for r in RULES]
SEVERITY = {'R01':'high','R02':'high','R04':'high','R10':'high','R12':'high','R16':'high',
            'R03':'mid','R05':'mid','R09':'mid','R06':'mid','R07':'mid','R08':'mid',
            'R11':'mid','R13':'mid','R14':'mid','R15':'mid'}
LEVEL_TEXT = {'high':'阻断·需CEO/总监审批','mid':'需业务/总监确认','low':'通过（提示）'}
RULE2DIM = {r['id']: r['dim'] for r in RULES}
DIM2RULE = {r['dim']: r['id'] for r in RULES}

class State(TypedDict, total=False):
    path: str; filename: str
    business_type_hint: str
    clauses: List[Dict[str, Any]]; masked_clauses: List[Dict[str, Any]]; mapping: Dict[str, str]
    contract_fields: Dict[str, Any]; rule_hits: Dict[str, List[str]]
    rules: List[Dict[str, Any]]; rules_by_id: Dict[str, Dict[str, Any]]; rule2dim: Dict[str, str]; dim2rule: Dict[str, str]
    parent_report: Dict[str, Any]; review_clause_ids: set[str]; review_scope: Dict[str, Any]
    infer: List[Dict[str, Any]]; risks: List[Dict[str, Any]]; review_hints: List[Dict[str, Any]]; summary: Dict[str, Any]
    steps: Annotated[List[str], lambda a, b: a + b]

def node_ingest(state):
    r = parse_contract(state['path'])
    state['clauses'] = r['clauses']; state['filename'] = os.path.basename(state['path'])
    parent = state.get('parent_report') or {}
    previous = parent.get('clauses') or []
    if previous and state['clauses']:
        old_text = [_normalized_clause(item.get('text', '')) for item in previous]
        new_text = [_normalized_clause(item.get('text', '')) for item in state['clauses']]
        matcher = difflib.SequenceMatcher(a=old_text, b=new_text, autojunk=False)
        changed_indexes = set()
        unchanged_pairs = []
        for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
            if tag == 'equal':
                unchanged_pairs.extend((old_index, new_index) for old_index, new_index in zip(range(old_start, old_end), range(new_start, new_end)))
            else:
                changed_indexes.update(range(new_start, new_end))
                if tag == 'delete' and new_text:
                    changed_indexes.add(min(new_start, len(new_text) - 1))
        scope_indexes = set(changed_indexes)
        for index in list(changed_indexes):
            scope_indexes.update(range(max(0, index - 1), min(len(new_text), index + 2)))
        state['review_clause_ids'] = {state['clauses'][index]['id'] for index in scope_indexes}
        state['review_scope'] = {'mode': 'incremental', 'changed_clause_ids': [state['clauses'][index]['id'] for index in sorted(changed_indexes)],
                                 'context_clause_ids': [state['clauses'][index]['id'] for index in sorted(scope_indexes - changed_indexes)],
                                 'unchanged_pairs': unchanged_pairs, 'total_clauses': len(state['clauses'])}
        state.setdefault('steps', []).append(f'版本差异Agent: 变更 {len(changed_indexes)} 条，连同上下文复审 {len(scope_indexes)} / {len(state["clauses"])} 条')
    else:
        state['review_clause_ids'] = {item['id'] for item in state['clauses']}
        state['review_scope'] = {'mode': 'full', 'total_clauses': len(state['clauses'])}
    state.setdefault('steps', []).append(f'文档解析Agent: 切分 {len(r["clauses"])} 条条款')
    return state

def _normalized_clause(text):
    return re.sub(r'\s+', '', (text or '')).lower()

def node_mask(state):
    if not (ENABLE_MASKING and state.get('clauses')):
        state['masked_clauses'] = state['clauses']; state['mapping'] = {}
        state['steps'].append('脱敏Agent: 跳过（未启用）')
        return state
    if SMART_MASK:
        m, mp = mask_clauses_smart(state['clauses'])
        state['masked_clauses'] = m; state['mapping'] = mp
        mode = '正则+本地8B' if MASK_LLM_MODEL else '正则回退（未配置本地8B）'
        state['steps'].append(f'本地隐私脱敏Agent({mode}): 脱敏 {len(mp)} 个敏感实体')
    else:
        m, mp = mask_clauses(state['clauses'])
        state['masked_clauses'] = m; state['mapping'] = mp
        state['steps'].append(f'脱敏Agent(正则): 脱敏 {len(mp)} 个敏感实体')
    return state

FIELD_PROMPT = '你是合同字段抽取子Agent。我方=乙方(供方/制造方东江集团)。文本中<MASK-AMOUNT-...>代表已脱敏金额，识别总合同金额时输出该占位符到total_amount_ref，不要猜测原始金额。只输出JSON: {"business_type":"TKM|TKP|模塑一体|一般","our_party":"甲方|乙方","parties":{"甲方":"","乙方":""},"total_amount_ref":"<MASK-...>|null","currency":"USD|HKD|RMB|EUR|...","validity_years":number_or_null,"payment_terms":"简述付款节点"}'

def _restore_field_values(value, mapping):
    if isinstance(value, str):
        return restore_text(value, mapping)
    if isinstance(value, list):
        return [_restore_field_values(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: _restore_field_values(item, mapping) for key, item in value.items()}
    return value

def _hydrate_masked_amount(fields, mapping):
    """强模型只返回金额占位符；本地再从映射表恢复数值与币种，原始金额不进入 Prompt。"""
    ref = fields.get('total_amount_ref') or fields.get('total_amount')
    raw = mapping.get(ref, ref) if isinstance(ref, str) else ref
    if not isinstance(raw, str):
        return fields
    amounts = extract_numerics(raw).get('amounts', [])
    if amounts:
        fields['total_amount'] = amounts[0]['value']
        fields['currency'] = fields.get('currency') or amounts[0]['currency']
    return fields

def node_extract_fields(state):
    llm = get_llm(json_mode=True, max_tokens=900, temperature=0, timeout=20, max_retries=0)
    sample = '\n'.join(c.get('text_masked', '')[:160] for c in state['masked_clauses'][:30])
    user = (state['masked_clauses'][0].get('text_masked', '')[:40] if state['masked_clauses'] else '') + '\n' + sample
    try:
        msg = invoke_remote(llm, [SystemMessage(content=FIELD_PROMPT), HumanMessage(content=user)], completion_tokens=900)
        f = json.loads(msg.content)
    except Exception:
        f = {}
    # 字段只在强模型返回后于本地恢复，保证报告中的合同主体和金额可追溯。
    mapping = state.get('mapping', {})
    state['contract_fields'] = _restore_field_values(_hydrate_masked_amount(f, mapping), mapping)
    if state.get('business_type_hint'):
        state['contract_fields']['business_type'] = state['business_type_hint']
    state['steps'].append(f'字段抽取Agent: 我方={f.get("our_party")} 业务={f.get("business_type")} 有效期={f.get("validity_years")}')
    return state

def node_retrieve(state):
    hits = {}
    business_type = state.get('contract_fields', {}).get('business_type', '一般')
    rules_by_id = state.get('rules_by_id', RULE_BY_ID)
    for c in state['masked_clauses']:
        if c['id'] not in state.get('review_clause_ids', set()):
            hits[c['id']] = []
            continue
        t = c.get('text_masked') or c.get('text')
        if not t or len(t) < 12:
            hits[c['id']] = []; continue
        local_ids = applicable_rule_ids(c.get('text') or t, business_type)
        # No candidate means no relevant legal topic — skip LLM for headings/boilerplate.
        if not local_ids:
            hits[c['id']] = []
            continue
        applicable = [rule_id for rule_id in local_ids if rule_id in rules_by_id and ('全部' in rules_by_id[rule_id].get('applies_to', ['全部']) or business_type in rules_by_id[rule_id].get('applies_to', ['全部']))]
        hits[c['id']] = applicable
    state['rule_hits'] = hits
    state['steps'].append(
        f'规则候选Agent(词法门控): 候选条款 {sum(1 for x in hits.values() if x)} / {len(hits)}，'
        f'已按业务类型过滤无关底限；不依赖向量检索'
    )
    return state

def _robust_json(text):
    if not text:
        return {}
    s = text.strip()
    try: return json.loads(s)
    except Exception: pass
    m = re.search(r'\{.*\}', s, re.S)
    if m:
        try: return json.loads(m.group(0))
        except Exception: pass
    return {}

def judge_one(llm, c, rule_ids, business_type, our_party, rules_by_id, rule2dim):
    requested_dims = list(dict.fromkeys(rule2dim.get(r) for r in rule_ids if r in rule2dim))
    txt_masked = c.get('text_masked') or c.get('text') or ''
    if not requested_dims:
        return {'clause_id': c['id'], 'page': c['start_page'], 'source_ref': c.get('source_ref', ''), 'requested': [], 'flags': {},
                'uncertain': {}, 'facts_by_dim': {}, 'evidence_map': {}, 'suggestion': '', 'skipped': True}
    rule_ctx = '\n'.join(f"- {rules_by_id[r]['id']} {rules_by_id[r]['baseline']}（{rules_by_id[r]['check']}）" for r in rule_ids if r in rules_by_id)
    dims_str = ', '.join(requested_dims)
    sys = ('你是销售合同条款语义与事实抽取子Agent。我方立场=' + str(our_party) + '（东江集团，供方/制造方）。'
           '请理解条款的主体、义务、时间触发点、条件、否定、例外和审批，不允许按关键词机械判断。'
           '仅输出JSON：'
           '{"assessments":{<维度名>:{"status":"risk|clear|uncertain","evidence":"原文片段<=80字",'
           '"reason":"简短判断依据","confidence":0到1,"facts":{'
           '"term_days":number_or_null,"payment_trigger":"delivery|acceptance|invoice|other|unknown",'
           '"delivery_payment_ratio":number_or_null,"validity_years":number_or_null,'
           '"penalty_ratio":number_or_null,"has_fixed_contract_amount":true|false|null,'
           '"undertakes_indirect_loss":true|false|null,"approval_role":"CEO|总监|none|unknown"}}},'
           '"suggestion":"<=120字修改建议"}。'
           '只返回 status 为 risk 或 uncertain 的维度；明确不适用的维度可以省略。无法确定时用 uncertain，禁止猜测。')
    user = (f'业务类型:{business_type}\n我方:{our_party}\n相关底限条款:\n{rule_ctx}\n'
            f'需评估维度: {dims_str}\n\n条款#{c["id"]} (页{c["start_page"]}) 脱敏后文本:\n{txt_masked[:1800]}')
    data = {}
    for attempt in range(1):
        try:
            r = invoke_remote(llm, [SystemMessage(content=sys), HumanMessage(content=user)], completion_tokens=1500)
            data = _robust_json(r.content)
            assessments = data.get('assessments') or data.get('flags')
            if isinstance(assessments, dict) and assessments:
                break
        except Exception as e:
            data = {'_error': str(e)}
    # 归一化
    assessments = data.get('assessments', data.get('flags', {})) if isinstance(data, dict) else {}
    flags = {}; uncertain = {}; evidence_map = {}; facts_by_dim = {}
    for d in requested_dims:
        v = assessments.get(d) if isinstance(assessments, dict) else None
        if isinstance(v, dict):
            status = v.get('status')
            flags[d] = status == 'risk' or (status is None and bool(v.get('hit', False)))
            uncertain[d] = status == 'uncertain'
            if v.get('evidence'): evidence_map[d] = v.get('evidence')
            facts_by_dim[d] = v.get('facts') or {}
        else:
            flags[d] = bool(v)
            uncertain[d] = False
    suggestion = data.get('suggestion', '')
    inf = {'clause_id': c['id'], 'page': c['start_page'], 'source_ref': c.get('source_ref', ''), 'requested': requested_dims,
           'flags': flags, 'uncertain': uncertain, 'evidence_map': evidence_map,
           'facts_by_dim': facts_by_dim, 'suggestion': suggestion, 'rule_ids': list(rule_ids)}
    return inf

# Deterministic rules inspect every clause. Semantic LLM review is bounded for
# interactive latency; the window scales with contract size and prioritises high
# severity candidates first.
def _max_analyze(n_clauses: int) -> int:
    return min(32, max(16, (n_clauses or 0) // 3 or 16))

HIGH_RULES = {'R01', 'R02', 'R04', 'R10', 'R12', 'R16'}

def node_judge(state):
    llm = get_llm(json_mode=True, max_tokens=1500, temperature=0, timeout=60, max_retries=0)
    business_type = state.get('contract_fields', {}).get('business_type', '未知')
    our_party = state.get('contract_fields', {}).get('our_party', '乙方')
    clauses = state['masked_clauses']; hits = state['rule_hits']
    rules_by_id = state.get('rules_by_id', RULE_BY_ID); rule2dim = state.get('rule2dim', RULE2DIM)
    keywords=['违约','赔偿','连带','排他','VMI','JIT','质保','知识产权','取消','提价','承兑','付款','账期','有效期','交货','法律','诉讼','不可','独家','订单','库存','价格']
    def orderby(i):
        c=clauses[i]; h=hits.get(c['id'],[])
        high_hits = sum(1 for rid in h if rid in HIGH_RULES)
        kw=sum(1 for k in keywords if k in (c.get('text') or '').lower()) if hasattr(c,'get') else 0
        return (-high_hits, -len(h), -kw)
    idxs=sorted(range(len(clauses)), key=orderby)
    idxs = [i for i in idxs if hits.get(clauses[i]['id'])]
    analyze_cap = _max_analyze(len(clauses))
    if len(idxs) > analyze_cap:
        idxs = idxs[:analyze_cap]
    results = [None] * len(clauses)
    def attach_local(result, clause):
        local = assess_clause(clause.get('text') or '', business_type)
        for rule_id, finding in local.items():
            if rule_id not in rules_by_id:
                continue
            dim = rule2dim[rule_id]
            result.setdefault('flags', {})[dim] = True
            result.setdefault('uncertain', {})[dim] = False
            result.setdefault('evidence_map', {})[dim] = finding['evidence']
            result.setdefault('facts_by_dim', {})[dim] = finding['facts']
            result.setdefault('local_notes', {})[dim] = finding['note']
        if local:
            result['skipped'] = False
        return result
    def work(i):
        clause = clauses[i]
        local = assess_clause(clause.get('text') or '', business_type)
        remaining = [r for r in hits.get(clause['id'], []) if r not in local]
        result = judge_one(llm, clause, remaining, business_type, our_party, rules_by_id, rule2dim)
        return i, attach_local(result, clause)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for i, res in ex.map(work, idxs):
            results[i] = res
    # Deterministic policy checks cover every clause even when it is outside the
    # bounded semantic-review window.
    for i, clause in enumerate(clauses):
        if results[i] is not None:
            continue
        local_result = attach_local({'clause_id': clause['id'], 'page': clause['start_page'], 'source_ref': clause.get('source_ref', ''),
                                     'requested': [], 'flags': {}, 'uncertain': {}, 'facts_by_dim': {}, 'evidence_map': {},
                                     'suggestion': '', 'rule_ids': [], 'skipped': True}, clause)
        if not local_result.get('skipped'):
            results[i] = local_result
    state['infer'] = results
    analyzed = sum(1 for x in results if x and not x.get('skipped'))
    state['steps'].append(
        f'研判Agent(LLM×{analyzed}): 语义研判 {analyzed}/{len(results)} 条'
        f'（窗口≤{_max_analyze(len(clauses))}；确定性规则仍覆盖全部条款）'
    )
    return state

def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None

def _fact_note(dim, facts, local_note=''):
    """只校验强模型已抽取的同一法律事实，不再从原文中取最大数字猜测语义。"""
    if local_note:
        return (True, local_note)
    if dim == 'pay_after_delivery_days':
        days = _number(facts.get('term_days'))
        if days is not None:
            return (days > 90, f'强模型识别的付款账期 {days:g} 天 > 90 天底线')
    if dim == 'validity_years':
        years = _number(facts.get('validity_years'))
        if years is not None:
            return (years > 5, f'强模型识别的有效期 {years:g} 年 > 5 年上限')
    if dim == 'penalty_ratio':
        ratio = _number(facts.get('penalty_ratio'))
        if ratio is not None:
            return (ratio > 50, f'强模型识别的违约/赔偿比例 {ratio:g}% > 50%上限')
    if dim == 'penalty_no_amount' and facts.get('undertakes_indirect_loss') is True:
        return (True, '强模型识别为承担间接损失')
    return (True, '强模型语义研判命中；未抽取到可直接计算的数值事实')

def node_enforce(state):
    """规则引擎只消费强模型输出的结构化事实，不对原始文本做关键词裁决。"""
    items = []; review_hints = []
    rules_by_id = state.get('rules_by_id', RULE_BY_ID)
    dim2rule = state.get('dim2rule', DIM2RULE)
    clause_text = {clause.get('id'): clause.get('text', '') for clause in state.get('clauses', [])}
    for inf in state.get('infer', []) or []:
        if not inf or inf.get('skipped'):
            continue
        cid = inf['clause_id']; page = inf.get('page'); source_ref = inf.get('source_ref', '')
        evidence_map = inf.get('evidence_map', {})
        facts_by_dim = inf.get('facts_by_dim', {})
        local_notes = inf.get('local_notes', {})
        for dim, hit in (inf.get('flags') or {}).items():
            if not hit:
                continue
            rule_id = dim2rule.get(dim)
            if not rule_id:
                continue
            raw_text = clause_text.get(cid, '')
            if rule_id == 'R06' and not re.search(r'(?:买方|甲方|客户|purchaser|buyer|customer).{0,100}(?:取消|撤销|变更|调整|cancel|terminat)', raw_text, re.I):
                continue
            if rule_id == 'R12' and not (re.search(r'间接(?:之)?损失|indirect\s+loss', raw_text, re.I) and re.search(r'卖方|乙方|供应商|seller|supplier', raw_text, re.I)):
                continue
            if rule_id == 'R01' and not (re.search(r'付款|货款|payment', raw_text, re.I) and re.search(r'交付|交货|发货|delivery|shipment', raw_text, re.I) and re.search(r'\d{1,3}\s*[%％]', raw_text)):
                continue
            if rule_id == 'R13' and not (re.search(r'关联(?:公司|企业|方)|关系企业|affiliate|subsidiar', raw_text, re.I) and re.search(r'承担|义务|责任|约束|liable|obligation|responsibilit', raw_text, re.I)):
                continue
            if rule_id == 'R15' and not (re.search(r'不得提价|不可提价|原价(?:持续|供货)|price\s+(?:shall\s+)?not\s+increase', raw_text, re.I) and re.search(r'(?:[4-9]|[1-9]\d+)\s*(?:个?月|months?)', raw_text, re.I)):
                continue
            evidence = evidence_map.get(dim, '')
            facts = facts_by_dim.get(dim, {})
            applies, note = _fact_note(dim, facts, local_notes.get(dim, ''))
            if not applies:
                continue
            severity = rules_by_id[rule_id].get('severity', SEVERITY.get(rule_id, 'mid')) if evidence.strip() else 'low'
            approval_role = rules_by_id[rule_id].get('approval_role', '')
            items.append({'clause_id': cid, 'page': page, 'source_ref': source_ref, 'rule_id': rule_id,
                          'rule_baseline': rules_by_id[rule_id]['baseline'],
                          'dim': dim, 'evidence': evidence, 'suggestion': inf.get('suggestion', ''),
                          'severity': severity, 'level': LEVEL_TEXT[severity], 'numeric_note': note,
                          'facts': facts, 'approval_required': approval_role,
                          'decision': 'requires_approval' if approval_role else 'risk_confirmed',
                          'decision_source': 'deterministic_policy_rule' if local_notes.get(dim) else 'strong_llm+policy_rule'})
        for dim, is_uncertain in (inf.get('uncertain') or {}).items():
            if not is_uncertain:
                continue
            rule_id = dim2rule.get(dim)
            if not rule_id:
                continue
            review_hints.append({'clause_id': cid, 'page': page, 'source_ref': source_ref, 'rule_id': rule_id,
                                 'rule_baseline': rules_by_id[rule_id]['baseline'], 'dim': dim,
                                 'evidence': evidence_map.get(dim, ''), 'suggestion': '请由法务核对原文、附件及审批记录后确认。',
                                 'severity': 'mid', 'level': '待人工确认',
                                 'numeric_note': '强模型无法确认主体、条件、否定或审批例外',
                                 'facts': facts_by_dim.get(dim, {}), 'approval_required': rules_by_id[rule_id].get('approval_role', ''),
                                 'decision': 'needs_human_confirmation',
                                 'decision_source': 'strong_llm_uncertain'})
    # Exact unchanged clauses do not need another model call. Carry their prior
    # findings into the new version so the comparison distinguishes persistent
    # risk from a genuinely resolved clause.
    if state.get('review_scope', {}).get('mode') == 'incremental':
        parent = state.get('parent_report') or {}
        old_clauses = parent.get('clauses') or []
        new_clauses = state.get('clauses') or []
        old_to_new = {old_clauses[old_index].get('id'): new_clauses[new_index].get('id')
                      for old_index, new_index in state['review_scope'].get('unchanged_pairs', [])
                      if old_index < len(old_clauses) and new_index < len(new_clauses)}
        for prior in parent.get('risks', []) or []:
            new_clause_id = old_to_new.get(prior.get('clause_id'))
            if not new_clause_id:
                continue
            carried = dict(prior)
            carried['clause_id'] = new_clause_id
            carried['decision_source'] = 'carried_forward_unchanged_clause'
            carried['finding_id'] = None
            carried['action_status'] = 'carried_forward'
            items.append(carried)
    seen = set(); dedup = []
    for it in items:
        k = (it['clause_id'], it['rule_id'])
        if k in seen: continue
        seen.add(k); dedup.append(it)
    order = {'high': 0, 'mid': 1, 'low': 2}
    dedup.sort(key=lambda x: (order.get(x['severity'], 9), x.get('page', 0), x['clause_id']))
    state['risks'] = dedup
    state['review_hints'] = review_hints
    state['steps'].append(f'规则引擎Agent: 命中 {len(dedup)} 条风险(高{sum(1 for x in dedup if x["severity"]=="high")} 中{sum(1 for x in dedup if x["severity"]=="mid")}低{sum(1 for x in dedup if x["severity"]=="low")})；待人工确认 {len(review_hints)} 条')
    return state


def node_summary(state):
    rs = state['risks']
    high = sum(1 for r in rs if r['severity'] == 'high')
    mid = sum(1 for r in rs if r['severity'] == 'mid')
    low = sum(1 for r in rs if r['severity'] == 'low')
    overall = '阻断·需CEO/总监审批' if high else ('需重点确认' if mid else '通过')
    state['summary'] = {'n_clauses': len(state['clauses']), 'n_risks': len(rs),
                        'high': high, 'mid': mid, 'low': low, 'overall_level': overall,
                        'contract_fields': state.get('contract_fields', {}),
                        'n_needs_review': len(state.get('review_hints', []))}
    state['steps'].append(f'汇总结论Agent: 总体 {overall}')
    return state

def build_graph():
    g = StateGraph(State)
    for n, f in [('ingest', node_ingest), ('mask', node_mask), ('extract_fields', node_extract_fields),
                 ('retrieve', node_retrieve), ('judge', node_judge), ('enforce', node_enforce), ('summary', node_summary)]:
        g.add_node(n, f)
    g.add_edge(START, 'ingest'); g.add_edge('ingest', 'mask'); g.add_edge('mask', 'extract_fields')
    g.add_edge('extract_fields', 'retrieve'); g.add_edge('retrieve', 'judge')
    g.add_edge('judge', 'enforce'); g.add_edge('enforce', 'summary'); g.add_edge('summary', END)
    return g.compile()

def run_review(path, on_step=None, business_type_hint='', rule_snapshot=None, parent_report=None):
    app = build_graph()
    rules = rule_snapshot or RULES
    rules_by_id = {rule['id']: rule for rule in rules}
    state = {'path': path, 'steps': [], 'business_type_hint': business_type_hint, 'rules': rules,
             'rules_by_id': rules_by_id, 'rule2dim': {rule['id']: rule['dim'] for rule in rules},
             'dim2rule': {rule['dim']: rule['id'] for rule in rules}, 'parent_report': parent_report or {}}
    seen = []; last = {}
    for ev in app.stream(state, {'recursion_limit': 40}, stream_mode='values'):
        new = ev.get('steps', [])
        for s in new[len(seed := seen):]:
            seen.append(s)
            if on_step: on_step(s)
        last = ev
    return assemble_report(last, path)

def assemble_report(state, path):
    report = {'filename': state.get('filename'), 'summary': state.get('summary', {}),
            'contract_fields': state.get('contract_fields', {}),
            'clauses': state.get('clauses', []), 'risks': state.get('risks', []),
            'review_hints': state.get('review_hints', []), 'steps': state.get('steps', []),
            'review_scope': state.get('review_scope', {}),
            'masked_entities': len(state.get('mapping', {})),
            '_mask_mapping': state.get('mapping', {})}
    report = restore_report(report, state.get('mapping', {}))
    return report
