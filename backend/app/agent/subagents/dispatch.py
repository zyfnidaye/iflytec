"""委托工具：主 AI 用来把任务派给子助手。

工厂对外暴露两个入口（两种「定义」子助手的方式）：

1. dispatch_agent(agent_name, task) —— 声明式。
   调用一个 skill 目录下 agents/*.md 预先声明好的子助手。
   agent 的系统提示词、模型、工具白名单都写死在定义里，可控、可复用。
   这是 write-test-yaml 这类正式 skill 的标准路径。

2. run_inline_agent(instructions, task, tools) —— 临时内联。
   主 AI 现场描述一个一次性子助手（系统提示词 + 可选工具白名单），
   不需要预先写 agents/*.md。适合临时、探索性的委托。
   工具白名单仍受 subagents.registry 的登记约束。

这两个函数**不是**普通同步 @tool：它们需要逐步产出内部事件透传给前端。
所以这里只登记「委托意图」的元数据 + 参数 schema，真正的执行由 chat.py
在 ReAct 循环里特判、内联跑 run_subagent()。见 DISPATCH_TOOL_NAMES。
"""
from __future__ import annotations

from app.agent.skills import registry as skill_registry
from app.agent.subagents.registry import available_tool_names

# 这两个工具名在 chat.py 里被特判：不走普通 _execute_tool，而是内联跑子助手循环。
DISPATCH_AGENT = "dispatch_agent"
RUN_INLINE_AGENT = "run_inline_agent"
DISPATCH_TOOL_NAMES = {DISPATCH_AGENT, RUN_INLINE_AGENT}


def _dispatch_agent_schema() -> dict:
    return {
        "name": DISPATCH_AGENT,
        "description": (
            "把一个任务委托给预定义的子助手（subagent）执行。子助手有自己独立的"
            "上下文，干活产生的中间过程不会污染当前对话，只把最终结果返回给你。"
            "适合「按既定流程埋头产出」的重活（如按 skill 规范生成大量文件）。"
            "可用的子助手见系统提示词的 Available Subagents 列表。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "子助手名称（来自 Available Subagents 列表）",
                },
                "task": {
                    "type": "string",
                    "description": "交给子助手的具体任务描述（越具体越好：输入是什么、要产出什么、有何约束）",
                },
            },
            "required": ["agent_name", "task"],
        },
    }


def _run_inline_agent_schema() -> dict:
    return {
        "name": RUN_INLINE_AGENT,
        "description": (
            "现场创建一个临时子助手来执行一次性任务，无需预先定义。你用 instructions "
            "描述它的角色和执行规则，用 task 给出具体任务，可选 tools 限定它能用的工具。"
            "适合临时、探索性的委托；正式可复用的流程应做成 skill 的 agents/*.md 再用 "
            "dispatch_agent 调用。可授予的工具名见 instructions 里的说明。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instructions": {
                    "type": "string",
                    "description": "子助手的系统提示词：它是谁、要遵守什么规则、如何产出",
                },
                "task": {
                    "type": "string",
                    "description": "交给子助手的具体任务",
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "（可选）授予子助手的工具名白名单。缺省则用安全默认集。"
                        f"可选工具：{', '.join(available_tool_names())}"
                    ),
                },
            },
            "required": ["instructions", "task"],
        },
    }


def dispatch_tool_schemas() -> list[dict]:
    """返回两个委托工具的 Anthropic tool schema，供 chat.py 挂载。"""
    return [_dispatch_agent_schema(), _run_inline_agent_schema()]


def build_inline_agent_def(instructions: str, tools: list[str] | None) -> dict:
    """把 run_inline_agent 的入参组装成 run_subagent 能吃的 agent 定义。"""
    return {
        "name": "inline-agent",
        "description": "临时内联子助手",
        "model": "",          # 用全局默认
        "tools": tools,       # None → 工厂默认白名单
        "system_prompt": instructions,
        "skill": "",          # 内联子助手不归属特定 skill
        "source": "inline",
    }


def render_available_subagents() -> str:
    """把已声明的 agent 定义渲染成一段系统提示词，注入主 AI。

    没有任何 agent 定义时返回空串（主 AI 就只有 run_inline_agent 可用）。
    """
    defs = skill_registry.scan_agent_defs()
    if not defs:
        return ""
    lines = "\n".join(f"- **{d['name']}**：{d['description']}" for d in defs)
    return (
        "\n\n## Available Subagents（可委托的子助手）\n\n"
        "你可以用 `dispatch_agent(agent_name, task)` 把重活委托给下列子助手。"
        "它们在独立上下文里干活，只回传最终结果，不会污染当前对话：\n\n"
        f"{lines}\n\n"
        "何时委托：任务是「按既定流程产出大量内容/文件」且会产生大量中间过程时，"
        "优先委托，保持主对话干净。委托后如实把子助手的结果转达给用户。"
    )
