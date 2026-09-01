"""Artifact 工具：用于生成大文档时提供实时预览。

用法：
1. agent 调用 create_artifact 声明要生成文档
2. 多次调用 append_artifact 逐段追加内容
3. 每次追加时，后端推 artifact_update 事件给前端实时预览
"""

from langchain_core.tools import tool

# 会话级 artifact 状态（简单起见用全局变量，生产环境应该用 Redis）
_artifact_store = {}


@tool
def create_artifact(title: str, artifact_type: str = "markdown") -> str:
    """创建一个 artifact（文档、代码等），用于在前端实时预览。

    适用场景：生成大文档、长代码文件时，让用户能在右侧预览面板实时看到内容增长。

    Args:
        title: artifact 的标题，显示在预览面板顶部
        artifact_type: 类型，可选 'markdown' / 'code' / 'html'，默认 'markdown'

    Returns:
        artifact_id，后续用 append_artifact 追加内容时需要这个 id

    注意：create 后必须配合 append_artifact 逐段追加内容，不要一次性生成全部。
    建议每 500-1000 字追加一次，让用户能看到渐进式生成过程。
    """
    from app.agent.workspace_context import get_session

    session_id = get_session()
    artifact_id = f"{session_id}:{title}"

    _artifact_store[artifact_id] = {
        "title": title,
        "type": artifact_type,
        "content": "",
        "session": session_id,
    }

    return f"已创建 artifact（ID: {artifact_id}），请使用 append_artifact 逐段追加内容"


@tool
def append_artifact(artifact_id: str, content: str) -> str:
    """向指定 artifact 追加内容。前端会实时显示更新。

    Args:
        artifact_id: create_artifact 返回的 id
        content: 要追加的内容片段（500-1000 字为佳，太长会慢）

    Returns:
        追加成功的确认信息
    """
    if artifact_id not in _artifact_store:
        return f"Artifact 不存在: {artifact_id}，请先调用 create_artifact"

    _artifact_store[artifact_id]["content"] += content

    # 这里返回的字符串会被 chat.py 看到，后面我们在 chat.py 里拦截并推送事件
    return f"__ARTIFACT_UPDATE__:{artifact_id}:{len(content)}"


def get_artifact_content(artifact_id: str) -> dict | None:
    """供 chat.py 调用，获取 artifact 完整内容用于推送事件"""
    return _artifact_store.get(artifact_id)


def clear_session_artifacts(session_id: str):
    """清理某个会话的所有 artifacts（可选，用于会话结束时清理）"""
    to_remove = [k for k in _artifact_store if _artifact_store[k]["session"] == session_id]
    for k in to_remove:
        del _artifact_store[k]


ARTIFACT_TOOLS = [create_artifact, append_artifact]
