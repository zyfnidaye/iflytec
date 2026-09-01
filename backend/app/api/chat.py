"""对话接口：SSE 流式返回 token 与工具调用事件。

使用 Anthropic 原生 SDK 实现带工具调用的 ReAct 循环：
1. 将 LangChain 工具转为 Anthropic tool schema
2. 每次 API 调用附加工具定义
3. 模型返回 text → 流式推 token；返回 tool_use → 本地执行 → 结果回传
4. 循环直到模型不再调用工具（或达到最大迭代次数）
"""

import json
import traceback

import anthropic
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from app.agent.graph import WORKSPACE_TOOLS, TOPOLOGY_TOOLS, SKILL_TOOLS
from app.agent.tools.knowledge import KNOWLEDGE_TOOLS
from app.agent.tools.web import WEB_TOOLS
from app.agent.tools.artifact import ARTIFACT_TOOLS, get_artifact_content
from app.agent.tools.workspace import resolve_written_file
from app.agent.subagents.dispatch import (
    DISPATCH_TOOL_NAMES,
    DISPATCH_AGENT,
    RUN_INLINE_AGENT,
    build_inline_agent_def,
    dispatch_tool_schemas,
)
from app.agent.subagents.runner import run_subagent
from app.agent.skills import registry as skill_registry
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.skills.registry import scan_skills
from app.config import get_settings
from app.store import conversations as convo

router = APIRouter()

# ReAct 最大迭代次数，防止无限循环
MAX_TOOL_ITERATIONS = 15
# 单次 API 调用的最大输出 token 数（复杂多工具任务需要较大空间）
MAX_OUTPUT_TOKENS = 16384

# ---------------------------------------------------------------------------
# Prompt Caching（照 Claude Code 的做法）
# ---------------------------------------------------------------------------
# 渲染顺序恒为 tools → system → messages，任何前缀字节变化都会让其后全部失效。
# 策略：
#   1) system 末尾打 1 个断点 → 连带把 tools + system 一起缓存（二者本轮内不变）。
#   2) 对话历史最近 2 条消息末尾各打断点 → ReAct 逐轮增量命中前缀，
#      且读点始终落在 20-block lookback 窗口内。
# 断点总数 = 1(system) + 2(messages) = 3，在每请求 4 个上限内。
_CACHE_CONTROL = {"type": "ephemeral"}


def _system_blocks(system_prompt: str) -> list[dict]:
    """把 system 字符串转成带缓存断点的 block 列表（断点在最后一块，连带缓存 tools）。"""
    return [{
        "type": "text",
        "text": system_prompt,
        "cache_control": _CACHE_CONTROL,
    }]


def _block_set_cache(block: dict) -> dict:
    """在单个 content block 上打缓存断点（浅拷贝，避免污染历史原对象）。"""
    b = dict(block)
    b["cache_control"] = _CACHE_CONTROL
    return b


def _mark_messages_cache(messages: list[dict]) -> list[dict]:
    """给最近 2 条消息的最后一个 content block 打缓存断点。

    - content 为字符串的消息：包装成单个 text block 再打断点。
    - content 为 block 列表的消息：在最后一个 block 上打断点。
    返回浅拷贝后的新列表，绝不修改传入的 anthropic_messages 原对象
    （原对象要保持"干净"，下一轮才能稳定命中同一份前缀缓存）。
    """
    if not messages:
        return messages
    out = [dict(m) for m in messages]
    # 只给最后 2 条打点（滚动窗口）
    for m in out[-2:]:
        content = m.get("content")
        if isinstance(content, str):
            m["content"] = [{
                "type": "text",
                "text": content,
                "cache_control": _CACHE_CONTROL,
            }]
        elif isinstance(content, list) and content:
            new_content = list(content)
            new_content[-1] = _block_set_cache(new_content[-1])
            m["content"] = new_content
    return out


def _strip_cache_control(obj):
    """递归剥掉所有 cache_control 字段（网关不支持时降级用）。"""
    if isinstance(obj, dict):
        return {k: _strip_cache_control(v) for k, v in obj.items() if k != "cache_control"}
    if isinstance(obj, list):
        return [_strip_cache_control(x) for x in obj]
    return obj


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"
    # 可选：附带的图片（base64 data url），用于让模型看架构图
    image_data_urls: list[str] = []
    # 是否启用知识库检索
    use_knowledge: bool = True
    # 是否强制首轮检索知识库（tool_choice 锁死 retrieve_knowledge）。
    # True=防幻觉最强但简单问题也慢；False=让模型自主判断是否检索（快，靠 prompt + Layer-2 兜底）
    # 默认 False：日常提速，靠 Layer-2 免责兜底；需要强防幻觉时前端 UI 开关手动开启。
    force_retrieval: bool = False
    # 是否启用联网搜索
    use_web: bool = False


