"""Agent Harness 集成示例

展示如何在现有 ReAct 循环（chat.py）里插入 Checkpoint，
不改变循环主逻辑，只在关键位置调用 Harness 验证。

三个 Checkpoint 位置：
1. 工具执行前（pre-tool）   - 可选，工具层硬门已覆盖
2. 每轮迭代后（mid-loop）   - 主动引导
3. 循环结束输出前（pre-output）- 最后守门员
"""

# ===== 伪代码示例：chat.py 的改造 =====

"""
@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    # 初始化
    from app.agent.workspace_context import set_session, reset_kb_coverage_state
    from app.agent.harness import get_default_harness, AgentState

    set_session(req.thread_id)
    reset_kb_coverage_state()

    # ★ 创建 Harness 实例
    harness = get_default_harness()

    # ... 准备工具、历史消息 ...

    async def event_stream():
        iteration = 0
        assistant_text = ""
        tools_used = []
        web_used = False
        max_iterations = 10

        while iteration < max_iterations:
            iteration += 1

            # ---- 调用模型生成 ----
            async with client.messages.stream(...) as stream:
                async for text in stream.text_stream:
                    assistant_text += text
                    yield _sse("token", {"text": text})

                final_msg = await stream.get_final_message()

            # ---- 工具调用处理 ----
            tool_blocks = [b for b in final_msg.content if b.type == "tool_use"]
            if not tool_blocks:
                # 没有工具调用 → 循环结束，进入输出验证
                break

            for tb in tool_blocks:
                tool_name = tb.name
                tool_input = tb.input

                # 执行工具
                result_text = _execute_tool(tool_name, tool_input)
                tools_used.append({"name": tool_name, "input": tool_input})

                if tool_name == "web_search":
                    web_used = True

                # ... 其他工具处理 ...

            # ★ Checkpoint 2: 每轮迭代后检查（主动引导）
            # 构建当前状态快照
            from app.agent.workspace_context import get_kb_coverage_state
            kb_state = get_kb_coverage_state()

            current_state = AgentState(
                kb_retrieve_done=kb_state["retrieve_done"],
                kb_grep_done=kb_state["grep_done"],
                kb_has_coverage=kb_state["has_coverage"],
                tools_called=[t["name"] for t in tools_used],
                web_used=web_used,
                iteration=iteration,
                max_iterations=max_iterations,
                current_answer=None,  # 中期检查不看答案
            )

            # 运行策略检查（但只做"引导提示"，不强制拦截）
            # 这里用 severity_threshold="low" 获取所有建议，但不中断
            hint = harness.enforce(current_state, severity_threshold="medium")
            if hint and iteration < max_iterations - 1:
                # 有违规倾向，注入提示到下一轮（可选：作为 system 或隐式 user 消息）
                # 这里演示：在工具结果后追加一个提示
                # 真实实现可能需要更优雅的注入方式
                pass  # 暂不实现，保持简洁

        # ★ Checkpoint 3: 输出验证（最后守门员）
        from app.agent.workspace_context import get_kb_coverage_state
        kb_state = get_kb_coverage_state()

        final_state = AgentState(
            kb_retrieve_done=kb_state["retrieve_done"],
            kb_grep_done=kb_state["grep_done"],
            kb_has_coverage=kb_state["has_coverage"],
            tools_called=[t["name"] for t in tools_used],
            web_used=web_used,
            iteration=iteration,
            max_iterations=max_iterations,
            current_answer=assistant_text.strip(),  # ★ 完整答案
        )

        # 执行严格检查
        correction_needed = harness.enforce(final_state, severity_threshold="high")

        if correction_needed and iteration < max_iterations:
            # ★ 拦截：答案不合格，强制追加一轮
            print(f"[HARNESS] 拦截输出，要求重做: {correction_needed[:100]}")

            # 把纠正提示作为 user 消息追加
            anthropic_messages.append({
                "role": "assistant",
                "content": assistant_text,  # 先记录模型刚才的答案
            })
            anthropic_messages.append({
                "role": "user",
                "content": correction_needed,  # 系统强制要求
            })

            # 清空当前答案，重新进入循环
            assistant_text = ""
            iteration = 0  # 重置（或继续累加，看你的策略）

            # ★ 回到循环开头（实际实现中可能需要重构成 while True + 状态机）
            # 这里演示意图，真实代码需要调整循环结构
            # continue  # 伪代码，实际需要重新 stream

            # 为简化演示，这里用递归重试（生产不推荐，应该在同一循环内）
            # 真实实现：标记 retry_needed=True，在主循环顶部检查并重新生成

        # ★ 通过所有检查 或 达到最大重试次数 → 返回答案
        if assistant_text.strip():
            # ... 原有的后置处理（知识库免责声明等）...
            convo.add_message(req.thread_id, "assistant", assistant_text, tools_used)
            yield _sse("done", {})

    return StreamingResponse(event_stream(), ...)
"""


# ===== 实际集成的最小侵入方案 =====

"""
关键点：
1. 在 chat() 开头创建 harness 实例
2. 在循环结束、准备返回前，构建 AgentState 并调用 harness.enforce()
3. 如果返回 correction_needed，追加消息并设置标志位重新生成

最小改动（只加 Checkpoint 3，输出验证）：

```python
# chat.py 的 event_stream() 函数里，ReAct 循环结束后

# ... 循环结束，没有更多工具调用 ...

# ★ 新增：输出验证 Checkpoint
from app.agent.harness import get_default_harness, AgentState
from app.agent.workspace_context import get_kb_coverage_state

harness = get_default_harness()
kb_state = get_kb_coverage_state()

final_state = AgentState(
    kb_retrieve_done=kb_state["retrieve_done"],
    kb_has_coverage=kb_state["has_coverage"],
    tools_called=[t["name"] for t in tools_used],
    web_used=web_used,
    iteration=iteration,
    current_answer=assistant_text.strip(),
)

correction = harness.enforce(final_state, severity_threshold="high")

if correction and iteration < max_iterations:
    # 拦截并重试
    anthropic_messages.append({"role": "assistant", "content": assistant_text})
    anthropic_messages.append({"role": "user", "content": correction})

    # 重新生成（需要重构循环为 retry_loop）
    # 演示：设置标志并 continue
    retry_needed = True
    assistant_text = ""
    # ... 回到循环开头 ...

# 没有拦截 → 正常返回
convo.add_message(...)
yield _sse("done", {})
```
"""


# ===== 扩展新策略的示例 =====

"""
场景：强制要求高风险操作（删除文件、修改配置）前必须用户确认

1. 定义策略：

class ConfirmBeforeDeletePolicy(Policy):
    name = "confirm_before_delete"

    def check(self, state: AgentState) -> PolicyViolation:
        if "delete_file" in state.tools_called:
            # 检查是否有用户明确确认（从 state 扩展字段读取）
            # if not state.user_confirmed_delete:
            #     return PolicyViolation(...)
            pass
        return PolicyViolation(violated=False, ...)

2. 注册到 Harness：

def get_production_harness():
    return AgentHarness(policies=[
        KnowledgeBeforeWebPolicy(),
        MustCiteSourcePolicy(),
        ConfirmBeforeDeletePolicy(),  # ← 新增
    ])

3. 完成！主循环代码一行不改，策略自动生效。
"""
