"""Subagent 可用工具的白名单注册表。

安全边界：子助手不能拿到主 AI 的全部工具，只能用它被显式授予的那些。
本模块把「工具名 → langchain @tool」集中登记，工厂据此按白名单发工具。

工具名与前端 TOOL_META、chat.py 的工具名保持一致，这样子助手内部工具事件
透传到前端后能复用同一套图标/文案渲染。

新增可授予子助手的工具时，在 _REGISTRY 里登记即可；不登记的工具无法被
任何 agent 定义引用（即使 frontmatter 写了也会被忽略并告警）。
"""
from __future__ import annotations

from typing import Any

from app.agent.tools.knowledge import KNOWLEDGE_TOOLS
from app.agent.tools.skills import SKILL_TOOLS
from app.agent.tools.workspace import WORKSPACE_TOOLS


# 即便被 agent 定义显式声明也不授予子助手的高影响工具。
# publish_skill 会写技能库（改变全局可用能力），远超「干活产出」范畴，
# 不该出现在任何子助手的可用池里——从注册表源头排除，堵死显式引用。
_NEVER_GRANT: set[str] = {"publish_skill"}


def _build_registry() -> dict[str, Any]:
    """把各工具组拍平成 {name: tool} 映射（排除 _NEVER_GRANT 里的高影响工具）。"""
    reg: dict[str, Any] = {}
    for group in (WORKSPACE_TOOLS, KNOWLEDGE_TOOLS, SKILL_TOOLS):
        for t in group:
            if t.name in _NEVER_GRANT:
                continue
            reg[t.name] = t
    return reg


# 工具名 → langchain @tool
_REGISTRY: dict[str, Any] = _build_registry()

# 工厂默认白名单：agent 定义未声明 tools 时授予的安全默认集。
# 只给「读技能资源 + 工作区读写 + 知识库检索」这类干活必需、无外部副作用的工具。
# 刻意不含 web_search（外部网络）、publish_skill（改技能库）等高影响工具——
# 需要时 agent 定义里显式声明。
DEFAULT_TOOL_NAMES: list[str] = [
    # 技能资源（读 agents 附带的 reference/templates/scripts 等）
    "read_skill_resource",
    # 工作区读写（子助手产出落在这里）
    "list_files",
    "read_file",
    "write_file",
    "edit_file",
    "append_file",
    # 知识库检索（executor 类子助手常需查内部文档核对）
    "list_knowledge_docs",
    "retrieve_knowledge",
    "grep_knowledge",
    "read_document",
]


def resolve_tools(names: list[str] | None) -> tuple[list[Any], list[str]]:
    """把工具名列表解析成 langchain 工具对象列表。

    Args:
        names: 白名单工具名；None 表示用 DEFAULT_TOOL_NAMES。

    Returns:
        (tools, unknown_names)：解析出的工具对象 + 未登记（被忽略）的名字。
        未知名字不报错，只回传供调用方告警，保证 agent 定义写错一个名字
        不会整体崩掉。
    """
    if names is None:
        names = DEFAULT_TOOL_NAMES

    tools: list[Any] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        tool = _REGISTRY.get(name)
        if tool is None:
            unknown.append(name)
        else:
            tools.append(tool)
    return tools, unknown


def available_tool_names() -> list[str]:
    """当前可授予子助手的全部工具名（诊断/文档用）。"""
    return sorted(_REGISTRY.keys())
