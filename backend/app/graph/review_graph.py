import os, json, re, difflib
from typing import TypedDict, List, Dict, Any, Annotated
from langgraph.graph import StateGraph, START, END

from ..config import ENABLE_MASKING, SMART_MASK, MASK_LLM_MODEL, masking_model_mode
from ..services.llm import get_llm, invoke_remote
from ..services.rules import RULES, RULE_BY_ID
from ..services.parse import parse_contract
from ..services.mask import mask_clauses
from ..services.smart_mask import mask_clauses_smart, restore_report, restore_text
from ..services.numerics import extract_numerics
from ..services.deterministic_rules import assess_clause
from ..services.contract_react_agent import run_contract_react_audit
from langchain_core.messages import HumanMessage, SystemMessage

GLOBAL_DIMS = [r['dim'] for r in RULES]
SEVERITY = {'R01':'high','R02':'high','R04':'high','R10':'high','R12':'high','R16':'high',
            'R03':'mid','R05':'mid','R09':'mid','R06':'mid','R07':'mid','R08':'mid',
            'R11':'mid','R13':'mid','R14':'mid','R15':'mid'}
LEVEL_TEXT = {'high':'阻断·须财务审批主管或集团财务总监审批','mid':'需业务确认或财务审批主管复核','low':'通过（提示）'}
RULE2DIM = {r['id']: r['dim'] for r in RULES}
DIM2RULE = {r['dim']: r['id'] for r in RULES}

class State(TypedDict, total=False):
    path: str; filename: str
    business_type_hint: str
    clauses: List[Dict[str, Any]]; masked_clauses: List[Dict[str, Any]]; mapping: Dict[str, str]
    contract_fields: Dict[str, Any]
    rules: List[Dict[str, Any]]; rules_by_id: Dict[str, Dict[str, Any]]; rule2dim: Dict[str, str]; dim2rule: Dict[str, str]
    parent_report: Dict[str, Any]; review_clause_ids: set[str]; review_scope: Dict[str, Any]
    infer: List[Dict[str, Any]]; risks: List[Dict[str, Any]]; review_hints: List[Dict[str, Any]]; summary: Dict[str, Any]
    credit_snapshot: Dict[str, Any]
    agent_audit: Dict[str, Any]; boundary_checks: List[Dict[str, Any]]; agent_observations: List[Dict[str, Any]]
    semantic_llm_attempts: int; semantic_llm_successes: int
    # Nodes mutate and return the complete sequential state. A reducer here
    # would concatenate every historical step list again on every node.
    steps: List[str]

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
        state.setdefault('steps', []).append(f'版本差异检查：变更 {len(changed_indexes)} 条，连同上下文复审 {len(scope_indexes)} / {len(state["clauses"])} 条')
    else:
        state['review_clause_ids'] = {item['id'] for item in state['clauses']}
        state['review_scope'] = {'mode': 'full', 'total_clauses': len(state['clauses'])}
    state.setdefault('steps', []).append(f'文档解析：切分 {len(r["clauses"])} 条条款')
    return state

def _normalized_clause(text):
    return re.sub(r'\s+', '', (text or '')).lower()

def node_mask(state):
    if not (ENABLE_MASKING and state.get('clauses')):
        state['masked_clauses'] = state['clauses']; state['mapping'] = {}
        state['steps'].append('合同脱敏：跳过（未启用）')
        return state
    if SMART_MASK:
        m, mp = mask_clauses_smart(state['clauses'])
        state['masked_clauses'] = m; state['mapping'] = mp
        mode = {'local_ollama': '正则+本地专用模型', 'remote_proxy': '正则+专用模型（远端替代）',
                'regex_only': '正则回退（未配置专用模型）'}[masking_model_mode()]
        state['steps'].append(f'合同脱敏（{mode}）：已保护 {len(mp)} 个敏感信息')
    else:
        m, mp = mask_clauses(state['clauses'])
        state['masked_clauses'] = m; state['mapping'] = mp
        state['steps'].append(f'合同脱敏（正则）：已保护 {len(mp)} 个敏感信息')
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


