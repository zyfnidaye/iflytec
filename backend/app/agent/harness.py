"""Agent Harness - 通用策略约束框架

核心理念：Policy + Checkpoint
- Policy：声明式定义"在什么状态下必须做什么"
- Checkpoint：在 ReAct 循环的关键位置自动检查和强制执行策略

适用场景：
- 知识库检索后必须联网（已实现的例子）
- 修改文件前必须先读取
- 高风险操作前必须确认
- 答案必须包含引用
- ...任何"该做X却不做"的约束

设计目标：
1. 可扩展：新增约束只需添加 Policy，不改主循环
2. 可测试：每个 Policy 独立，可单元测试
3. 可观测：每次拦截/放行都有日志
4. 低侵入：主循环只插入 checkpoint 调用，不改业务逻辑
"""
from abc import ABC, abstractmethod
from typing import Any, Optional
from dataclasses import dataclass


@dataclass
class AgentState:
    """Agent 当前状态快照（从 contextvars、工具调用历史等收集）"""
    # 知识库状态
    kb_retrieve_done: bool = False
    kb_grep_done: bool = False
    kb_has_coverage: bool = False

    # 工具使用历史
    tools_called: list[str] = None  # 本轮调用过的工具名
    web_used: bool = False

    # 循环状态
    iteration: int = 0
    max_iterations: int = 10

    # 当前答案（如果是输出验证阶段）
    current_answer: Optional[str] = None

    def __post_init__(self):
        if self.tools_called is None:
            self.tools_called = []


@dataclass
class PolicyViolation:
    """策略违规结果"""
    violated: bool  # 是否违规
    policy_name: str
    reason: str  # 为什么违规
    correction_prompt: str  # 强制纠正的提示词（追加给模型）
    severity: str = "high"  # high/medium/low，决定是否硬拦截


class Policy(ABC):
    """策略基类"""
    name: str = "unnamed_policy"

    @abstractmethod
    def check(self, state: AgentState) -> PolicyViolation:
        """检查当前状态是否违反策略。

        Returns:
            PolicyViolation.violated == True 表示违规需要纠正
        """
        pass


# ===== 具体策略实现 =====

class KnowledgeBeforeWebPolicy(Policy):
    """策略：知识库无覆盖时，必须联网才能作答"""
    name = "knowledge_before_web"

    def check(self, state: AgentState) -> PolicyViolation:
        # 条件：retrieve 做了 + 无覆盖 + 没联网 + 答案包含时效性断言
        if not state.kb_retrieve_done:
            return PolicyViolation(
                violated=False,
                policy_name=self.name,
                reason="尚未检索知识库，暂不判定",
                correction_prompt="",
            )

        if state.kb_has_coverage:
            # 知识库有内容，不需要联网，放行
            return PolicyViolation(
                violated=False,
                policy_name=self.name,
                reason="知识库已覆盖",
                correction_prompt="",
            )

        # 知识库无覆盖 + 没联网
        if not state.web_used and state.current_answer:
            # 检测答案是否包含时效性断言
            from app.agent.answer_validator import contains_time_sensitive_claims

            risk = contains_time_sensitive_claims(state.current_answer, strict=False)
            if risk["has_risk"]:
                return PolicyViolation(
                    violated=True,
                    policy_name=self.name,
                    reason=f"知识库无覆盖，答案含时效性断言 {risk['signals']}，但未联网核实",
                    correction_prompt=(
                        f"⚠️ 你的回答包含时效性信息（{', '.join(risk['examples'][:2])}），"
                        "但知识库确认无此内容且你未联网核实。这可能导致过时信息。\n"
                        "请先用 web_search 确认最新情况后再作答。"
                    ),
                    severity="high",
                )

        return PolicyViolation(
            violated=False,
            policy_name=self.name,
            reason="未触发拦截条件",
            correction_prompt="",
        )