# ---------------------------------------------------------------------------
# 工具转换：LangChain @tool → Anthropic tool schema
# ---------------------------------------------------------------------------

def _lc_tool_to_anthropic(lc_tool) -> dict:
    """将一个 LangChain StructuredTool 转为 Anthropic tool schema。"""
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


def _build_tool_map():
    """构建 {name: callable} 的工具映射表（含知识库工具，供 ReAct 循环执行）。"""
    all_tools = KNOWLEDGE_TOOLS + WEB_TOOLS + WORKSPACE_TOOLS + TOPOLOGY_TOOLS + SKILL_TOOLS + ARTIFACT_TOOLS
    return {t.name: t for t in all_tools}


def _execute_tool(name: str, args: dict) -> str:
    """执行指定工具并返回字符串结果。

    使用 .func(**args) 直接调用底层函数，绕过 .invoke() 的 context 拷贝，
    确保工具内部的 ContextVar.set() 能传递到外部（修复知识库覆盖状态丢失的 bug）。
    """
    tool_map = _build_tool_map()
    lc_tool = tool_map.get(name)
    if lc_tool is None:
        return f"Unknown tool: {name}"
    try:
        result = lc_tool.func(**args)
        return str(result)
    except Exception as e:
        return f"Tool execution error: {e}"


async def _run_dispatch(tool_name: str, tool_input: dict, parent_id: str):
    """把一次委托工具调用解析成 agent 定义并内联跑子助手循环。

    这是 async generator：逐个转发 run_subagent 的事件（tool/tool_done/
    file_written/text/result/error）。参数错误（agent 不存在、缺字段）时
    直接 yield 一个 error 事件，让上层把它作为 tool_result 回喂给主 AI，
    主 AI 可据此改正重试，而不是整轮崩掉。

    parent_id 目前未在事件里回填（上层已用外层 tb.id 关联），保留形参
    是为了将来子助手嵌套时定位归属。
    """
    if tool_name == DISPATCH_AGENT:
        agent_name = (tool_input.get("agent_name") or "").strip()
        task = tool_input.get("task") or ""
        if not agent_name:
            yield {"kind": "error", "message": "dispatch_agent 缺少 agent_name"}
            return
        agent_def = skill_registry.get_agent_def(agent_name)
        if agent_def is None:
            yield {
                "kind": "error",
                "message": f"未找到名为 '{agent_name}' 的子助手。请查看 Available Subagents 列表。",
            }
            return
        async for ev in run_subagent(agent_def, task):
            yield ev
        return

    if tool_name == RUN_INLINE_AGENT:
        instructions = (tool_input.get("instructions") or "").strip()
        task = tool_input.get("task") or ""
        tools = tool_input.get("tools")
        if not instructions:
            yield {"kind": "error", "message": "run_inline_agent 缺少 instructions"}
            return
        if tools is not None and not isinstance(tools, list):
            tools = None
        agent_def = build_inline_agent_def(instructions, tools)
        async for ev in run_subagent(agent_def, task):
            yield ev
        return

    yield {"kind": "error", "message": f"未知委托工具: {tool_name}"}


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_content(req: ChatRequest):
    if not req.image_data_urls:
        return req.message
    parts: list[dict] = [{"type": "text", "text": req.message}]
    for url in req.image_data_urls:
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts


# Claude Code 风格上下文管理：平时全量保留原文，估算 token 接近预算时
# 才做一次结构化压缩（把老消息归纳进 summary），压缩后仍保留最近若干轮原文。
COMPACT_TOKEN_BUDGET = 50_000  # token 用量接近此预算时触发压缩（本地字符估算，宁可偏早）
KEEP_RECENT_TURNS = 3  # 压缩后仍保留原文的最近轮数（user+assistant 各算一条）
CHARS_TO_TOKENS = 0.6  # 字符→token 粗估系数：中英混合保守取值，宁可高估、早压缩


