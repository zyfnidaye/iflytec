"""工作区会话上下文 + 知识库覆盖状态：把当前请求的 thread_id 和检索结果注入工具执行环境。

agent 的文件工具是模块级无状态函数，本身不知道属于哪个会话。为了让每个会话
的文件互相隔离（workspace/<thread_id>/...），chat.py 在执行工具前用
`set_session(thread_id)` 设置上下文，工具的 `_resolve_safe` 读取它，
自动把工作区根切到对应会话子目录。对 agent 完全透明——它仍只看到相对路径。

同时跟踪知识库检索状态（retrieve/grep 是否执行过 + 有无覆盖），供联网搜索工具
做硬门拦截：只有知识库双重确认"无覆盖"时，web_search 才被允许执行。

用 contextvar 而非全局变量：ASGI 下多个请求的事件循环任务并发，contextvar
天然隔离每个任务的值，不会串会话。
"""
import re
from contextlib import contextmanager
from contextvars import ContextVar

# 当前会话的工作区子目录名（thread_id 经过安全清洗）。空串表示未隔离（工作区根）。
_current_session: ContextVar[str] = ContextVar("workspace_session", default="")

# 知识库检索覆盖状态（本轮对话中）
_kb_retrieve_done: ContextVar[bool] = ContextVar("kb_retrieve_done", default=False)
_kb_grep_done: ContextVar[bool] = ContextVar("kb_grep_done", default=False)
_kb_has_coverage: ContextVar[bool] = ContextVar("kb_has_coverage", default=False)

# 本轮对话累积的段落级引用命中（供前端展示"命中哪段"）。
# default=None 避免可变默认值被共享；读取时按空列表处理。
_kb_citations: ContextVar[list | None] = ContextVar("kb_citations", default=None)


def _sanitize(thread_id: str) -> str:
    """把 thread_id 清洗成安全的目录名：只留字母数字、下划线、连字符。"""
    if not thread_id:
        return ""
    # 去掉路径分隔符和其它危险字符，避免用 thread_id 穿越目录
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", thread_id.strip())
    return safe[:100]  # 限长，防止异常超长名


def set_session(thread_id: str) -> str:
    """设置当前会话，返回清洗后的目录名。"""
    safe = _sanitize(thread_id)
    _current_session.set(safe)
    return safe


def get_session() -> str:
    """取当前会话目录名（已清洗）。未设置时返回空串。"""
    return _current_session.get()


@contextmanager
def use_workspace_session(thread_id: str):
    """临时把工作区切到指定会话子目录，退出时还原（供非流式场景）。"""
    token = _current_session.set(_sanitize(thread_id))
    try:
        yield
    finally:
        _current_session.reset(token)


# ---- 知识库覆盖状态管理 ----

def reset_kb_coverage_state():
    """重置知识库覆盖状态（每轮对话开始时调用，清理上一轮残留）。"""
    _kb_retrieve_done.set(False)
    _kb_grep_done.set(False)
    _kb_has_coverage.set(False)
    _kb_citations.set([])  # 清空引用累积


def record_citations(hits: list[dict]):
    """记录段落级引用命中（跨轮累积，按 doc_id:section_id 去重，保留 distance 最小的）。

    hits 格式: [{"doc_id": str, "section_id": ..., "section_title": str, "snippet": str, "distance": float}]
    多次检索时自动合并，同一段落只保留最优距离那次的记录。
    """
    current = _kb_citations.get()
    if current is None:
        current = []
    else:
        current = list(current)  # 复制，避免 mutate 共享默认值

    # 去重 key map: {doc_id:section_id -> hit}
    seen = {}
    for item in current:
        key = f"{item['doc_id']}:{item.get('section_id')}"
        if key not in seen or item.get("distance", 999) < seen[key].get("distance", 999):
            seen[key] = item

    # 合并新 hits
    for hit in hits:
        key = f"{hit['doc_id']}:{hit.get('section_id')}"
        if key not in seen or hit.get("distance", 999) < seen[key].get("distance", 999):
            seen[key] = hit

    _kb_citations.set(list(seen.values()))


def get_citations() -> list[dict]:
    """获取本轮对话累积的段落级引用（供 chat.py 发 citations SSE 事件）。"""
    citations = _kb_citations.get()
    return list(citations) if citations else []


def reset_citations():
    """清空引用累积（已整合进 reset_kb_coverage_state，一般不单独调用）。"""
    _kb_citations.set([])


def mark_kb_retrieve_done(has_result: bool):
    """标记 retrieve_knowledge 已执行，记录是否有命中结果。"""
    _kb_retrieve_done.set(True)
    if has_result:
        _kb_has_coverage.set(True)


def mark_kb_grep_done(has_result: bool):
    """标记 grep_knowledge 已执行，记录是否有命中结果。"""
    _kb_grep_done.set(True)
    if has_result:
        _kb_has_coverage.set(True)


def get_kb_coverage_state() -> dict:
    """获取当前知识库覆盖状态（供 web_search 硬门检查）。"""
    return {
        "retrieve_done": _kb_retrieve_done.get(),
        "grep_done": _kb_grep_done.get(),
        "has_coverage": _kb_has_coverage.get(),
    }
