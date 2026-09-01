"""联网搜索工具：基于 DuckDuckGo（免费、无需 API Key）。

设计原则（与知识库工具区分）：
- 知识库工具（retrieve_knowledge 等）是【权威来源】，回答公司内部文档问题优先用它。
- web_search 是【外部补充】，用于知识库未覆盖的时效性/通用信息。
- 联网所得结果非公司权威来源，回答时须注明"以下信息来自联网搜索"，供用户甄别。

稳定性：DuckDuckGo 偶发限速返回空，故内置重试 + 空结果兜底。
"""
import time

from langchain_core.tools import tool

_MAX_RETRIES = 3
_RETRY_WAIT = 1.5  # 秒


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """联网搜索，获取知识库中没有的最新/外部信息。

    ⚠️ 硬性规则：只有在知识库检索确认"无覆盖"后才能使用本工具。
    必须先完成以下任一流程：
      1. retrieve_knowledge 返回"未找到" + grep_knowledge 精确匹配也空（双重确认无覆盖）
      2. retrieve_knowledge 返回"未找到"且问题明显超出知识库范围（如通用技术问题）

    适用场景：
    - 时效性信息（最新版本、近期事件、当前价格等）
    - 知识库未覆盖的通用技术问题、第三方库用法
    - 需要外部佐证或补充的内容

    不适用场景：
    - 公司内部文档、接口、API —— 必须用知识库，联网结果是污染
    - 知识库里已明确有的内容

    Args:
        query: 搜索关键词（用自然语言或关键词均可）
        max_results: 返回结果条数，默认 5，建议 3-8

    Returns:
        编号列表，每条含标题、URL、内容摘要。
        注意：这些是【联网所得的外部信息】，非公司权威来源，
        回答时请注明来源为联网搜索，供用户自行甄别。
    """
    from app.agent.workspace_context import get_kb_coverage_state

    # 硬门检查：是否已确认知识库无覆盖
    state = get_kb_coverage_state()

    # 如果知识库有覆盖，直接拒绝
    if state["has_coverage"]:
        return (
            "❌ 联网搜索被拒绝：知识库已有相关内容。\n\n"
            "接口/API 等内部问题必须以知识库为准，联网结果会污染权威答案。\n"
            "请基于已检索到的知识库内容作答，不要联网。"
        )

    # 如果还没做过任何检索，拒绝并提示先检索
    if not state["retrieve_done"]:
        return (
            "❌ 联网搜索被拒绝：尚未检索知识库。\n\n"
            "必须先用 retrieve_knowledge 确认知识库是否有相关内容。\n"
            "只有知识库确认无覆盖后，才能联网查找外部信息。"
        )

    # retrieve 做过且返回空，但建议做 grep 二次确认（可选，不强制）
    if not state["grep_done"]:
        # 这里不强制拒绝，但给个提示，让模型自己判断要不要再 grep 确认
        pass  # 可以在下面的返回文本里加提示

    # 通过硬门，执行搜索
    try:
        from ddgs import DDGS
    except ImportError:
        return "联网搜索不可用：未安装 ddgs 依赖。"

    max_results = max(1, min(max_results, 10))
    last_err = None

    for attempt in range(_MAX_RETRIES):
        try:
            results = list(
                DDGS().text(query, max_results=max_results, region="cn-zh")
            )
            if results:
                lines = []
                for i, r in enumerate(results, 1):
                    title = r.get("title", "").strip()
                    url = r.get("href", "").strip()
                    body = r.get("body", "").strip()
                    lines.append(f"[{i}] {title}\n    链接：{url}\n    摘要：{body}")

                grep_hint = ""
                if not state["grep_done"]:
                    grep_hint = "\n💡 提示：若想更确保知识库真的没有，可对核心关键词用 grep_knowledge 二次确认。\n"

                return (
                    f"联网搜索「{query}」共 {len(results)} 条结果"
                    f"（外部信息，非公司权威来源，请注明来源供用户甄别）：\n{grep_hint}\n"
                    + "\n".join(lines)
                )
            # 空结果：可能被限速，重试
            last_err = "返回空结果（可能被限速）"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"

        if attempt < _MAX_RETRIES - 1:
            time.sleep(_RETRY_WAIT)

    return (
        f"联网搜索「{query}」未获得结果：{last_err}。"
        f"可稍后重试，或改用知识库工具/告知用户暂时无法联网。"
    )


WEB_TOOLS = [web_search]