def _local_contract_fields(clauses):
    """Best-effort local fields used only when semantic LLM is unavailable."""
    text = '\n'.join(str(item.get('text') or '') for item in clauses or [])
    parties = {}
    for label in ('甲方', '乙方'):
        # DOCX templates commonly write labels as “甲方（买方）：…”.  The
        # semantic model may return syntactically valid but incomplete JSON, so
        # this local parser must recognise both the short and qualified forms.
        found = re.search(rf'{label}(?:\s*[（(][^）)]{{0,40}}[）)])?\s*[：:]\s*([^\n\r；;]{{2,120}})', text)
        if found:
            value = found.group(1).strip()
            # The next party label is a stronger delimiter than punctuation in
            # one-line TXT acceptance fixtures and simple purchase orders.
            value = re.split(
                r'\s*(?:(?:甲方|乙方)(?:\s*[（(][^）)]{0,40}[）)])?|项目名称|合同业务类型|合同总金额|合同编号|修订日期)\s*[：:]',
                value, maxsplit=1,
            )[0].strip(' ，,。')
            parties[label] = value
    return {'our_party': '乙方', 'parties': parties}

def node_extract_fields(state):
    sample = '\n'.join(c.get('text_masked', '')[:160] for c in state['masked_clauses'][:30])
    user = (state['masked_clauses'][0].get('text_masked', '')[:40] if state['masked_clauses'] else '') + '\n' + sample
    try:
        llm = get_llm(json_mode=True, max_tokens=900, temperature=0, timeout=20, max_retries=0)
        msg = invoke_remote(llm, [SystemMessage(content=FIELD_PROMPT), HumanMessage(content=user)], completion_tokens=900)
        f = json.loads(msg.content)
    except Exception:
        f = _local_contract_fields(state.get('clauses') or [])
    # A valid JSON response is not necessarily a complete extraction.  Preserve
    # the model's richer fields, but fail closed only after the deterministic
    # parser has had a chance to backfill an explicitly written contract party.
    if not isinstance(f, dict):
        f = {}
    local_fields = _local_contract_fields(state.get('clauses') or [])
    model_parties = f.get('parties') if isinstance(f.get('parties'), dict) else {}
    local_parties = local_fields.get('parties') or {}
    f['parties'] = {**local_parties, **{key: value for key, value in model_parties.items() if str(value or '').strip()}}
    if not f.get('our_party'):
        f['our_party'] = local_fields.get('our_party') or '乙方'
    # 字段只在强模型返回后于本地恢复，保证报告中的合同主体和金额可追溯。
    mapping = state.get('mapping', {})
    state['contract_fields'] = _restore_field_values(_hydrate_masked_amount(f, mapping), mapping)
    if state.get('business_type_hint'):
        state['contract_fields']['business_type'] = state['business_type_hint']
    state['steps'].append(f'合同信息提取：我方={f.get("our_party")} 业务={f.get("business_type")} 有效期={f.get("validity_years")}')
    return state


def _claims_to_infer(claims, mapping):
    """Agent-verified risk claims -> enforce's per-clause infer structure."""
    infer: Dict[str, Dict[str, Any]] = {}
    for claim in claims or []:
        cid = str(claim.get('clause_id') or '')
        if claim.get('type') != 'clause_risk' or not cid:
            continue
        inf = infer.setdefault(cid, {'clause_id': cid, 'page': claim.get('page'), 'source_ref': claim.get('source_ref', ''),
                                     'requested': [], 'flags': {}, 'uncertain': {}, 'evidence_map': {}, 'facts_by_dim': {},
                                     'suggestion': '', 'rule_ids': [], 'skipped': False,
                                     'model_attempted': True, 'model_succeeded': True})
        dim = str(claim.get('dim') or '')
        rule_id = str(claim.get('rule_id') or '')
        inf['rule_ids'].append(rule_id)
        if claim.get('status') == 'risk':
            inf['flags'][dim] = True
        else:
            inf['uncertain'][dim] = True
        inf['evidence_map'][dim] = restore_text(str(claim.get('evidence_quote') or ''), mapping)
        inf['facts_by_dim'][dim] = claim.get('facts') or {}
    return infer


