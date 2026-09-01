"""LangGraph 智能体：基于 ReAct 模式，接 Claude，挂载工作区与拓扑工具。"""
from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.skills.registry import scan_skills
from app.agent.tools.knowledge import KNOWLEDGE_TOOLS
from app.agent.tools.skills import SKILL_TOOLS
from app.agent.tools.topology import TOPOLOGY_TOOLS
from app.agent.tools.workspace import WORKSPACE_TOOLS
from app.config import get_settings

# 说明：agent 本身无状态（不挂 checkpointer）。多轮上下文由 sqlite 持久化
# 存储（app.store.conversations）在每次请求时读出历史、连同新消息一起喂入。
# 这样重启进程后历史仍在，且避免与 checkpointer 双份维护上下文。


def _build_system_prompt(state):
    """动态构建系统提示词，注入当前可用的 skills 列表。

    每次请求时调用，确保新上传的 skills 立即可见，无需重启。
    """
    skills = scan_skills()
    if skills:
        skill_list = "\n".join(f"- **{s['name']}**: {s['description']}" for s in skills)
        prompt_text = f"""{SYSTEM_PROMPT}

## Available Skills

You have access to the following specialized skills. When a task matches one, use the `load_skill` tool to get detailed instructions:

{skill_list}

To use a skill: call `load_skill(skill_name)` to read its full instructions, then follow them.
"""
    else:
        prompt_text = SYSTEM_PROMPT

    return [SystemMessage(content=prompt_text), *state["messages"]]


@lru_cache
def get_llm(max_tokens: int = 8192):
    """获取 LLM 实例（带缓存）。子 agent 和主 agent 共用。"""
    settings = get_settings()
    kwargs = dict(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        temperature=0,
        max_tokens=max_tokens,
    )
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url
    return ChatAnthropic(**kwargs)


@lru_cache
def get_agent():
    llm = get_llm()
    tools = KNOWLEDGE_TOOLS + WORKSPACE_TOOLS + TOPOLOGY_TOOLS + SKILL_TOOLS
    return create_react_agent(
        llm,
        tools=tools,
        # 用 callable 动态构建系统提示词，每次请求时注入最新 skills 列表
        state_modifier=_build_system_prompt,
    )
