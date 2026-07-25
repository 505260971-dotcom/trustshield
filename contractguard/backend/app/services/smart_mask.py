import re, json
import httpx
from .llm import get_mask_llm, invoke_mask, estimate_tokens, clip_text_to_tokens
from ..config import (LOCAL_CONTEXT_TOKENS, MASK_LLM_API_BASE, MASK_LLM_MODEL,
                      MASK_LLM_NATIVE_OLLAMA, MASK_LLM_THINK, MASK_LLM_MAX_OUTPUT, MASK_LLM_DEEP_SCAN)
from langchain_core.messages import HumanMessage, SystemMessage
from . import mask as _mask

# 本地 8B 仅用于识别隐私实体。原始文本永不离开本机；后续强模型只获取脱敏文本。
MASK_PROMPT = ('你是本地合同隐私脱敏子Agent。识别给定合同文本中的敏感实体，只输出JSON: '
               '{"entities":[{"text":"原文片段","kind":"COMPANY|AMOUNT|TECH|PERSON|PHONE|ADDR"}]}。'
               '需识别供应商/客户及其子公司名称、价格和收付款金额、技术参数规格、个人姓名电话地址。'
               '禁止输出推理过程；每条text必须是原文精确片段且不超过30字。')

# The regular-expression layer already handles contacts, accounts, money,
# addresses and common company suffixes.  The 9B model is deliberately used
# only for the residual entities it is good at: technical identifiers and
# people/entity names in clauses that look like they contain such data.
_SEMANTIC_CANDIDATE = re.compile(
    r'(?i)(\b[A-Z]{2,}[\-_][A-Z0-9\-_]{2,}\b|\b(?:contact|signatory|representative)\s*[:：]?\s*[A-Za-z]{2,})')

def _needs_deep_scan(text):
    if not MASK_LLM_DEEP_SCAN: return False
    residual = re.sub(r'<MASK-[A-Z_]+-\d+>', '', text or '')
    return bool(_SEMANTIC_CANDIDATE.search(residual))

def _native_ollama_url():
    return MASK_LLM_API_BASE.rstrip('/').removesuffix('/v1') + '/api/chat'

def _native_mask_json(system, user, max_tokens):
    """Use Ollama's native API so `think:false` is actually honored.

    The OpenAI-compatible endpoint does not consistently expose Ollama's
    thinking switch.  Native chat also returns timing fields useful when
    profiling the slow local CPU path.
    """
    if not MASK_LLM_MODEL:
        return {}
    payload = {'model': MASK_LLM_MODEL, 'stream': False, 'think': MASK_LLM_THINK, 'format': 'json',
               'messages': [{'role':'system','content':system},{'role':'user','content':user}],
               'options': {'temperature': 0, 'num_predict': max_tokens}}
    with httpx.Client(timeout=180) as client:
        response = client.post(_native_ollama_url(), json=payload)
        response.raise_for_status()
        body = response.json(); text = ((body.get('message') or {}).get('content') or '').strip()
    return _decode_model_json(text)

def _decode_model_json(text):
    """Parse strict JSON, with a deliberately narrow repair for Qwen 4B.

    qwen3.5:4b sometimes emits a complete top-level array but omits the final
    `}` after `{"entities":[...]`.  We only repair that exact one-character
    truncation; arbitrary malformed model output remains rejected.
    """
    if not text: return {}
    candidates=[text.strip()]
    if candidates[0].startswith('{') and candidates[0].endswith(']'):
        candidates.append(candidates[0]+'}')
    match=re.search(r'\{.*\}',candidates[0],re.S)
    if match: candidates.append(match.group(0))
    for candidate in candidates:
        try:
            data=json.loads(candidate)
            if isinstance(data,dict): return data
        except Exception: pass
    return {}

def _mask_llm_json(system, user, max_tokens):
    if MASK_LLM_NATIVE_OLLAMA:
        return _native_mask_json(system, user, max_tokens)
    llm = get_mask_llm(max_tokens=max_tokens)
    if not llm: return {}
    r = invoke_mask(llm, [SystemMessage(content=system), HumanMessage(content=user)], completion_tokens=max_tokens)
    return _decode_model_json(r.content.strip())