def node_react_audit(state):
    """RAG + ReAct clause audit; deterministic local rules still cover every clause.

    The Agent searches and reads masked clauses, inspects the rule catalog and
    the customer's approved credit boundary, and submits source-bound Claims.
    If the Agent is unavailable it fails closed; the deterministic local rules
    below still produce their auditable findings for every clause.
    """
    clauses = state.get('masked_clauses') or []
    business_type = state.get('contract_fields', {}).get('business_type', '未知')
    our_party = state.get('contract_fields', {}).get('our_party', '乙方')
    rules_by_id = state.get('rules_by_id', RULE_BY_ID)
    mapping = state.get('mapping') or {}
    approval_history = [{'severity': item.get('severity'), 'rule_id': item.get('rule_id'),
                         'summary': str(item.get('suggestion') or '')[:300], 'action_status': item.get('action_status') or 'prior'}
                        for item in (state.get('parent_report') or {}).get('risks') or []][:12]
    agent: Dict[str, Any] = {'status': 'skipped', 'claims': [], 'trace': [], 'boundary_checks': [],
                             'observations': [], 'material_requests': []}
    try:
        agent = run_contract_react_audit(clauses, rules_by_id, state.get('credit_snapshot'), business_type, our_party,
                                         approval_history=approval_history, mask_mapping=mapping,
                                         on_event=state.get('on_event'))
    except Exception as exc:
        agent = {'status': 'execution_failed', 'reason': f'{type(exc).__name__}: {str(exc)[:160]}', 'claims': [], 'trace': [],
                 'boundary_checks': [], 'observations': [], 'material_requests': [str(exc)[:300]]}
    # The mapping itself never enters the persisted report; quotes are restored
    # to the original text before the audit object is stored.
    for claim in agent.get('claims') or []:
        claim['evidence_quote'] = restore_text(str(claim.get('evidence_quote') or ''), mapping)
    agent.pop('mask_mapping', None)
    infer = _claims_to_infer(agent.get('claims') or [], mapping)
    # Deterministic local rules cover every clause regardless of the Agent.
    for clause in clauses:
        cid = clause.get('id')
        if cid in infer:
            continue
        local = assess_clause(clause.get('text') or '', business_type)
        if not local:
            continue
        inf = {'clause_id': cid, 'page': clause.get('start_page'), 'source_ref': clause.get('source_ref', ''),
               'requested': [], 'flags': {}, 'uncertain': {}, 'evidence_map': {}, 'facts_by_dim': {},
               'suggestion': '', 'rule_ids': [], 'skipped': False, 'local_notes': {}}
        for rule_id, finding in local.items():
            if rule_id not in rules_by_id:
                continue
            dim = rules_by_id[rule_id]['dim']
            inf['flags'][dim] = True
            inf['evidence_map'][dim] = finding['evidence']
            inf['facts_by_dim'][dim] = finding['facts']
            inf['local_notes'][dim] = finding['note']
            inf['rule_ids'].append(rule_id)
        infer[cid] = inf
    state['infer'] = [infer[cid] for cid in infer]
    state['agent_audit'] = agent
    boundary = agent.get('boundary_checks') or []
    for check in boundary:
        check['evidence_quote'] = restore_text(str(check.get('evidence_quote') or ''), mapping)
    state['boundary_checks'] = boundary
    state['agent_observations'] = [{'category': item.get('category'), 'summary': restore_text(str(item.get('summary') or ''), mapping),
                                    'source_ref': item.get('source_ref', '')} for item in agent.get('observations') or []]
    attempted = agent.get('status') in {'ready_for_policy', 'not_assessable', 'execution_failed'}
    state['semantic_llm_attempts'] = 1 if attempted else 0
    state['semantic_llm_successes'] = 1 if agent.get('status') == 'ready_for_policy' else 0
    local_covered = sum(1 for inf in state['infer'] if inf.get('local_notes'))
    state['steps'].append(
        f'Agent 审查：{agent.get("status")}；核验事实 {len(agent.get("claims") or [])} 条，'
        f'授信边界对照 {len(boundary)} 项，本地规则兜底 {local_covered} 条'
    )
    return state


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None

