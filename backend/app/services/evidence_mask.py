"""Local masking gateway for credit evidence before any remote transfer.

Original financial evidence (statement rows, tables) may only leave the
machine in masked form.  ``mask_evidence_records`` is the single entry
point: it applies the deterministic regex layer, then the configured
masking model (local Ollama by default, or the deployment-configured
provider) over the residuals, and returns masked records plus a
placeholder -> original mapping that stays local.  Every outbound consumer
(rerank, embedding, financial LLM) refuses records that do not carry a
``masked_text``, so there is no code path that sends unmasked financial
evidence.
"""
from __future__ import annotations

from typing import Any

from ..config import MASK_LLM_MODEL
from . import mask as _mask
from .smart_mask import llm_mask_batch


# Credit-evidence oriented residual recognition.  Unlike the contract prompt
# it asks the local model to also mask bare statement numbers (the regex layer
# only covers amounts that carry a currency suffix) while excluding periods,
# page numbers and ratios, which retrieval and period validation still need.
CREDIT_MASK_PROMPT = (
    '你是本地财务证据隐私脱敏子Agent。识别给定财务报表文本中的敏感实体，只输出JSON: '
    '{"items":[{"idx":int,"entities":[{"text":"原文片段","kind":"COMPANY|AMOUNT|TECH|PERSON|PHONE|ADDR"}]}]}。'
    '需识别公司主体名称（含无后缀简称）、报表金额与数值（含千分位与小数）、技术参数、个人姓名电话地址。'
    '年份、页码和比例不计入敏感实体。每条text必须是原文精确片段且不超过30字。')


class EvidenceMaskUnavailable(RuntimeError):
    """Remote financial-data transfer was requested without a masking model."""


def mask_evidence_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Return records with ``masked_text`` plus the global placeholder mapping.

    Fail-closed: without a configured masking model the numeric residuals of a
    statement cannot be masked, so remote transfer must not happen.  Records
    that already carry ``masked_text`` (e.g. constructed in tests) are reused
    as-is without requiring a masking model.
    """
    if all(str(item.get('text_masked') or '').strip() for item in records):
        return records, {}
    if not MASK_LLM_MODEL:
        raise EvidenceMaskUnavailable(
            '未配置本地脱敏模型（mask_llm_model），财务证据不得未脱敏外发；'
            '请在系统设置中配置脱敏模型（默认本地 Ollama，如 qwen3.5:4b）。')
    mapping_all: dict[str, str] = {}
    masked_texts: list[str] = []
    pending: list[int] = []
    for index, record in enumerate(records):
        existing = str(record.get('text_masked') or '').strip()
        if existing:
            masked_texts.append(existing)
            continue
        masked, per = _mask.mask_text(str(record.get('text') or ''))
        masked, per = _mask.uniquify_mapping(masked, per, mapping_all)
        masked_texts.append(masked)
        mapping_all.update(per)
        pending.append(index)
    try:
        batch_entities = llm_mask_batch([masked_texts[index] for index in pending],
                                        system_prompt=CREDIT_MASK_PROMPT, force=True, strict=True)
    except Exception as exc:
        # A masking-model failure must not silently degrade to regex-only
        # residuals (bare statement numbers would leak); refuse the transfer.
        raise EvidenceMaskUnavailable(
            f'本地脱敏模型调用失败，拒绝外发财务证据: {type(exc).__name__}: {str(exc)[:160]}') from exc
    out: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if str(record.get('text_masked') or '').strip():
            out.append(record)
            continue
        masked = masked_texts[index]
        for entity in batch_entities.get(pending.index(index), []) or []:
            value = (entity.get('text') or '').strip()
            if not value or len(value) > 30 or value.startswith('<MASK-') or value in mapping_all.values():
                continue
            if value in masked:
                placeholder = f'<MASK-LLM-{len(mapping_all) + 1}>'
                masked = masked.replace(value, placeholder, 1)
                mapping_all[placeholder] = value
        out.append({**record, 'text_masked': masked})
    return out, mapping_all