class ReadBeforeEditPolicy(Policy):
    """策略：编辑文件前必须先读取（避免盲改）"""
    name = "read_before_edit"

    def check(self, state: AgentState) -> PolicyViolation:
        # 简化实现：检查工具调用序列
        # 真实实现需要跟踪"哪些文件被 edit 了、是否之前 read 过"
        if "edit_file" in state.tools_called or "write_file" in state.tools_called:
            # TODO: 实际需要文件级别的状态跟踪
            # 这里只是演示框架，真实要从 workspace_context 里拿文件操作历史
            pass

        return PolicyViolation(
            violated=False,
            policy_name=self.name,
            reason="演示策略，未实际检查",
            correction_prompt="",
        )


class MustCiteSourcePolicy(Policy):
    """策略：答案必须包含引用来源（知识库 doc_id 或联网 URL）"""
    name = "must_cite_source"

    def check(self, state: AgentState) -> PolicyViolation:
        if not state.current_answer:
            return PolicyViolation(violated=False, policy_name=self.name, reason="无答案", correction_prompt="")

        # 检测是否包含引用标记
        import re
        has_doc_cite = bool(re.search(r"doc_id[=:]\s*\d+", state.current_answer))
        has_url_cite = bool(re.search(r"https?://", state.current_answer))
        has_web_disclaimer = "联网搜索" in state.current_answer

        if state.kb_has_coverage and not has_doc_cite:
            return PolicyViolation(
                violated=True,
                policy_name=self.name,
                reason="知识库有覆盖，但答案未引用 doc_id",
                correction_prompt="你的回答基于知识库，但未标注 doc_id。请在答案中明确引用文档来源。",
                severity="medium",
            )

        if state.web_used and not (has_url_cite or has_web_disclaimer):
            return PolicyViolation(
                violated=True,
                policy_name=self.name,
                reason="使用了联网，但答案未标注来源",
                correction_prompt="你使用了联网搜索，但未在答案中标注来源网站或声明这是联网所得。请补充来源标注。",
                severity="medium",
            )

        return PolicyViolation(violated=False, policy_name=self.name, reason="引用完整", correction_prompt="")


# ===== Harness 核心引擎 =====

class AgentHarness:
    """Agent 约束引擎"""

    def __init__(self, policies: list[Policy]):
        self.policies = policies

    def check_all(self, state: AgentState) -> list[PolicyViolation]:
        """运行所有策略检查"""
        violations = []
        for policy in self.policies:
            result = policy.check(state)
            if result.violated:
                violations.append(result)
        return violations

    def enforce(self, state: AgentState, severity_threshold: str = "high") -> Optional[str]:
        """执行策略检查，返回需要追加的纠正提示（如果有）。

        Args:
            severity_threshold: 只拦截此严重级别及以上的违规
                - "high": 只拦截高危违规（默认，适合生产）
                - "medium": 拦截中危及以上
                - "low": 拦截所有违规（严格模式）

        Returns:
            如果有违规，返回合并的 correction_prompt；否则返回 None
        """
        violations = self.check_all(state)

        severity_order = {"high": 3, "medium": 2, "low": 1}
        threshold_level = severity_order.get(severity_threshold, 3)

        # 过滤出达到阈值的违规
        serious_violations = [
            v for v in violations if severity_order.get(v.severity, 0) >= threshold_level
        ]

        if not serious_violations:
            return None

        # 合并多个违规的纠正提示
        prompts = [v.correction_prompt for v in serious_violations if v.correction_prompt]
        combined = "\n\n".join(prompts)

        # 记录日志（生产环境应该用 logging）
        for v in serious_violations:
            print(f"[HARNESS] Policy violated: {v.policy_name} | {v.reason}")

        return combined


# ===== 默认策略集 =====

def get_default_harness() -> AgentHarness:
    """获取默认的 Harness 实例（包含当前启用的所有策略）"""
    return AgentHarness(
        policies=[
            KnowledgeBeforeWebPolicy(),
            # ReadBeforeEditPolicy(),  # 可选
            MustCiteSourcePolicy(),
        ]
    )
