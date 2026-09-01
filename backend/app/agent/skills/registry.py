"""Skill registry: scan, validate, and load Anthropic Agent Skills."""
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings


def _skills_root() -> Path:
    """技能存储根目录。"""
    return get_settings().store_path / "skills"


def scan_skills() -> list[dict[str, Any]]:
    """扫描所有已上传的 skills，返回 [{name, description, path}, ...]。

    只返回包含有效 SKILL.md 的文件夹。
    """
    root = _skills_root()
    if not root.exists():
        return []

    skills = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            continue

        try:
            name, description = _parse_frontmatter(skill_md)
            skills.append({
                "name": name,
                "description": description,
                "path": str(entry.relative_to(root)),
            })
        except Exception:
            # 解析失败的跳过
            continue

    return sorted(skills, key=lambda s: s["name"])


def get_skill_md(skill_name: str) -> str:
    """读取指定 skill 的完整 SKILL.md 内容。"""
    skill_dir = _resolve_skill_dir(skill_name)
    skill_md = _find_skill_md(skill_dir)
    if skill_md is None:
        raise FileNotFoundError(f"Skill '{skill_name}' 的 SKILL.md 或 skill.md 不存在")
    return skill_md.read_text(encoding="utf-8")


def read_skill_content(skill_name: str) -> str:
    """读取指定 skill 的完整内容（别名，供 API 调用）。"""
    return get_skill_md(skill_name)


def get_skill_resource(skill_name: str, filename: str) -> str:
    """读取 skill 文件夹内的支持文件（如 reference.md、script.py）。"""
    skill_dir = _resolve_skill_dir(skill_name)
    # 防止路径穿越
    target = (skill_dir / filename).resolve()
    try:
        target.relative_to(skill_dir)
    except ValueError:
        raise ValueError(f"文件路径越界: {filename}")

    if not target.exists():
        raise FileNotFoundError(f"资源文件不存在: {filename}")
    if not target.is_file():
        raise ValueError(f"不是文件: {filename}")

    return target.read_text(encoding="utf-8")


def validate_skill(skill_path: Path) -> tuple[bool, str]:
    """验证 skill 文件夹结构是否符合规范。

    Returns:
        (valid, error_message)  如果 valid=True，error_message 为空
    """
    skill_md = _find_skill_md(skill_path)
    if skill_md is None:
        return False, "缺少 SKILL.md 或 skill.md 文件"

    try:
        name, description = _parse_frontmatter(skill_md)
        if not name or not description:
            return False, "SKILL.md frontmatter 必须包含 name 和 description"
        return True, ""
    except Exception as e:
        return False, f"解析 SKILL.md 失败: {e}"


def _find_skill_md(skill_path: Path) -> Path | None:
    """查找技能文件，支持 SKILL.md 或 skill.md（不区分大小写）。

    Returns:
        Path 对象，如果找不到返回 None
    """
    # 优先查找 SKILL.md（大写）
    skill_md_upper = skill_path / "SKILL.md"
    if skill_md_upper.exists():
        return skill_md_upper

    # 查找 skill.md（小写）
    skill_md_lower = skill_path / "skill.md"
    if skill_md_lower.exists():
        return skill_md_lower

    # 兼容其他大小写组合
    for file in skill_path.iterdir():
        if file.is_file() and file.name.lower() == "skill.md":
            return file

    return None


def delete_skill(skill_name: str) -> None:
    """删除指定 skill 的整个文件夹。"""
    import shutil
    skill_dir = _resolve_skill_dir(skill_name)
    if skill_dir.exists():
        shutil.rmtree(skill_dir)


def _resolve_skill_dir(skill_name: str) -> Path:
    """解析 skill 目录，校验存在性。"""
    root = _skills_root()
    skill_dir = root / skill_name
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise FileNotFoundError(f"Skill '{skill_name}' 不存在")
    return skill_dir


def _parse_frontmatter(skill_md: Path) -> tuple[str, str]:
    """从 SKILL.md 提取 frontmatter 中的 name 和 description。

    如果没有 frontmatter，则自动生成默认值。

    Returns:
        (name, description)
    """
    content = skill_md.read_text(encoding="utf-8")

    # 如果没有 frontmatter，使用默认值
    if not content.startswith("---\n"):
        # 从文件名生成默认 name
        skill_name = skill_md.parent.name
        return skill_name, f"技能: {skill_name}"

    # 找到第二个 ---
    end = content.find("\n---\n", 4)
    if end == -1:
        raise ValueError("SKILL.md frontmatter 未正确闭合")

    frontmatter_text = content[4:end]
    meta = yaml.safe_load(frontmatter_text)

    if not isinstance(meta, dict):
        raise ValueError("frontmatter 必须是 YAML 字典")

    name = meta.get("name", "").strip()
    description = meta.get("description", "").strip()

    if not name or not description:
        raise ValueError("frontmatter 必须包含 name 和 description 字段")

    return name, description


