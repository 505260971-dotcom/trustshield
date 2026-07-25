import re

AMOUNT_RE = re.compile(r'(\d[\d,]*\.?\d+)\s*(元|人民币|港币|美元|欧元|日元|韩元|越南盾|RMB|USD|HKD|JPY|EUR)')
PCT_RE = re.compile(r'(\d{1,3})\s*[%％]')
YEAR_RE = re.compile(r'(\d{1,2})\s*(?:个?年|years?|yr)', re.IGNORECASE)
DAY_RE = re.compile(r'(\d{1,4})\s*(?:个?天|日|days?|day)', re.IGNORECASE)

def extract_numerics(text):
    amounts = [{'value': float(a.replace(',', '')), 'currency': cur} for a, cur in AMOUNT_RE.findall(text)]
    pcts = [float(p) for p in PCT_RE.findall(text)]
    years = [int(y) for y in YEAR_RE.findall(text)]
    days = [int(d) for d in DAY_RE.findall(text)]
    return {'amounts': amounts, 'percentages': pcts, 'years': years, 'days': days}

def largest_pct_below_delivery(numerics):
    return max(numerics['percentages'], default=0)
