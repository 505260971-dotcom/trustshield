# -*- coding: utf-8 -*-
"""Privacy-preserving multilingual contract translation.

Only reversible mask tokens are sent to the remote translation model.  The
mapping remains encrypted at rest and is used here, on the server, to restore
the completed translation for the authorized user.
"""
import json, re
from .llm import get_llm, invoke_remote
from .smart_mask import restore_text
from langchain_core.messages import HumanMessage, SystemMessage

LANG_NAME = {'en': '英语', 'vi': '越南语', 'ja': '日语', 'es': '西班牙语', 'zh': '中文'}

def _robust_json(text):
    if not text: return {}
    s = text.strip()
    try: return json.loads(s)
    except Exception: pass
    m = re.search(r'\{.*\}', s, re.S)
    if m:
        try: return json.loads(m.group(0))
        except Exception: pass
    return {}

def _mask_with_saved_mapping(text, mapping):
    """Rebuild the masked form from the encrypted review-time mapping.

    Reversing the mapping locally is intentional: the report shown to users is
    restored text, while the translation model must never receive that text.
    Longest values first avoids replacing a sensitive value inside a longer one.
    """
    masked=text or ''
    for token, value in sorted(mapping.items(), key=lambda item: len(str(item[1])), reverse=True):
        if isinstance(token,str) and isinstance(value,str) and value:
            masked=masked.replace(value,token)
    return masked

def translate_clauses(clauses, mapping, target_lang='en', on_step=None, limit=60):
    """Translate tokenized clauses and restore tokens only after model output."""
    name = LANG_NAME.get(target_lang, target_lang)
    picks = clauses[:limit]
    out = []
    batch = 7
    llm = get_llm(json_mode=True, max_tokens=3500, temperature=0.2)
    for i in range(0, len(picks), batch):
        chunk = picks[i:i+batch]
        sys = (f'你是合同翻译子Agent。把下列合同条款逐条翻译为{name},保持法律术语准确。'
               '文本中的 <MASK-...> 是隐私令牌，必须逐字原样保留；不得猜测、解释、翻译、删除或替换令牌。'
               '只输出JSON: {"items":[{"clause_id":"原id","translated":"译文"}]}。禁止输出推理过程。')
        masked_chunk=[{'clause_id': c.get('id'), 'text': _mask_with_saved_mapping(c.get('text') or '', mapping)[:600]}
                      for c in chunk]
        user = json.dumps(masked_chunk,
                          ensure_ascii=False)
        try:
            r = invoke_remote(llm, [SystemMessage(content=sys), HumanMessage(content=user)], completion_tokens=3500)
            data = _robust_json(r.content)
            items = data.get('items', [])
        except Exception as e:
            items = []
        mp = {it.get('clause_id'): it.get('translated', '') for it in items if it}
        for c in chunk:
            masked_original=next((x['text'] for x in masked_chunk if x['clause_id']==c.get('id')), '')
            translated_masked=mp.get(c.get('id'), '')
            out.append({'clause_id': c.get('id'), 'original': c.get('text', ''),
                        'masked_original': masked_original,
                        'translated_masked': translated_masked,
                        'translated': restore_text(translated_masked, mapping),
                        'mask_restored': any(token in translated_masked for token in mapping)})
        if on_step: on_step(f'翻译Agent: 批次 {i//batch+1} 完成 ({len(out)}/{len(picks)} 条)')
    return out

def run_translate(report, target_lang='en', mapping=None, on_step=None):
    """Run a translation without transmitting restored fields or mask mappings."""
    if target_lang not in LANG_NAME:
        raise ValueError('不支持的目标语言')
    if not mapping:
        raise ValueError('该合同的脱敏映射不存在或已过期，已拒绝将原文发送至翻译模型')
    clauses = report.get('clauses', []) or []
    if on_step: on_step(f'翻译Agent: 开始翻译为 {LANG_NAME.get(target_lang,target_lang)},共 {min(len(clauses),60)} 条')
    translated = translate_clauses(clauses, mapping, target_lang, on_step)
    if on_step: on_step('翻译Agent: 完成；敏感令牌已在服务端恢复')
    return {'target_lang': target_lang, 'target_lang_name': LANG_NAME.get(target_lang, target_lang),
            'translated': translated, 'contract_fields_translated': {}}
