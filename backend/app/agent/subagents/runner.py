"""Subagent 工厂运行核心：给定一个 agent 定义，跑一个自包含的 ReAct 循环。

为什么不复用 chat.py 的主循环 / 不用 LangChain：
- 对话主循环（chat.py）手写了原生 anthropic SDK 的流式事件解析，专门绕过了
  公司网关偶发返回 `text: null` 把 SDK 内部累积搞崩的坑。子助手复用这套
  已验证的手写解析，而不是赌 LangChain `.invoke()` 封装层能扛住网关怪返回。
- 子助手在主循环内部「内联」跑（async generator，被父循环 async for 消费），
  contextvars（会话 / 工作区隔离）天然传播，无需另开 task 或 Queue 桥接。

事件协议：本模块是 async generator，逐个 yield dict：
  {"kind": "tool",       "name", "input", "id"}   子助手发起一次工具调用
  {"kind": "tool_done",  "name", "id", "ok"}       工具执行完成
  {"kind": "file_written", "path", "content", "name"}  写文件类工具产出（供实时预览）
  {"kind": "text",       "text"}                    子助手产出的阶段性文本（可选透传）
  {"kind": "result",     "text"}                    子助手最终答复（最后一个事件）
  {"kind": "error",      "message"}                 出错（终止）

调用方（chat.py）把这些翻译成 SSE 事件透传给前端，并把 result 作为
tool_result 回喂给主 AI。
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, AsyncGenerator

import anthropic

from app.agent.skills import registry as skill_registry
from app.agent.subagents.registry import resolve_tools
from app.config import get_settings


def _lc_tool_to_anthropic(lc_tool) -> dict:
    """LangChain @tool → Anthropic tool schema（与 chat.py 同款转换）。"""
    schema = {"type": "object", "properties": {}, "required": []}
    if lc_tool.args_schema:
        raw = lc_tool.args_schema.model_json_schema()
        schema["properties"] = raw.get("properties", {})
        schema["required"] = raw.get("required", [])
    return {
        "name": lc_tool.name,
        "description": lc_tool.description or "",
        "input_schema": schema,
    }


def _execute_tool(tool_map: dict[str, Any], name: str, args: dict) -> str:
    """执行工具。用 .func(**args) 直调底层函数，绕开 .invoke() 的 context 拷贝，
    确保工具内 ContextVar.set()（如知识库覆盖状态）能传出去——与 chat.py 一致。"""
    lc_tool = tool_map.get(name)
    if lc_tool is None:
        return f"Unknown tool: {name}"
    try:
        return str(lc_tool.func(**args))
    except Exception as e:  # noqa: BLE001
        return f"Tool execution error: {e}"


def _is_ok(result_text: str) -> bool:
    return not str(result_text).startswith(
        ("Tool execution error", "路径越界", "Unknown tool", "Resource not found", "Invalid path")
    )


async def run_subagent(
    agent_def: dict[str, Any],
    task_prompt: str,
) -> AsyncGenerator[dict, None]:
    """按 agent 定义跑一个子助手 ReAct 循环，逐步 yield 事件。

    Args:
        agent_def: registry.scan_agent_defs() 规整后的定义
                   （name/description/model/tools/system_prompt/skill/...）。
        task_prompt: 主 AI 委托给子助手的具体任务描述。
    """
    settings = get_settings()

    # ── 模型：agent 定义 model > 全局 subagent_model > 主模型 ──
    model = agent_def.get("model") or settings.resolved_subagent_model

    # ── 工具：按白名单发；未知名字告警但不致命 ──
    tools, unknown = resolve_tools(agent_def.get("tools"))
    if unknown:
        yield {
            "kind": "text",
            "text": f"[子助手告警] 忽略未登记的工具：{', '.join(unknown)}",
        }
    tool_map = {t.name: t for t in tools}
    anthropic_tools = [_lc_tool_to_anthropic(t) for t in tools]

    # ── 系统提示词：agent 定义正文即执行指令 ──
    system_prompt = agent_def.get("system_prompt", "").strip()
    if not system_prompt:
        yield {"kind": "error", "message": "agent 定义缺少系统提示词正文"}
        return

    # 让子助手知道自己归属哪个 skill，读资源时用得上
    skill_name = agent_def.get("skill", "")
    if skill_name:
        system_prompt += (
            f"\n\n---\n（运行环境：你是 skill「{skill_name}」派生的子助手。"
            f"需要读取该 skill 附带的资源文件时，用 read_skill_resource"
            f'(skill_name="{skill_name}", filename="...")。）'
        )

    messages: list[dict] = [{"role": "user", "content": task_prompt}]

    client = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url or None,
    )

    max_iters = settings.subagent_max_iterations
    max_tokens = settings.subagent_max_tokens
    final_text = ""

    for _iteration in range(max_iters):
        stream_kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
            stream=True,
        )
        if anthropic_tools:
            stream_kwargs["tools"] = anthropic_tools

        # 手动累积 final_message 各字段（与 chat.py 同款，绕开 SDK 自动累积）
        snapshot = {
            "content": [],
            "stop_reason": None,
        }
        assistant_text = ""

        try:
            stream = await client.messages.create(**stream_kwargs)
            async for event in stream:
                etype = event.type
                if etype == "content_block_start":
                    block = (
                        event.content_block.model_dump()
                        if hasattr(event.content_block, "model_dump")
                        else vars(event.content_block)
                    )
                    if block.get("type") == "text" and block.get("text") is None:
                        block["text"] = ""
                    snapshot["content"].append(block)

                elif etype == "content_block_delta":
                    idx = event.index
                    delta = event.delta
                    if delta.type == "text_delta":
                        text = delta.text
                        assistant_text += text
                        final_text += text
                        if idx < len(snapshot["content"]):
                            b = snapshot["content"][idx]
                            if b.get("type") == "text":
                                b["text"] = (b.get("text") or "") + text
                    elif delta.type == "input_json_delta":
                        if idx < len(snapshot["content"]):
                            b = snapshot["content"][idx]
                            if b.get("type") == "tool_use":
                                b["_json_buf"] = b.get("_json_buf", "") + delta.partial_json

                elif etype == "content_block_stop":
                    idx = event.index
                    if idx < len(snapshot["content"]):
                        b = snapshot["content"][idx]
                        if b.get("type") == "tool_use" and "_json_buf" in b:
                            try:
                                b["input"] = json.loads(b["_json_buf"]) if b["_json_buf"] else {}
                            except json.JSONDecodeError:
                                b["input"] = {}
                            del b["_json_buf"]

                elif etype == "message_delta":
                    d = (
                        event.delta.model_dump()
                        if hasattr(event.delta, "model_dump")
                        else vars(event.delta)
                    )
                    if "stop_reason" in d:
                        snapshot["stop_reason"] = d["stop_reason"]

        except anthropic.BadRequestError as e:
            # 网关不支持 tools → 降级无工具重试一次
            if "tool" in str(e).lower() and anthropic_tools:
                anthropic_tools = []
                continue
            yield {"kind": "error", "message": f"子助手请求失败: {e}"}
            return
        except Exception as e:  # noqa: BLE001
            yield {"kind": "error", "message": f"子助手异常: {e}"}
            return

        # 组装成便于取字段的对象
        content_blocks = [SimpleNamespace(**b) for b in snapshot["content"]]

        # max_tokens 截断 → 让子助手接着写
        if snapshot["stop_reason"] == "max_tokens":
            messages.append({"role": "assistant", "content": snapshot["content"]})
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": "你的回复被截断了，请从截断处继续。"}],
            })
            continue

        tool_blocks = [b for b in content_blocks if getattr(b, "type", None) == "tool_use"]
        valid_tool_blocks = [b for b in tool_blocks if getattr(b, "id", None) and getattr(b, "name", None)]

        if not valid_tool_blocks:
            # 没有工具调用 → 子助手结束
            break

        # 把 assistant 消息（含 text + tool_use）入历史
        messages.append({"role": "assistant", "content": snapshot["content"]})

        tool_results: list[dict] = []
        for tb in valid_tool_blocks:
            tool_name = tb.name
            tool_input = tb.input if isinstance(getattr(tb, "input", None), dict) else {}

            yield {"kind": "tool", "id": tb.id, "name": tool_name, "input": tool_input}

            result_text = _execute_tool(tool_map, tool_name, tool_input)
            ok = _is_ok(result_text)

            yield {"kind": "tool_done", "id": tb.id, "name": tool_name, "ok": ok}

            # 写文件类工具：解析真实路径 + 内容，供前端实时预览
            if tool_name in ("write_file", "append_file", "edit_file") and ok:
                from app.agent.tools.workspace import resolve_written_file

                info = resolve_written_file(tool_input.get("path", ""))
                if info:
                    yield {
                        "kind": "file_written",
                        "path": info["path"],
                        "content": info["content"],
                        "name": info["path"].rsplit("/", 1)[-1],
                    }

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tb.id,
                "content": result_text,
            })

        messages.append({"role": "user", "content": tool_results})
    else:
        yield {
            "kind": "text",
            "text": f"[子助手告警] 达到最大迭代次数 {max_iters}，可能未完成。",
        }

    yield {"kind": "result", "text": final_text.strip()}
