import re, json

PATTERNS = [
    ('phone', re.compile(r'1[3-9]\d{9}|\+?\d{2,4}[-\s]?\d{6,8}')),  # 电话
    ('email', re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')),
    ('idcard', re.compile(r'\b\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b')),
    ('bank', re.compile(r'(?<!\d)(?:\d[\s-]?){15,22}(?!\d)')),
    ('address', re.compile(r'(地址|地\s*址)\s*[:：]?\s*([^\n，。]{6,40})')),
    ('amount', re.compile(r'(\d[\d,]*\.?\d+)\s*(元|人民币|港币|美元|欧元|日元|韩元|越南盾|RMB|USD|HKD|JPY|EUR)')),
]

COMPANY_HINT = re.compile(r'([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z·\.\(\)()]{2,18}(?:有限公司|股份有限公司|责任公司|集团|公司|Inc\.|Ltd\.|Co\.?\.?|GmbH|Corp\.?|LLC))')
TECH_REF = re.compile(r'((?:图号|零件号|料号|型号|规格编号|Drawing|Part\s*(?:No|Number)|Model)\s*[:：#]?\s*)([A-Za-z0-9][A-Za-z0-9_.\-/]{3,})', re.I)
PERSON_REF = re.compile(r'((?:联系人|签字人|法定代表人|授权代表|代表人)\s*[:：]?\s*)([\u4e00-\u9fa5]{2,4}?)(?=签字|确认|，|。|,|\s|$)')

def mask_text(text):
    mapping = {}  # placeholder -> original
    counter = {'n': 0}
    def add(orig, kind):
        counter['n'] += 1
        ph = f'<MASK-{kind.upper()}-{counter["n"]}>'
        mapping[ph] = orig
        return ph
    out = text
    # 顺序：标识类 -> 公司 -> 金额
    for kind, pat in PATTERNS:
        def rep(m, k=kind):
            return add(m.group(0), k)
        out = pat.sub(rep, out)
    # 公司名脱敏
    out = COMPANY_HINT.sub(lambda m: add(m.group(1), 'COMPANY'), out)
    # High-frequency technical identifiers and named contacts are handled
    # deterministically, so a CPU-bound local LLM only needs to cover true
    # residual cases.
    out = TECH_REF.sub(lambda m: m.group(1) + add(m.group(2), 'TECH'), out)
    out = PERSON_REF.sub(lambda m: m.group(1) + add(m.group(2), 'PERSON'), out)
    return out, mapping

def restore_text(text, mapping):
    for ph, orig in sorted(mapping.items(), key=lambda x: -len(x[0])):
        text = text.replace(ph, orig)
    return text

def uniquify_mapping(masked_text, mapping, global_mapping):
    """Rename per-clause placeholders before joining a task-wide mapping.

    `mask_text` is intentionally stateless.  Without this remap, C1 and C2
    would both produce e.g. `<MASK-PHONE-1>`, and restoring a whole report
    could substitute a value from the wrong clause.
    """
    out = masked_text
    unique = {}
    for old, original in mapping.items():
        match = re.fullmatch(r'<MASK-([A-Z_]+)-\d+>', old)
        kind = match.group(1) if match else 'ENTITY'
        new = f'<MASK-{kind}-{len(global_mapping) + len(unique) + 1}>'
        out = out.replace(old, new)
        unique[new] = original
    return out, unique

def mask_clauses(clauses):
    out = []
    mapping_all = {}
    for c in clauses:
        mt, mp = mask_text(c['text'])
        mt, mp = uniquify_mapping(mt, mp, mapping_all)
        mapping_all.update(mp)
        out.append({**c, 'text_masked': mt})
    return out, mapping_all

if __name__ == '__main__':
    t = '联系：张三 电话：13812345678，注册地：深圳市南山区科技园，金额：人民币 1,200,000 元，付款给深圳东江精密注塑有限公司。'
    m, mp = mask_text(t)
    print(m)
    print(json.dumps(mp, ensure_ascii=True))
    print(restore_text(m, mp))
