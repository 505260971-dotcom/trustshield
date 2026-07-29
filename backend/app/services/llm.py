from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
from ..config import (
    LLM_API_BASE, LLM_API_KEY, LLM_MODEL,
    SMART_MASK, MASK_LLM_API_BASE, MASK_LLM_API_KEY, MASK_LLM_MODEL,
    FINANCIAL_LLM_API_BASE, FINANCIAL_LLM_API_KEY, FINANCIAL_LLM_MODEL,
    REMOTE_CONTEXT_TOKENS, LOCAL_CONTEXT_TOKENS, LLM_TIMEOUT_SECONDS, configured_financial_llm, configured_llm,
)

_MESSAGE_OVERHEAD_TOKENS = 32


def _provider_generation_options(api_base: str) -> dict:
    """Apply only documented provider-specific generation controls.

    Qwen's newer thinking-capable models may spend the complete output budget
    on reasoning tokens before emitting the required JSON.  Extraction and
    report-formatting Agents need deterministic structured output, so disable
    thinking only for the DashScope-compatible endpoint.  Other providers do
    not receive an unknown parameter.
    """
    if 'dashscope.aliyuncs.com' in str(api_base or '').lower():
        return {'extra_body': {'enable_thinking': False}}
    return {}


def _utf8_size(value):
    """Return the byte length without failing on malformed input."""
    text = '' if value is None else str(value)
    return len(text.encode('utf-8', errors='replace'))

def estimate_tokens(value):
    """Return a tokenizer-independent upper bound for plain-text tokens.

    远端模型和本地 Ollama 模型的 tokenizer 可能不同，按中英文比例估算不能作为
    “绝不超窗”的依据。常见 BPE/SentencePiece tokenizer 最坏会退化为 UTF-8 单字节
    切分，因此以 UTF-8 字节数作上界；它会比实际 token 数保守，但不会因换模型而
    把请求放大到上下文上限之外。
    """
    return _utf8_size(value)


def estimate_message_tokens(message):
    """内容上界加 OpenAI 兼容 messages 序列化的固定余量。"""
    return estimate_tokens(getattr(message, 'content', '')) + _MESSAGE_OVERHEAD_TOKENS


def estimate_request_tokens(messages, completion_tokens=0, reserve_tokens=0):
    """估算一次请求的总预算（messages + 最大输出 + 协议/提供方余量）。"""
    return (sum(estimate_message_tokens(message) for message in messages)
            + max(0, int(completion_tokens or 0))
            + max(0, int(reserve_tokens or 0)))


def _clip_prefix_to_tokens(text, budget):
    """取最长前缀，且严格满足 estimate_tokens(prefix) <= budget。"""
    if budget <= 0:
        return ''
    text = str(text or '')
    lo, hi, best = 0, len(text), ''
    while lo <= hi:
        middle = (lo + hi) // 2
        candidate = text[:middle]
        if estimate_tokens(candidate) <= budget:
            best = candidate
            lo = middle + 1
        else:
            hi = middle - 1
    return best

def clip_text_to_tokens(text, budget):
    """严格按预算裁剪文本，并尽量保留首尾。

    原来的按比例截字符方式在加入截断标记、最少保留字符后可能反而超过预算。
    此实现用二分查找选择实际可容纳的字符数，并在返回前再次验证上界。
    """
    text = str(text or '')
    budget = max(0, int(budget or 0))
    if not budget:
        return ''
    if estimate_tokens(text) <= budget:
        return text

    marker = '\n…[按上下文预算截断]…\n'
    marker_tokens = estimate_tokens(marker)
    if marker_tokens > budget:
        return _clip_prefix_to_tokens(text, budget)

    # 查找“保留的原文字符总数”的最大值，而不是按字符/token 比例猜测。
    lo, hi, best = 0, len(text), marker
    while lo <= hi:
        kept = (lo + hi) // 2
        head_chars = (kept * 2 + 2) // 3
        tail_chars = kept - head_chars
        candidate = f'{text[:head_chars]}{marker}{text[-tail_chars:]}' if tail_chars else f'{text[:head_chars]}{marker}'
        if estimate_tokens(candidate) <= budget:
            best = candidate
            lo = kept + 1
        else:
            hi = kept - 1

    # 二分结果应当已经合格；保留此硬校验以防以后更改 marker 或估算器。
    return best if estimate_tokens(best) <= budget else _clip_prefix_to_tokens(best, budget)


def _allocate_content_budgets(messages, total_budget):
    """公平分配一组消息的内容预算，保证总和不超过 total_budget。"""
    remaining = max(0, int(total_budget))
    budgets = []
    for position, message in enumerate(messages):
        remaining_count = len(messages) - position
        fair_share = remaining // remaining_count
        want = estimate_tokens(getattr(message, 'content', ''))
        granted = min(want, fair_share)
        budgets.append(granted)
        remaining -= granted
    return budgets

