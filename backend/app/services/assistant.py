"""案件审查助理：基于当前案件真实上下文（审查报告、信用条件、处置状态）的流式问答。

助理不是独立 Agent 工具循环，而是“受控上下文 + 强模型”的问答：
- 上下文只来自当前案件的报告、信用审核绑定、风险清单与处置状态；
- 证据与合同字段在送模型前经过本地脱敏（与既有隐私网关一致）；
- 模型被明确禁止编造规则、数值或依据，并限制在案件范围内回答；
- 回答中提到的规则号（rule_id）会在结束时回传，前端可据此渲染可点击的依据。
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from .llm import fit_messages, get_llm, REMOTE_CONTEXT_TOKENS

_SYSTEM_PROMPT = (
    '你是 TrustShield 合同审查协作中心的案件审查助理。你只依据下方“案件上下文”回答当前案件的问题；'
    '不得编造规则、数值、条款、审批状态或依据，不得给出法律结论、授信结论或对外承诺。'
    '回答使用简洁中文并分点；引用风险时标注 rule_id 与 clause_id。'
    '上下文中的证据文本可能已做隐私脱敏（<MASK-...> 占位符），不要复述占位符本身。'
    '如果问题超出本案范围或上下文无法支撑，直接说明“依据当前案件无法回答”，不要猜测。'
)

_RULE_TOKEN = re.compile(r'\b(?:CREDIT_[A-Z_]+|R\d{2}|B\d{2})\b')
_CONTEXT_BUDGET = 60000  # UTF-8 字节上界，严格按预算裁剪


def _mask(value: Any) -> str:
    from .mask import mask_text
    masked, _ = mask_text(str(value or ''))
    return masked


def _money(value: Any, currency: str = 'CNY') -> str:
    try:
        number = float(str(value or 0).replace(',', ''))
    except (TypeError, ValueError):
        return '—'
    return f'{number:,.2f}'.rstrip('0').rstrip('.') + f' {currency or "CNY"}'


def _clip(text: str, limit: int = 160) -> str:
    text = str(text or '').strip()
    return text if len(text) <= limit else text[:limit] + '…'


def build_assistant_context(job_id: str, report: dict[str, Any], findings: list[dict[str, Any]],
                            approvals: list[dict[str, Any]], materials: list[dict[str, Any]],
                            case: dict[str, Any] | None) -> str:
    """组装一份只含本案事实的受控上下文文本。"""
    report = report or {}
    summary = report.get('summary') or {}
    fields = report.get('contract_fields') or {}
    decision = report.get('credit_decision') or {}
    conditions = decision.get('conditions') or {}
    risks = report.get('risks') or []
    hints = report.get('review_hints') or []
    case = case or {}

    lines: list[str] = []
    lines.append(f'案件：{job_id}（阶段 {case.get("current_stage") or "—"}，客户 {_mask(case.get("customer_name"))}，'
                 f'业务类型 {case.get("business_type") or "—"}）')
    if decision:
        lines.append(f'信用审核绑定：{_mask(decision.get("customer_name"))} V{decision.get("version") or "—"}，'
                     f'额度上限 {_money(conditions.get("max_credit_amount"), conditions.get("currency"))}，'
                     f'最长账期 {conditions.get("max_payment_days") or 0} 天，交付前最低收款 {conditions.get("min_prepayment_ratio") or 0}%，'
                     f'允许付款方式 {("、".join(conditions.get("allowed_payment_methods") or []) or "未提供")}，'
                     f'VMI/JIT {"允许" if conditions.get("allow_vmi_jit") else "不允许"}')
        if conditions.get('tail_payment_ratio') is not None or conditions.get('tail_payment_days'):
            lines.append(f'TKM 模具条款：首期款采购豁免 {"是" if conditions.get("first_payment_exempt") else "否"}，'
                         f'走模后尾款放账比例上限 {conditions.get("tail_payment_ratio") or 0}%，'
                         f'走模后尾款信用期 {conditions.get("tail_payment_days") or 0} 天')
    parties = fields.get('parties') or {}
    lines.append(f'合同字段：金额 {_money(fields.get("total_amount"), fields.get("currency") or conditions.get("currency"))}，'
                 f'币种 {fields.get("currency") or "—"}，有效期 {fields.get("validity_years") or "—"} 年，'
                 f'付款节点 {_clip(_mask(fields.get("payment_terms")), 120) or "—"}，'
                 f'我方 {_mask(fields.get("our_party")) or "—"}，'
                 f'对方 {_mask("、".join(str(v) for v in parties.values() if str(v or "").strip())) or "—"}')
    lines.append(f'审查结论：总体 {summary.get("overall_level") or "—"}，风险 {summary.get("n_risks") or 0} 条'
                 f'（高 {summary.get("high") or 0} / 中 {summary.get("mid") or 0} / 低 {summary.get("low") or 0}），'
                 f'待人工确认 {len(hints)} 条')

    lines.append('风险清单（rule_id｜严重度｜规则底线｜识别证据(脱敏)｜处置建议｜当前处置）：')
    for risk in (risks or [])[:30]:
        status = risk.get('action_status') or risk.get('decision') or 'pending'
        lines.append(f'- {risk.get("rule_id")}｜{risk.get("severity")}｜{_clip(_mask(risk.get("rule_baseline")), 90)}｜'
                     f'{_clip(_mask(risk.get("evidence")), 110)}｜{_clip(_mask(risk.get("suggestion")), 90)}｜{status}')

    clause_text = {str(item.get('id')): _clip(_mask(item.get('text')), 220) for item in report.get('clauses') or []}
    referenced = [str(risk.get('clause_id')) for risk in (risks or []) if str(risk.get('clause_id') or '').strip()]
    if referenced:
        lines.append('相关条款原文（脱敏，按风险引用提取）：')
        for clause_id in list(dict.fromkeys(referenced))[:10]:
            if clause_id in clause_text:
                lines.append(f'- [{clause_id}] {clause_text[clause_id]}')

    finding_status = {str(f.get('finding_id')): f.get('action_status') for f in findings or []}
    pending_risks = sum(1 for f in findings or [] if f.get('action_status') == 'pending')
    pending_approvals = sum(1 for a in approvals or [] if a.get('status') == 'pending')
    open_materials = sum(1 for m in materials or [] if m.get('status') == 'open')
    lines.append(f'待办：合同风险未处置 {pending_risks} 条；条款例外审批待处理 {pending_approvals} 项；'
                 f'待补材料未关闭 {open_materials} 项（finding_status={len(finding_status)} 项已记录处置）')

    return '\n'.join(lines)


def mentioned_rule_ids(answer: str, risks: list[dict[str, Any]]) -> list[str]:
    """从回答中抽取提到的规则号，并只保留本案风险清单中真实存在的规则。"""
    known = {str(risk.get('rule_id')) for risk in risks or [] if str(risk.get('rule_id') or '').strip()}
    return sorted({match.group(0) for match in _RULE_TOKEN.finditer(str(answer or ''))} & known)


def build_messages(question: str, context: str, history: list[dict[str, Any]] | None) -> list[Any]:
    """按预算组装消息：系统约束 + 案件上下文 + 最近对话历史 + 当前问题。"""
    messages: list[Any] = [SystemMessage(content=_SYSTEM_PROMPT)]
    context = _clip(context, _CONTEXT_BUDGET)
    history = (history or [])[-6:]
    content: list[str] = []
    if history:
        content.append('最近对话：')
        for item in history:
            role = '用户' if str(item.get('role')) == 'user' else '助理'
            content.append(f'{role}：{_clip(str(item.get("content") or ""), 300)}')
    content.append('以下为当前案件的受控上下文：')
    content.append('```' + context + '```')
    content.append(f'当前问题：{question}')
    messages.append(HumanMessage(content='\n'.join(content)))
    return fit_messages(messages, REMOTE_CONTEXT_TOKENS, 1024)


def chat_llm():
    """返回用于实时问答的强模型；未配置时抛错由调用方转为 503。"""
    return get_llm(temperature=0.2, max_tokens=1024, max_retries=1)


def assistant_answer_text(llm: Any, messages: list[Any]) -> str:
    """同步调用并返回完整回答（用于测试/兜底路径）。"""
    return str(llm.invoke(messages).content or '')


async def stream_assistant_answer(llm: Any, messages: list[Any]) -> Any:
    """流式调用，逐块产出回答文本；用法：async for text in stream_assistant_answer(...)。"""
    async for chunk in llm.astream(messages):
        text = str(getattr(chunk, 'content', '') or '')
        if text:
            yield text