def _estimate_tokens(messages: list[dict]) -> int:
    """本地粗估上下文 token：累加所有 content 字符数 × 系数。宁可高估触发早压缩。"""
    total = 0
    for m in messages:
        c = m.get("content")
        total += len(c) if isinstance(c, str) else len(str(c))
    return int(total * CHARS_TO_TOKENS)


def _history_messages(thread_id: str) -> list:
    """构建历史上下文：结构化摘要（若有）+ 已压缩点之后的全量原文。

    Claude Code 风格：平时全量保留原文，只有 _compact_if_needed 触发过压缩时，
    前 compacted_count 条已被归纳进 summary，这里只回放其后的原文。
    """
    all_msgs = convo.get_messages(thread_id)
    if not all_msgs:
        return []

    out = []

    # 1. 已有摘要 → 前置（承载已压缩掉的老对话）
    existing_summary = convo.get_summary(thread_id)
    if existing_summary:
        out.append(HumanMessage(
            content=f"【此前对话摘要】{existing_summary}\n\n---\n以下是最近的对话："
        ))

    # 2. 已压缩点之后的全量原文（未触发压缩时 compacted_count=0，即全部）
    compacted = convo.get_compacted_count(thread_id)
    recent = all_msgs[compacted:] if compacted < len(all_msgs) else []

    for m in recent:
        if m["role"] == "user":
            out.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant" and m["content"]:
            out.append(AIMessage(content=m["content"]))

    return out


_COMPACT_SYSTEM = "你是对话压缩助手。用中文，只输出摘要本身，不加任何前缀说明。"

_COMPACT_PROMPT_TEMPLATE = """你在为一个长对话做压缩，目的是让助手在丢失原始消息后仍能无缝继续工作。
必须完整保留（不得省略技术细节）：
1. 用户的核心需求与意图
2. 已完成的工作、关键决策与结论
3. 当前进行到哪一步、正在做什么
4. 涉及的文件路径、函数名、代码位置、接口/字段名
5. 待办事项与下一步计划
用中文，分条输出，只输出摘要本身。

{existing_hint}以下是需要压缩的对话历史：

{old_text}"""


def _compact_if_needed(thread_id: str) -> None:
    """Claude Code 风格同步压缩：估算当前将回放的上下文 token，超预算则把
    「已压缩点 ~ 最近 KEEP_RECENT_TURNS 轮之前」的老消息归纳进结构化摘要。

    在进入 ReAct 循环前同步调用，仅极长对话偶发触发，压缩后立即生效。
    """
    all_msgs = convo.get_messages(thread_id)
    if not all_msgs:
        return

    compacted = convo.get_compacted_count(thread_id)
    existing_summary = convo.get_summary(thread_id)

    # 估算「摘要 + 已压缩点之后原文」的 token（与 _history_messages 回放口径一致）
    replay: list[dict] = []
    if existing_summary:
        replay.append({"content": existing_summary})
    replay.extend(all_msgs[compacted:])
    if _estimate_tokens(replay) < COMPACT_TOKEN_BUDGET:
        return  # 未超预算，无需压缩

    # 待压缩区间：已压缩点 → 最近 KEEP_RECENT_TURNS 轮之前
    keep = KEEP_RECENT_TURNS * 2  # user+assistant 各一条
    end = len(all_msgs) - keep
    old_msgs = all_msgs[compacted:end] if end > compacted else []
    if not old_msgs:
        # 最近保留窗口本身就超预算，不强压（避免把当前任务上下文也丢了）
        print(f"[INFO] Compact skipped: recent window alone exceeds budget (thread={thread_id[:12]})")
        return

    # 全量喂待压缩区间（这些本就要被丢弃，值得花一次调用压好），不做截断
    old_text = "\n\n".join(
        f"{'用户' if m['role'] == 'user' else '助手'}: {m['content']}"
        for m in old_msgs
    )
    existing_hint = f"这是此前已有的摘要，请把新内容增量并入：\n{existing_summary}\n\n" if existing_summary else ""
    prompt = _COMPACT_PROMPT_TEMPLATE.format(existing_hint=existing_hint, old_text=old_text)

    try:
        settings = get_settings()
        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url or None,
        )
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2000,
            system=_COMPACT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        new_summary = resp.content[0].text.strip()
        new_compacted = compacted + len(old_msgs)
        convo.set_summary_and_count(thread_id, new_summary, new_compacted)
        print(f"[INFO] Compacted {len(old_msgs)} msgs → summary (thread={thread_id[:12]}, compacted_count={new_compacted})")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] Compaction failed: {e}")