def fit_messages(messages, context_limit, completion_tokens, reserve_tokens=192):
    """将消息压入“输入 + 最大输出 <= context_limit”的预算内。"""
    context_limit = max(1, int(context_limit))
    completion_tokens = max(0, int(completion_tokens or 0))
    reserve_tokens = max(0, int(reserve_tokens or 0))
    input_budget = context_limit - completion_tokens - reserve_tokens
    if input_budget < 0:
        raise ValueError('最大输出和协议余量已超过上下文上限，已阻止模型调用')
    if estimate_request_tokens(messages, completion_tokens, reserve_tokens) <= context_limit:
        return messages

    message_overhead = len(messages) * _MESSAGE_OVERHEAD_TOKENS
    content_budget = input_budget - message_overhead
    if content_budget < 0:
        raise ValueError('消息封装开销已超过可用上下文，已阻止模型调用')

    system_messages = [message for message in messages if isinstance(message, SystemMessage)]
    other_messages = [message for message in messages if not isinstance(message, SystemMessage)]
    if system_messages and other_messages:
        system_budget = min(sum(estimate_tokens(message.content) for message in system_messages), content_budget // 2)
    elif system_messages:
        system_budget = content_budget
    else:
        system_budget = 0
    other_budget = content_budget - system_budget
    system_budgets = iter(_allocate_content_budgets(system_messages, system_budget))
    other_budgets = iter(_allocate_content_budgets(other_messages, other_budget))
    fitted = []
    for message in messages:
        is_system = isinstance(message, SystemMessage)
        content = clip_text_to_tokens(getattr(message, 'content', ''),
                                      next(system_budgets) if is_system else next(other_budgets))
        fitted.append(message.model_copy(update={'content': content}))

    # 这是发送前的最终硬闸；出现异常配置或后续代码改动时宁可不调用模型。
    if estimate_request_tokens(fitted, completion_tokens, reserve_tokens) > context_limit:
        raise ValueError('上下文裁剪后二次校验失败，已阻止模型调用')
    return fitted

def invoke_remote(llm, messages, completion_tokens):
    return llm.invoke(fit_messages(messages, REMOTE_CONTEXT_TOKENS, completion_tokens))

def invoke_mask(llm, messages, completion_tokens):
    return llm.invoke(fit_messages(messages, LOCAL_CONTEXT_TOKENS, completion_tokens, reserve_tokens=128))

def get_llm(temperature=0.1, max_tokens=4096, json_mode=False, timeout=None, max_retries=1):
    if not configured_llm():
        raise RuntimeError('远端 LLM 未配置：请设置 LLM_API_BASE、LLM_API_KEY 和 LLM_MODEL')
    max_tokens = min(max_tokens, max(64, REMOTE_CONTEXT_TOKENS - 256))
    kw = dict(
        model=LLM_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        base_url=LLM_API_BASE,
        api_key=LLM_API_KEY,
        default_headers={'User-Agent': 'Mozilla/5.0'},
        timeout=LLM_TIMEOUT_SECONDS if timeout is None else timeout,
        max_retries=max(0, int(max_retries)),
    )
    kw.update(_provider_generation_options(LLM_API_BASE))
    if json_mode:
        kw['model_kwargs'] = {'response_format': {'type': 'json_object'}}
    return ChatOpenAI(**kw)


def get_financial_llm(temperature=0, max_tokens=1800, json_mode=True, timeout=45, max_retries=0):
    """Return the isolated financial-extraction model, with explicit demo fallback."""
    if not configured_financial_llm():
        raise RuntimeError('财报 LLM 未配置：请设置 FINANCIAL_LLM_* 或主 LLM_* 配置')
    max_tokens = min(max_tokens, max(64, REMOTE_CONTEXT_TOKENS - 256))
    kw = dict(
        model=FINANCIAL_LLM_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        base_url=FINANCIAL_LLM_API_BASE,
        api_key=FINANCIAL_LLM_API_KEY,
        default_headers={'User-Agent': 'Mozilla/5.0'},
        timeout=LLM_TIMEOUT_SECONDS if timeout is None else timeout,
        max_retries=max(0, int(max_retries)),
    )
    kw.update(_provider_generation_options(FINANCIAL_LLM_API_BASE))
    if json_mode:
        kw['model_kwargs'] = {'response_format': {'type': 'json_object'}}
    return ChatOpenAI(**kw)

def get_mask_llm(temperature=0, max_tokens=1200, json_mode=True, timeout=30):
    """返回仅用于本地隐私识别的小模型；未配置时返回 None。

    合同研判、字段抽取、翻译等业务语义任务统一使用 get_llm() 的强模型。
    """
    if not (SMART_MASK and MASK_LLM_MODEL):
        return None
    max_tokens = min(max_tokens, max(64, LOCAL_CONTEXT_TOKENS - 256))
    kw = dict(
        model=MASK_LLM_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        base_url=MASK_LLM_API_BASE,
        api_key=MASK_LLM_API_KEY,
        timeout=timeout,
    )
    if json_mode:
        kw['model_kwargs'] = {'response_format': {'type': 'json_object'}}
    return ChatOpenAI(**kw)