# ─────────────────────────────────────────────────────────────────────────
# Agent 定义（subagent 工厂用）
#
# Anthropic Agent Skills 约定：skill 目录下的 agents/*.md 用 YAML frontmatter
# 声明一个可派生的子助手。frontmatter 字段：
#   name        —— 子助手标识（工具名会基于它派生）
#   description —— 子助手能干什么（注入主 AI 系统提示词，决定何时委托）
#   model       —— （可选）子助手用的模型，覆盖全局 subagent_model 默认值
#   tools       —— （可选）子助手可用的工具白名单（工具名列表）。缺省则用
#                  工厂的安全默认集。这是子助手的安全边界。
# frontmatter 之后的正文是子助手的系统提示词（执行指令）。
# ─────────────────────────────────────────────────────────────────────────


def _split_frontmatter(md_text: str) -> tuple[dict, str]:
    """把一个 markdown 文本拆成 (frontmatter dict, body)。

    无 frontmatter 时返回 ({}, 全文)。frontmatter 未闭合则抛 ValueError。
    """
    if not md_text.startswith("---\n"):
        return {}, md_text
    end = md_text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("frontmatter 未正确闭合（缺少第二个 ---）")
    meta = yaml.safe_load(md_text[4:end])
    if not isinstance(meta, dict):
        raise ValueError("frontmatter 必须是 YAML 字典")
    body = md_text[end + len("\n---\n"):]
    return meta, body


def _normalize_agent_meta(meta: dict, body: str, skill_name: str, source: str) -> dict:
    """把原始 frontmatter 规整成 agent 定义 dict。校验必填字段。"""
    name = str(meta.get("name", "")).strip()
    description = str(meta.get("description", "")).strip()
    if not name or not description:
        raise ValueError(f"agent 定义缺少 name 或 description（{source}）")

    # 注意：YAML 里空值 `model:` 会解析成 None（key 存在但值为空），
    # 不能用 meta.get("model", "")——那样只在 key 缺失时给默认。用 `or ""` 兜住 None。
    model = str(meta.get("model") or "").strip()

    # tools 支持列表或逗号分隔字符串；缺省为 None（由工厂用安全默认集）
    raw_tools = meta.get("tools")
    tools: list[str] | None
    if raw_tools is None:
        tools = None
    elif isinstance(raw_tools, str):
        tools = [t.strip() for t in raw_tools.split(",") if t.strip()]
    elif isinstance(raw_tools, list):
        tools = [str(t).strip() for t in raw_tools if str(t).strip()]
    else:
        raise ValueError(f"agent 定义的 tools 必须是列表或逗号分隔字符串（{source}）")

    return {
        "name": name,
        "description": description,
        "model": model,           # 空串表示用全局默认
        "tools": tools,           # None 表示用工厂默认白名单
        "system_prompt": body.strip(),
        "skill": skill_name,      # 归属的 skill（读取资源、定位目录用）
        "source": source,         # 定义来源（诊断用）
    }


def scan_agent_defs() -> list[dict[str, Any]]:
    """扫描所有 skill 目录下 agents/*.md 的子助手定义。

    返回规整后的 agent 定义列表（见 _normalize_agent_meta）。解析失败的单个
    文件跳过，不影响其余。名字冲突时后扫描到的覆盖（按 skill 名排序保证稳定）。
    """
    root = _skills_root()
    if not root.exists():
        return []

    defs: list[dict[str, Any]] = []
    for skill_dir in sorted(root.iterdir(), key=lambda p: p.name):
        if not skill_dir.is_dir():
            continue
        agents_dir = skill_dir / "agents"
        if not agents_dir.is_dir():
            continue
        for md in sorted(agents_dir.glob("*.md")):
            try:
                meta, body = _split_frontmatter(md.read_text(encoding="utf-8"))
                if not meta:
                    continue  # 没有 frontmatter 的 md 不是 agent 定义
                defs.append(
                    _normalize_agent_meta(meta, body, skill_dir.name, f"{skill_dir.name}/agents/{md.name}")
                )
            except Exception:
                continue
    return defs


def get_agent_def(agent_name: str) -> dict[str, Any] | None:
    """按 name 取一个 agent 定义；找不到返回 None。"""
    for d in scan_agent_defs():
        if d["name"] == agent_name:
            return d
    return None