def llm_mask_clause(text):
    """对单条条款做正则+本地 8B 脱敏；未配置本地模型时仅返回正则结果。"""
    mapping = {}
    # 1) 正则兜底(确定性、零成本):公司/电话/邮箱/金额/地址
    masked, mp = _mask.mask_text(text)
    mapping.update(mp)
    # 2) 本地 8B 识别额外敏感实体（子公司名、技术参数等正则难覆盖）
    try:
        if not MASK_LLM_MODEL:
            return masked, mapping
        # Do not ask the slow model to rediscover values that regex already
        # masked.  It receives only the residual short text.
        if not _needs_deep_scan(masked): return masked, mapping
        data = _mask_llm_json(MASK_PROMPT, masked[:700], MASK_LLM_MAX_OUTPUT)
        counter = len(mapping)
        for it in (data.get('entities') or []):
            t = (it.get('text') or '').strip()
            if not t or t in mapping.values(): continue
            # 跳过正则已脱敏的占位符
            if t.startswith('<MASK-'): continue
            counter += 1
            ph = f"<MASK-LLM-{counter}>"
            if ph not in masked and t in masked:
                masked = masked.replace(t, ph, 1)
                mapping[ph] = t
    except Exception:
        pass
    return masked, mapping

def llm_mask_batch(texts):
    """批量本地 8B 识别：原文只发送至本地模型，返回每条的敏感实体。"""
    # Receive regex-masked clauses: PII and money never enter this second
    # stage, while clauses without technical/person-name signals skip LLM.
    valid = [(i,t) for i,t in enumerate(texts) if t and len(t)>=20 and _needs_deep_scan(t)]
    if not valid:
        return {i: [] for i in range(len(texts))}
    results = {i: [] for i in range(len(texts))}
    # 预留输出和系统提示后，按输入 token 动态分包；不会出现固定 10 条文本挤爆 2k 上下文。
    output_tokens = min(MASK_LLM_MAX_OUTPUT, max(64, LOCAL_CONTEXT_TOKENS // 5))
    if not MASK_LLM_MODEL:
        return results

    sys = (MASK_PROMPT + ' 输入为多条款 JSON 数组（含 idx 和 text），输出 '
           '{"items":[{"idx":int,"entities":[...]}]}。')
    # Short residual fragments keep prompt evaluation cheap.  On CPU a large
    # batch is counterproductive because JSON output generation is ~5 tok/s.
    input_budget = max(128, LOCAL_CONTEXT_TOKENS - output_tokens - 128 - estimate_tokens(sys))
    batches = []; current = []; current_tokens = 0
    for index, text in valid:
        clipped = clip_text_to_tokens(text, min(320, max(96, input_budget // 2)))
        item = {'idx': index, 'text': clipped}
        item_tokens = estimate_tokens(json.dumps(item, ensure_ascii=False))
        if current and current_tokens + item_tokens > input_budget:
            batches.append(current)
            current = []; current_tokens = 0
        current.append(item)
        current_tokens += item_tokens
    if current:
        batches.append(current)

    for chunk in batches:
        user = json.dumps(chunk, ensure_ascii=False)
        try:
            data = _mask_llm_json(sys, user, output_tokens)
            for it in data.get('items', []):
                results[int(it.get('idx'))] = it.get('entities', []) or []
        except Exception:
            pass
    return results

def mask_clauses_smart(clauses):
    """批量智能脱敏:正则兜底(零成本)+ 本地 8B 批量识别(合并多条款)。
    返回 masked_clauses + 全局映射(placeholder->原文)。"""
    out = []; mapping_all = {}
    texts = [c.get('text') or '' for c in clauses]
    # 1) 正则兜底逐条(确定性)
    masked_texts = []; regex_maps = []
    for t in texts:
        mt, mp = _mask.mask_text(t)
        mt, mp = _mask.uniquify_mapping(mt, mp, mapping_all)
        masked_texts.append(mt); regex_maps.append(mp)
        mapping_all.update(mp)
    # 2) 原文仅送往本地 8B；DeepSeek 等强模型只会收到最终 masked_text。
    batch_entities = llm_mask_batch(masked_texts)
    for ci, c in enumerate(clauses):
        mt = masked_texts[ci]
        for ent in batch_entities.get(ci, []):
            t = (ent.get('text') or '').strip()
            if not t or len(t) > 30 or t in mapping_all.values(): continue
            if t.startswith('<MASK-'): continue
            if t in mt:
                ph = f"<MASK-LLM-{len(mapping_all)+1}>"
                mt = mt.replace(t, ph, 1)
                mapping_all[ph] = t
        out.append({**c, 'text': texts[ci], 'text_masked': mt})
    return out, mapping_all

def restore_text(text, mapping):
    if not text or not mapping: return text or ''
    for ph, orig in sorted(mapping.items(), key=lambda x: -len(x[0])):
        text = text.replace(ph, orig)
    return text

def restore_report(report, mapping):
    """把报告里的风险证据、建议和条款文本占位符还原为原文。"""
    m = mapping or {}
    if not m: return report
    for r in (report.get('risks') or []):
        for f in ('evidence','suggestion','rule_baseline'):
            if r.get(f): r[f] = restore_text(r[f], m)
    for c in (report.get('clauses') or []):
        if c.get('text'): c['text'] = restore_text(c['text'], m)
    return report