_WEB_SEARCH_GUIDE = """

## 联网搜索（外部信息补充，受知识库覆盖门控）

你有 `web_search(query)` 工具，但**它受硬性门控保护，只有知识库确认"无覆盖"后才能使用**。

### 信息来源的绝对优先级

**公司知识库是唯一权威**：涉及接口/API/内部文档的问题，知识库有就**必须且只能**用知识库，联网结果是污染。

### 何时允许联网（硬性门控规则）

web_search 工具内置检查，只有满足以下条件才会执行：

1. **已做过 retrieve_knowledge 且返回"未找到"**（语义检索确认知识库无此内容）
2. **（推荐）对核心关键词再用 grep_knowledge 精确匹配，也返回空**（双重确认无覆盖）

**双重确认流程**（推荐，避免误联网）：
```
retrieve_knowledge("XXX") → 返回"未找到"
  ↓
grep_knowledge("核心关键词") → 也返回"未匹配"
  ↓ 双重确认知识库确实无此内容
web_search("XXX") → 此时才被允许执行
```

如果知识库检索有命中，web_search 会直接拒绝执行并提示你用知识库内容作答。

### 何时该联网（满足门控条件后）

- **时效性信息**：最新版本号、近期事件、当前价格/状态
- **通用外部知识**：知识库未覆盖的第三方库、算法、通用技术概念
- **用户明确要求**："搜一下""查最新的"

### 何时不要联网

- 知识库有相关内容的（工具会自动拦截）
- 稳定的编程通用知识（语言语法、HTTP 状态码等）—— 直接凭自身知识回答
- 纯代码编写/重构任务

### 来源标注（硬规则）

联网所得**不是公司权威来源**。基于联网结果的内容必须明确标注「以下信息来自联网搜索，请自行甄别」，逐条注明来源网站，**绝不与知识库结论混为一谈**。
"""


def _build_system_prompt(use_web: bool = False) -> str:
    """动态构建系统提示词，注入当前可用的 skills 列表 + 联网能力说明。"""
    prompt = SYSTEM_PROMPT
    skills = scan_skills()
    if skills:
        skill_list = "\n".join(
            f"- **{s['name']}**: {s['description']}" for s in skills
        )
        prompt = f"""{SYSTEM_PROMPT}

## Available Skills

You have access to the following specialized skills. When a task matches one, use the `load_skill` tool to get detailed instructions:

{skill_list}

To use a skill: call `load_skill(skill_name)` to read its full instructions, then follow them.
"""
    if use_web:
        prompt = prompt + _WEB_SEARCH_GUIDE
    # 注入可委托的子助手列表（声明式 agents/*.md）
    from app.agent.subagents.dispatch import render_available_subagents
    prompt = prompt + render_available_subagents()
    return prompt


# ---------------------------------------------------------------------------
# 主端点
# ---------------------------------------------------------------------------

