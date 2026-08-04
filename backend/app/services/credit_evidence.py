"""Evidence chunking and masked material manifests for the credit ReAct audit.

Original records are never sent to any remote service.  The ReAct agent and
the retrieval services only consume ``masked_text`` produced by the local
masking gateway (``evidence_mask``); the original ``text`` stays local for
quote/number validation and the reviewer-facing report.
"""
from __future__ import annotations

from typing import Any

from .llm import clip_text_to_tokens
from .mask import mask_text as _mask_text


def build_document_manifest(document: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Give the planner a bounded material view, never an unbounded document.

    Preview rows and the original file name are masked: this manifest is the
    planner's view of the material, so it may never contain unmasked source
    text once records have gone through the masking gateway.
    """
    preview_rows = []
    for record in records[:12]:
        text = str(record.get('text_masked') or '').strip()
        if text:
            preview_rows.append({
                'source_ref': str(record.get('source_ref') or ''),
                'source_kind': str(record.get('source_kind') or 'text'),
                'text': clip_text_to_tokens(text, 420),
            })
    kinds: dict[str, int] = {}
    for record in records:
        kind = str(record.get('source_kind') or 'text')
        kinds[kind] = kinds.get(kind, 0) + 1
    return {
        'document_id': str(document.get('document_id') or ''),
        'declared_type': str(document.get('document_type') or 'other'),
        'original_name': _mask_text(str(document.get('original_name') or ''))[0],
        'record_count': len(records), 'source_kinds': kinds, 'preview': preview_rows,
    }


def build_evidence_chunks(document: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make retrieval units with one-record context and stable source anchors."""
    chunks: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        center = str(record.get('text') or '').strip()
        if not center or record.get('source_kind') == 'ocr_pending':
            continue
        before = str(records[index - 1].get('text') or '').strip() if index else ''
        after = str(records[index + 1].get('text') or '').strip() if index + 1 < len(records) else ''
        text = '\n'.join(part for part in (before[-220:], center, after[:220]) if part)
        chunks.append({
            'chunk_id': f"{document.get('document_id') or 'document'}:R{index + 1}",
            'document_id': str(document.get('document_id') or ''),
            'document_type': str(document.get('document_type') or 'other'),
            'source_ref': str(record.get('source_ref') or ''),
            'source_kind': str(record.get('source_kind') or 'text'),
            'page': int(record.get('start_page') or 0),
            # Preserve parser/source provenance for the production Claim
            # verifier.  These fields are metadata, not inferred facts.
            'content_hash': str(document.get('content_hash') or ''),
            'parser_version': str(document.get('text_parser_version') or ''),
            'table_id': str(record.get('table_id') or ''),
            'row': record.get('row'),
            'column': record.get('column'),
            'bbox': record.get('bbox'),
            'text': clip_text_to_tokens(text, 2200),
            # Only the local masking gateway may produce masked_text; without
            # it the outbound services (rerank/embedding) refuse the chunk.
            'masked_text': str(record.get('text_masked') or '').strip() or None,
        })
    return chunks
