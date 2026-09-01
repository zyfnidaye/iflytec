"""Subagent 工厂：把「子助手」做成可派生的通用能力。

两种入口（见 tools.py）：
- 声明式：skill 的 agents/*.md 用 frontmatter 定义子助手，工厂据此派生专属工具。
- 临时内联：主 AI 用 spawn_subagent 现场定义一个一次性子助手。

两者最终都调 factory.run_subagent —— 一个自包含的 ReAct 循环（异步生成器），
边执行边 yield 内部工具事件，供 chat.py 内联消费并透传到前端。
"""