@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    # 诊断日志：打印请求参数
    print(f"[DEBUG] /api/chat 收到请求: thread_id={req.thread_id[:20]}..., use_knowledge={req.use_knowledge}, use_web={req.use_web}, message={req.message[:30]}...")

    # 1. 不再预注入 RAG 上下文。改为把知识库检索做成工具，
    #    由 agent 在 ReAct 循环里主动调用（retrieve/grep/read），
    #    自行迭代到周全后再作答（见 use_knowledge 分支的工具挂载）。

    # 会话隔离：把工作区切到 workspace/<thread_id>/，本请求内所有文件工具都写这里
    from app.agent.workspace_context import set_session, reset_kb_coverage_state
    set_session(req.thread_id)
    reset_kb_coverage_state()  # 清理上一轮检索状态，确保本轮从零开始

    # 2. 建会话 + 落盘 user 消息（保存原始消息）
    convo.ensure_conversation(req.thread_id, req.message)
    # Claude Code 风格：进循环前同步检查上下文用量，超预算则先压缩老对话
    _compact_if_needed(req.thread_id)
    history = _history_messages(req.thread_id)
    convo.add_message(req.thread_id, "user", req.message)

    # 3. 构建消息列表（Anthropic 格式）
    human = HumanMessage(content=_build_content(req))
    input_messages = history + [human]

    # 转为 Anthropic 字典格式
    anthropic_messages: list[dict] = []
    for msg in input_messages:
        if isinstance(msg, HumanMessage):
            anthropic_messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            anthropic_messages.append({"role": "assistant", "content": msg.content})

    # 4. 准备工具：use_knowledge 开启时才挂知识库工具（关闭则 agent 完全拿不到）
    all_lc_tools = WORKSPACE_TOOLS + TOPOLOGY_TOOLS + SKILL_TOOLS
    if req.use_knowledge:
        all_lc_tools = KNOWLEDGE_TOOLS + all_lc_tools
    if req.use_web:
        all_lc_tools = WEB_TOOLS + all_lc_tools
    anthropic_tools = [_lc_tool_to_anthropic(t) for t in all_lc_tools]
    # 委托工具（subagent 工厂）：不是普通 langchain @tool，只挂 schema，
    # 真正执行由下面 ReAct 循环特判、内联跑子助手循环（见 DISPATCH_TOOL_NAMES）。
    anthropic_tools = anthropic_tools + dispatch_tool_schemas()
    system_prompt = _build_system_prompt(use_web=req.use_web)

    # 诊断日志：打印挂载的工具名
    tool_names = [t.name for t in all_lc_tools] + sorted(DISPATCH_TOOL_NAMES)
    print(f"[DEBUG] 挂载的工具({len(tool_names)}): {tool_names}")

    # 知识库工具名集合，供防幻觉两层复用（强制首轮检索 + 无检索拦截）
    knowledge_tool_names = {t.name for t in KNOWLEDGE_TOOLS}
    # 首轮强制检索的目标工具（防止模型跳过 RAG 直接凭记忆作答）
    force_first_tool = "retrieve_knowledge"

    # 网关不支持 cache_control 时置 False，后续请求彻底剥离缓存字段（降级）
    cache_enabled = True

    async def event_stream():
        nonlocal anthropic_messages, anthropic_tools, cache_enabled

        # 再次设置会话上下文：StreamingResponse 的生成器可能在新的 context 中运行，
        # 不一定继承 handler 里 set_session 的值，故在生成器内重设一次以保证工具隔离生效。
        set_session(req.thread_id)

        settings = get_settings()
        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url or None,
        )

        assistant_text = ""  # 本轮累积的全部文本
        tools_used: list[dict] = []  # 本轮使用的工具
        knowledge_used = False  # 第二层防护：本轮是否调用过任一知识库工具

        interrupted = False  # 客户端是否中途打断

        # ---- ReAct 循环 ----
        for iteration in range(MAX_TOOL_ITERATIONS):
            # 每轮开始检测客户端是否已断开（用户点了停止）
            if await request.is_disconnected():
                interrupted = True
                break
            # 第一层防护：首轮强制调用知识库检索（仅当挂了知识库工具且尚未检索过）。
            # tool_choice=forced 让模型第一步必须调 retrieve_knowledge，
            # 堵死"跳过 RAG 直接凭训练知识作答"这个幻觉入口。
            # Prompt caching：system 转成带断点的 block 列表（连带缓存 tools），
            # 对话历史最近 2 条打滚动断点。网关不支持时 cache_enabled=False 全部降级。
            if cache_enabled:
                stream_kwargs = dict(
                    model=settings.anthropic_model,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    system=_system_blocks(system_prompt),
                    messages=_mark_messages_cache(anthropic_messages),
                    tools=anthropic_tools,
                )
            else:
                stream_kwargs = dict(
                    model=settings.anthropic_model,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    system=system_prompt,
                    messages=anthropic_messages,
                    tools=anthropic_tools,
                )
            if (
                req.use_knowledge
                and req.force_retrieval
                and anthropic_tools
                and iteration == 0
                and not knowledge_used
                and any(t["name"] == force_first_tool for t in anthropic_tools)
            ):
                stream_kwargs["tool_choice"] = {"type": "tool", "name": force_first_tool}

            try:
                # 改用 create(stream=True) 拿原始事件流，绕开 stream() 的自动累积逻辑
                # 网关返回 text: null 会导致 SDK 内部累积崩溃，这里完全避开那层封装
                stream_kwargs["stream"] = True

                # 手动累积 final_message 的各个字段
                final_msg_snapshot = {
                    "id": None,
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": stream_kwargs["model"],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                }

                stream = await client.messages.create(**stream_kwargs)

                async for event in stream:
                    # 客户端断开（用户点停止）→ 立即停止生成
                    if await request.is_disconnected():
                        interrupted = True
                        break

                    # 手动解析事件，累积到 snapshot
                    if event.type == "message_start":
                        msg_dict = event.message.model_dump() if hasattr(event.message, 'model_dump') else vars(event.message)
                        final_msg_snapshot.update(msg_dict)
                        # 缓存命中诊断：cache_read>0 说明前缀命中；持续为 0 说明有静默失效因子
                        u = msg_dict.get("usage") or {}
                        cr = u.get("cache_read_input_tokens")
                        cc = u.get("cache_creation_input_tokens")
                        if cr is not None or cc is not None:
                            print(f"[CACHE] iter={iteration} read={cr or 0} "
                                  f"write={cc or 0} input={u.get('input_tokens', 0)}")

                    elif event.type == "content_block_start":
                        # 防御性初始化：确保 text 字段不为 None
                        block = event.content_block.model_dump() if hasattr(event.content_block, 'model_dump') else vars(event.content_block)
                        if block.get("type") == "text" and block.get("text") is None:
                            block["text"] = ""  # 修复网关返回的 null
                        final_msg_snapshot["content"].append(block)

                    elif event.type == "content_block_delta":
                        idx = event.index
                        delta = event.delta
                        if delta.type == "text_delta":
                            # 流式文本增量
                            text = delta.text
                            assistant_text += text
                            yield _sse("token", {"text": text})
                            # 累积到 snapshot
                            if idx < len(final_msg_snapshot["content"]):
                                block = final_msg_snapshot["content"][idx]
                                if block.get("type") == "text":
                                    if block.get("text") is None:
                                        block["text"] = ""  # 再次防御
                                    block["text"] += text

                        elif delta.type == "input_json_delta":
                            # 工具调用的 JSON 增量（累积原始 JSON 字符串）
                            if idx < len(final_msg_snapshot["content"]):
                                block = final_msg_snapshot["content"][idx]
                                if block.get("type") == "tool_use":
                                    # 累积 partial_json（后续统一解析）
                                    if "_json_buf" not in block:
                                        block["_json_buf"] = ""
                                    block["_json_buf"] += delta.partial_json

                    elif event.type == "content_block_stop":
                        # 内容块结束：若是 tool_use，解析完整 JSON
                        idx = event.index
                        if idx < len(final_msg_snapshot["content"]):
                            block = final_msg_snapshot["content"][idx]
                            if block.get("type") == "tool_use" and "_json_buf" in block:
                                import json
                                try:
                                    block["input"] = json.loads(block["_json_buf"])
                                except json.JSONDecodeError:
                                    block["input"] = {}  # 解析失败兜底
                                del block["_json_buf"]  # 清理临时字段

                    elif event.type == "message_delta":
                        # 更新 stop_reason 等元信息
                        delta_dict = event.delta.model_dump() if hasattr(event.delta, 'model_dump') else vars(event.delta)
                        if "stop_reason" in delta_dict:
                            final_msg_snapshot["stop_reason"] = delta_dict["stop_reason"]
                        if hasattr(event, "usage"):
                            usage_dict = event.usage.model_dump() if hasattr(event.usage, 'model_dump') else vars(event.usage)
                            final_msg_snapshot["usage"]["output_tokens"] = usage_dict.get("output_tokens", 0)

                    elif event.type == "message_stop":
                        # 消息结束
                        pass

                if interrupted:
                    break

                # 将 snapshot 转换为类似 Message 对象的结构（用 SimpleNamespace 模拟）
                from types import SimpleNamespace
                final_msg = SimpleNamespace(
                    id=final_msg_snapshot["id"],
                    type=final_msg_snapshot["type"],
                    role=final_msg_snapshot["role"],
                    content=[SimpleNamespace(**b) for b in final_msg_snapshot["content"]],
                    model=final_msg_snapshot["model"],
                    stop_reason=final_msg_snapshot["stop_reason"],
                    stop_sequence=final_msg_snapshot["stop_sequence"],
                    usage=SimpleNamespace(**final_msg_snapshot["usage"]),
                )

            except anthropic.BadRequestError as e:
                err = str(e).lower()
                # 网关可能不支持 cache_control → 关闭缓存重试（不影响功能，仅失去命中）
                if cache_enabled and ("cache_control" in err or "cache" in err):
                    print("[WARN] cache_control not supported by gateway, disabling prompt caching")
                    cache_enabled = False
                    continue
                # 网关可能不支持 tools 参数 → 降级为无工具模式重试
                if "tool" in err and len(anthropic_tools) > 0:
                    print(f"[WARN] Tools not supported by gateway, falling back to no-tools mode")
                    anthropic_tools = []
                    continue
                yield _sse("error", {"message": str(e)})
                return
            except Exception as e:
                traceback.print_exc()
                if assistant_text:
                    convo.add_message(req.thread_id, "assistant", assistant_text, tools_used)
                yield _sse("error", {"message": str(e)})
                return

            # 检查 stop_reason：如果是 max_tokens 截断，让模型继续
            stop_reason = getattr(final_msg, "stop_reason", None)
            print(f"[DEBUG] Iteration {iteration}, stop_reason={stop_reason}, assistant_text length={len(assistant_text)}")

            if stop_reason == "max_tokens":
                # 模型输出被截断，将已产出的内容加入历史并继续
                print("[INFO] Response truncated by max_tokens, continuing...")
                anthropic_messages.append({
                    "role": "assistant",
                    "content": [vars(b) if hasattr(b, "__dict__") else b.model_dump() for b in final_msg.content],
                })
                anthropic_messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": "你的回复被截断了，请从截断处继续。"}],
                })
                continue  # 不检查 tool_use，直接下一轮让模型继续

            # 分析响应中有无 tool_use
            tool_blocks = [b for b in final_msg.content if b.type == "tool_use"]

            if not tool_blocks:
                # 没有工具调用 → 本轮结束
                print(f"[INFO] No tool_use blocks, ending ReAct loop. Final assistant_text length: {len(assistant_text)}")
                break

            # 过滤掉不完整的 tool_use（id 或 name 为空）
            valid_tool_blocks = [b for b in tool_blocks if b.id and b.name]
            if len(valid_tool_blocks) < len(tool_blocks):
                print(f"[WARN] Skipped {len(tool_blocks) - len(valid_tool_blocks)} incomplete tool_use blocks")

            # ---- 执行工具调用 ----
            # 将完整的 assistant 消息（含 text + tool_use）加入历史
            anthropic_messages.append({
                "role": "assistant",
                "content": [vars(b) if hasattr(b, "__dict__") else b.model_dump() for b in final_msg.content],
            })

            tool_results: list[dict] = []
            for tb in valid_tool_blocks:
                tool_name = tb.name
                tool_input = tb.input if isinstance(tb.input, dict) else {}

                # 通知前端工具开始（带 id，供前端把 start/done 对应起来做进度条）
                yield _sse("tool", {"id": tb.id, "name": tool_name, "input": tool_input})
                tools_used.append({"name": tool_name, "input": tool_input})
                if tool_name in knowledge_tool_names:
                    knowledge_used = True

                # ── 委托工具特判：内联跑子助手循环，透传其内部事件 ──
                # 不走 _execute_tool（那是同步的），而是 async for 消费 run_subagent
                # 的事件生成器，逐个翻译成 subagent_* SSE 事件推给前端，
                # 最后把子助手的 result 作为本工具的 tool_result 回喂给主 AI。
                if tool_name in DISPATCH_TOOL_NAMES:
                    # 委托即视为「已尽调查责任」，避免 Layer-2 免责误标
                    # （子助手内部才是真正查知识库、产出的地方）。
                    knowledge_used = True
                    sub_result = ""
                    sub_error = None
                    async for ev in _run_dispatch(tool_name, tool_input, tb.id):
                        kind = ev.get("kind")
                        if kind == "tool":
                            yield _sse("subagent_tool", {
                                "id": ev.get("id"),
                                "parent_id": tb.id,
                                "name": ev.get("name"),
                                "input": ev.get("input", {}),
                            })
                        elif kind == "tool_done":
                            yield _sse("subagent_tool_done", {
                                "id": ev.get("id"),
                                "parent_id": tb.id,
                                "name": ev.get("name"),
                                "ok": ev.get("ok", True),
                            })
                        elif kind == "file_written":
                            # 复用主链路的实时预览事件，子助手写的文件也能即时可见
                            yield _sse("file_written", {
                                "path": ev.get("path"),
                                "content": ev.get("content"),
                                "name": ev.get("name"),
                            })
                        elif kind == "text":
                            # 子助手的阶段性文本（告警等）——作为 subagent 提示透传
                            yield _sse("subagent_text", {"parent_id": tb.id, "text": ev.get("text", "")})
                        elif kind == "result":
                            sub_result = ev.get("text", "")
                        elif kind == "error":
                            sub_error = ev.get("message", "子助手执行失败")

                    result_text = sub_error if sub_error else (sub_result or "（子助手无输出）")
                    ok = sub_error is None
                    yield _sse("tool_done", {"id": tb.id, "name": tool_name, "ok": ok})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tb.id,
                        "content": result_text,
                    })
                    continue

                # 执行工具
                result_text = _execute_tool(tool_name, tool_input)

                # 检测 artifact 更新，推送实时预览事件
                if result_text.startswith("__ARTIFACT_UPDATE__:"):
                    parts = result_text.split(":", 2)
                    if len(parts) >= 2:
                        artifact_id = parts[1]
                        artifact_data = get_artifact_content(artifact_id)
                        if artifact_data:
                            yield _sse("artifact_update", {
                                "id": artifact_id,
                                "title": artifact_data["title"],
                                "type": artifact_data["type"],
                                "content": artifact_data["content"],
                            })

                # 通知前端工具完成（写入类工具据此把进度条推到 100%）
                ok = not str(result_text).startswith(("Tool execution error", "路径越界", "Unknown tool"))
                done_payload = {"id": tb.id, "name": tool_name, "ok": ok}
                yield _sse("tool_done", done_payload)

                # retrieve_knowledge 执行后：把累积的段落级引用发给前端（全量累积，前端整体替换）
                if tool_name == "retrieve_knowledge":
                    from app.agent.workspace_context import get_citations
                    yield _sse("citations", {"items": get_citations()})

                # 写文件类工具成功后：解析真实存储路径 + 内容，推给前端实时预览 + 刷新工作区
                if tool_name in ("write_file", "append_file", "edit_file") and ok:
                    info = resolve_written_file(tool_input.get("path", ""))
                    if info:
                        yield _sse("file_written", {
                            "path": info["path"],
                            "content": info["content"],
                            "name": info["path"].rsplit("/", 1)[-1],
                        })

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tb.id,
                    "content": result_text,
                })

            # 将工具结果作为 user 消息加入
            anthropic_messages.append({"role": "user", "content": tool_results})
        else:
            # for 循环正常结束（没 break）→ 达到最大迭代次数
            print(f"[WARN] Reached max tool iterations ({MAX_TOOL_ITERATIONS}), response may be incomplete")

        # ---- 循环结束 ----
        # 用户中途打断：保留已生成的部分内容并落盘（标记为已中断），不再走后续防护
        if interrupted:
            print("[INFO] 用户中途打断本轮生成")
            if assistant_text.strip():
                marked = f"{assistant_text}\n\n_（已被用户中断）_"
                convo.add_message(req.thread_id, "assistant", marked, tools_used)
            # 尝试通知前端（若连接还活着）
            yield _sse("interrupted", {})
            return

        # 第二层防护已禁用（用户要求去掉未经检索的免责警告）
        # if req.use_knowledge and not knowledge_used and assistant_text.strip():
        #     disclaimer = (
        #         "⚠️ 本回答未经知识库检索核实，可能存在不准确或与公司文档不符之处，"
        #         "请谨慎参考。"
        #     )
        #     print("[WARN] Layer-2 guard: 回答未经知识库检索，已标注免责")
        #     yield _sse("warning", {"message": disclaimer})
        #     assistant_text = f"{disclaimer}\n\n{assistant_text}"

        # DEBUG: 检查最终答案是否包含警告
        if "未经知识库检索" in assistant_text:
            print(f"[DEBUG chat.py] ⚠️ 检测到警告文字在最终答案中！")
            print(f"[DEBUG chat.py] knowledge_used={knowledge_used}, use_knowledge={req.use_knowledge}")
            print(f"[DEBUG chat.py] 答案前150字: {assistant_text[:150]}")

        convo.add_message(req.thread_id, "assistant", assistant_text, tools_used)
        yield _sse("done", {})
        # 压缩改为下轮请求进入前同步检查（见 _compact_if_needed），此处不再异步摘要

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