def _fact_note(dim, facts, local_note=''):
    """只校验 Agent 已抽取的同一法律事实，不再从原文中取最大数字猜测语义。"""
    if local_note:
        return (True, local_note)
    if dim == 'pay_after_delivery_days':
        days = _number(facts.get('term_days'))
        if days is not None:
            return (days > 90, f'Agent 识别的付款账期为 {days:g} 天，超过 90 天底线')
    if dim == 'validity_years':
        years = _number(facts.get('validity_years'))
        if years is not None:
            return (years > 5, f'Agent 识别的有效期为 {years:g} 年，超过 5 年上限')
    if dim == 'penalty_ratio':
        ratio = _number(facts.get('penalty_ratio'))
        if ratio is not None:
            return (ratio > 50, f'Agent 识别的违约/赔偿比例为 {ratio:g}%，超过 50% 上限')
    if dim == 'penalty_no_amount' and facts.get('undertakes_indirect_loss') is True:
        return (True, 'Agent 识别为承担间接损失')
    return (True, 'Agent 已识别出相关风险，但未提取到可直接计算的数值事实')

def node_enforce(state):
    """规则引擎只消费 Agent 输出的结构化事实，不对原始文本做关键词裁决。"""
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
                          'decision_source': 'deterministic_policy_rule' if local_notes.get(dim) else 'react_agent+policy_rule'})
        for dim, is_uncertain in (inf.get('uncertain') or {}).items():
            if not is_uncertain:
                continue
            rule_id = dim2rule.get(dim)
            if not rule_id:
                continue
            review_hints.append({'clause_id': cid, 'page': page, 'source_ref': source_ref, 'rule_id': rule_id,
                                 'rule_baseline': rules_by_id[rule_id]['baseline'], 'dim': dim,
                                 'evidence': evidence_map.get(dim, ''), 'suggestion': '请由信用审核专员核对原文、附件及审批记录后确认。',
                                 'severity': 'mid', 'level': '待人工确认',
                                 'numeric_note': 'Agent 无法确认主体、适用条件、否定条款或审批例外',
                                 'facts': facts_by_dim.get(dim, {}), 'approval_required': rules_by_id[rule_id].get('approval_role', ''),
                                 'decision': 'needs_human_confirmation',
                                 'decision_source': 'react_agent_uncertain'})
    # Agent-verified credit-boundary comparisons become approval-required risks.
    # The comparison itself is deterministic local arithmetic; the Agent only
    # extracted the contract-side facts.
    boundary_approval = {'acceptance_bill': 'admin', 'vmi_jit': 'director'}
    for check in state.get('boundary_checks') or []:
        if check.get('verdict') in {'within', ''}:
            continue
        dimension = str(check.get('dimension') or '')
        message = str(check.get('message') or '')[:200]
        items.append({'clause_id': str(check.get('clause_id') or ''), 'page': 0, 'source_ref': '',
                      'rule_id': 'B01', 'rule_baseline': '合同条款不得超过客户已批准授信边界',
                      'dim': dimension, 'evidence': str(check.get('evidence_quote') or '')[:500],
                      'suggestion': message, 'severity': 'high', 'level': LEVEL_TEXT['high'],
                      'numeric_note': message,
                      'facts': {'contract_value': check.get('contract_value'), 'boundary_value': check.get('boundary_value')},
                      'approval_required': boundary_approval.get(dimension, 'director'),
                      'decision': 'requires_approval', 'decision_source': 'credit_boundary_check'})
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
        k = (it['clause_id'], it['rule_id'], it['dim'])
        if k in seen: continue
        seen.add(k); dedup.append(it)
    order = {'high': 0, 'mid': 1, 'low': 2}
    dedup.sort(key=lambda x: (order.get(x['severity'], 9), x.get('page', 0), x['clause_id']))
    state['risks'] = dedup
    state['review_hints'] = review_hints
    state['steps'].append(f'规则检查：命中 {len(dedup)} 条风险（高{sum(1 for x in dedup if x["severity"]=="high")} 中{sum(1 for x in dedup if x["severity"]=="mid")} 低{sum(1 for x in dedup if x["severity"]=="low")}）；待人工确认 {len(review_hints)} 条')
    return state


def node_summary(state):
    rs = state['risks']
    high = sum(1 for r in rs if r['severity'] == 'high')
    mid = sum(1 for r in rs if r['severity'] == 'mid')
    low = sum(1 for r in rs if r['severity'] == 'low')
    overall = '阻断·须财务审批主管或集团财务总监审批' if high else ('需重点确认' if mid else '通过')
    state['summary'] = {'n_clauses': len(state['clauses']), 'n_risks': len(rs),
                        'high': high, 'mid': mid, 'low': low, 'overall_level': overall,
                        'contract_fields': state.get('contract_fields', {}),
                        'n_needs_review': len(state.get('review_hints', [])),
                        'semantic_llm_attempts': state.get('semantic_llm_attempts', 0),
                        'semantic_llm_successes': state.get('semantic_llm_successes', 0)}
    state['steps'].append(f'汇总结论：总体 {overall}')
    return state

