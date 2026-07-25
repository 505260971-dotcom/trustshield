# -*- coding: utf-8 -*-
"""上下文硬上限回归：无需网络或模型服务。

用法：python scripts/test_context_budget.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from langchain_core.messages import HumanMessage, SystemMessage
from app.services.llm import (
    clip_text_to_tokens,
    estimate_request_tokens,
    estimate_tokens,
    fit_messages,
)


def test_clip_never_exceeds_budget():
    text = ('中文 English 123，条款条件、例外与责任；' * 3000)
    for budget in (0, 1, 8, 24, 64, 96, 128, 256, 700, 2048):
        clipped = clip_text_to_tokens(text, budget)
        assert estimate_tokens(clipped) <= budget, (budget, estimate_tokens(clipped))


def test_local_context_hard_cap():
    messages = [
        SystemMessage(content='系统约束：' + '仅输出 JSON；' * 1000),
        HumanMessage(content=('客户名称 Example Corp；付款条件为验收后 180 天。' * 2500)),
    ]
    completion = 512
    reserve = 128
    fitted = fit_messages(messages, 2048, completion, reserve)
    total = estimate_request_tokens(fitted, completion, reserve)
    assert total <= 2048, total
    assert fitted != messages


def test_remote_context_hard_cap():
    messages = [
        SystemMessage(content='合同研判规则。' * 10000),
        HumanMessage(content=('Long English contract clause with 中文补充条款。' * 60000)),
    ]
    completion = 3500
    reserve = 192
    fitted = fit_messages(messages, 128000, completion, reserve)
    total = estimate_request_tokens(fitted, completion, reserve)
    assert total <= 128000, total
    assert fitted != messages


if __name__ == '__main__':
    test_clip_never_exceeds_budget()
    test_local_context_hard_cap()
    test_remote_context_hard_cap()
    print('context budget checks passed: local <= 2048, remote <= 128000')