def build_graph():
    g = StateGraph(State)
    for n, f in [('ingest', node_ingest), ('mask', node_mask), ('extract_fields', node_extract_fields),
                 ('react_audit', node_react_audit), ('enforce', node_enforce), ('summary', node_summary)]:
        g.add_node(n, f)
    g.add_edge(START, 'ingest'); g.add_edge('ingest', 'mask'); g.add_edge('mask', 'extract_fields')
    g.add_edge('extract_fields', 'react_audit'); g.add_edge('react_audit', 'enforce')
    g.add_edge('enforce', 'summary'); g.add_edge('summary', END)
    return g.compile()

def _review_event_sources(state):
    """Expose only source-bound snippets for the live reviewer workspace."""
    sources = {}
    for item in state.get('infer') or []:
        if not item:
            continue
        for evidence in (item.get('evidence_map') or {}).values():
            quote = str(evidence or '').strip()
            key = f"{item.get('clause_id') or ''}:{item.get('source_ref') or ''}:{quote}"
            sources[key] = {
                'clause_id': item.get('clause_id'), 'source_ref': item.get('source_ref', ''),
                'page': item.get('page'), 'evidence_quote': quote[:500],
            }
    for risk in state.get('risks') or []:
        quote = str(risk.get('evidence') or '').strip()
        key = f"{risk.get('clause_id') or ''}:{risk.get('source_ref') or ''}:{quote}"
        sources[key] = {
            'clause_id': risk.get('clause_id'), 'source_ref': risk.get('source_ref', ''),
            'page': risk.get('page'), 'evidence_quote': quote[:500], 'rule_id': risk.get('rule_id', ''),
        }
    return list(sources.values())[-120:]


def run_review(path, on_step=None, business_type_hint='', rule_snapshot=None, parent_report=None, on_event=None, credit_snapshot=None):
    app = build_graph()
    rules = rule_snapshot or RULES
    rules_by_id = {rule['id']: rule for rule in rules}
    state = {'path': path, 'steps': [], 'business_type_hint': business_type_hint, 'rules': rules,
             'rules_by_id': rules_by_id, 'rule2dim': {rule['id']: rule['dim'] for rule in rules},
             'dim2rule': {rule['dim']: rule['id'] for rule in rules}, 'parent_report': parent_report or {},
             'credit_snapshot': credit_snapshot or {}, 'on_event': on_event}
    seen = []; last = {}
    for ev in app.stream(state, {'recursion_limit': 40}, stream_mode='values'):
        new = ev.get('steps', [])
        for s in new[len(seen):]:
            seen.append(s)
            if on_step: on_step(s)
            if on_event:
                try:
                    on_event({'type': 'agent_update', 'message': s, 'step_index': len(seen),
                              'clause_count': len(ev.get('clauses') or []),
                              'reviewed_count': sum(1 for item in ev.get('infer') or [] if item and not item.get('skipped')),
                              'risk_count': len(ev.get('risks') or []),
                              'sources': _review_event_sources(ev)})
                except Exception:
                    pass
        last = ev
    return assemble_report(last, path)

def assemble_report(state, path):
    report = {'filename': state.get('filename'), 'summary': state.get('summary', {}),
            'contract_fields': state.get('contract_fields', {}),
            'clauses': state.get('clauses', []), 'risks': state.get('risks', []),
            'review_hints': state.get('review_hints', []), 'steps': state.get('steps', []),
            'review_scope': state.get('review_scope', {}),
            'agent_audit': state.get('agent_audit') or {'status': 'skipped'},
            'boundary_checks': state.get('boundary_checks') or [],
            'agent_observations': state.get('agent_observations') or [],
            'masked_entities': len(state.get('mapping', {})),
            '_mask_mapping': state.get('mapping', {})}
    report = restore_report(report, state.get('mapping', {}))
    return report
