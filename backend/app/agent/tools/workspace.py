"""工作区文件工具。

所有读写都被限制在 WORKSPACE_ROOT 目录内，防止路径穿越（../）攻击。
这是智能体操作文件系统的唯一安全边界。

工作区 → 技能区：publish_skill 工具可将工作区内的 skill 目录发布到技能库。
"""
import shutil
from pathlib import Path

from langchain_core.tools import tool

from app.agent.workspace_context import get_session
from app.config import get_settings

MAX_READ_BYTES = 200_000  # 单文件读取上限，防止把超大文件塞进上下文


def _root() -> Path:
    """当前会话的工作区根：若设置了会话，则隔离到 workspace/<thread_id>/。

    对 agent 透明——它传的相对路径始终相对于这个根，感知不到会话子目录。
    """
    base = get_settings().workspace_path
    session = get_session()
    if session:
        root = base / session
        root.mkdir(parents=True, exist_ok=True)
        return root
    return base


def _resolve_safe(rel_path: str) -> Path:
    """把相对路径解析为工作区内的绝对路径；越界则报错。"""
    root = _root()
    # 去掉开头的斜杠，避免被当成绝对路径
    candidate = (root / rel_path.lstrip("/\\")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError(
            f"路径越界：'{rel_path}' 超出了工作区。只能操作工作区内的文件。"
        )
    return candidate


def _category_for(filename: str) -> str:
    """按文件扩展名返回同名文件夹（如 .md → md、.yaml → yaml）。无扩展名归到 other。"""
    dot = filename.rfind(".")
    if dot == -1 or dot == len(filename) - 1:
        return "other"
    return filename[dot + 1:].lower()


def _categorize(rel_path: str) -> str:
    """把裸文件名按扩展名归入同名子文件夹（如 main.py → py/main.py、a.md → md/a.md）。

    对 agent 透明：只有当 agent 给的是「裸文件名」（不含目录分隔符）时才自动归类；
    若 agent 显式指定了目录（如 src/main.py），则尊重其选择，原样返回。
    """
    normalized = rel_path.strip().lstrip("/\\")
    # 已含目录分隔符 → agent 显式选了路径，不动
    if "/" in normalized or "\\" in normalized:
        return normalized
    if not normalized:
        return normalized
    return f"{_category_for(normalized)}/{normalized}"


def _resolve_for_read(rel_path: str) -> Path:
    """读/编辑时解析路径：先按原样找；找不到且是裸文件名时，尝试归类后的路径。

    这样 agent 即便忘了带类别前缀（写时返回过），也能命中真实文件。
    """
    target = _resolve_safe(rel_path)
    if target.exists():
        return target
    normalized = rel_path.strip().lstrip("/\\")
    if "/" not in normalized and "\\" not in normalized and normalized:
        alt = _resolve_safe(_categorize(normalized))
        if alt.exists():
            return alt
    return target


@tool
def list_files(subdir: str = "") -> str:
    """列出工作区内某个目录下的文件和子目录。

    Args:
        subdir: 相对工作区根的子目录，留空表示根目录。
    """
    base = _resolve_safe(subdir) if subdir else _root()
    if not base.exists():
        return f"目录不存在: {subdir or '(根)'}"
    if not base.is_dir():
        return f"不是目录: {subdir}"

    root = _root()
    lines = []
    for entry in sorted(base.iterdir(), key=lambda e: (e.is_file(), e.name)):
        rel = entry.relative_to(root).as_posix()
        if entry.is_dir():
            lines.append(f"[dir]  {rel}/")
        else:
            lines.append(f"[file] {rel}  ({entry.stat().st_size} bytes)")
    return "\n".join(lines) if lines else "（空目录）"


@tool
def read_file(path: str) -> str:
    """读取工作区内某个文本文件的内容。

    Args:
        path: 相对工作区根的文件路径。
    """
    target = _resolve_for_read(path)
    if not target.exists():
        return f"文件不存在: {path}"
    if not target.is_file():
        return f"不是文件: {path}"
    data = target.read_bytes()
    if len(data) > MAX_READ_BYTES:
        data = data[:MAX_READ_BYTES]
        suffix = f"\n\n...（已截断，文件超过 {MAX_READ_BYTES} 字节）"
    else:
        suffix = ""
    try:
        return data.decode("utf-8") + suffix
    except UnicodeDecodeError:
        return f"无法以 UTF-8 解码，可能是二进制文件: {path}"


@tool
def write_file(path: str, content: str) -> str:
    """在工作区内创建或覆盖一个文件。会自动创建所需的父目录。

    Args:
        path: 相对工作区根的文件路径。裸文件名会按扩展名自动归入同名文件夹
              （如 a.md → md/a.md）；显式带目录的路径原样保留。
        content: 要写入的完整文件内容。

    注意：单次写入建议不超过 50KB（约 5 万字符）。若文档很大，请分段写入：
    1. 先写骨架（目录+章节标题）
    2. 用 edit_file 逐段补充各章节内容
    这样可避免大内容生成被截断导致写入失败。
    """
    stored = _categorize(path)
    target = _resolve_safe(stored)

    # 大文件警告（不强制拒绝，只提示最佳实践）
    size_kb = len(content) / 1024
    if size_kb > 50:
        warning = f"[!] 内容较大（{size_kb:.1f}KB），建议分段写入以避免生成被截断。"
    else:
        warning = ""

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    # 返回真实存储路径，让 agent 后续 read/edit 能对上
    result = f"已写入 {len(content)} 个字符到 {stored}"
    return f"{result}\n{warning}" if warning else result


@tool
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """对工作区内文件做精确字符串替换。old_string 必须在文件中唯一出现。

    Args:
        path: 相对工作区根的文件路径。
        old_string: 要被替换的原文（需唯一匹配）。
        new_string: 替换后的新内容。
    """
    target = _resolve_for_read(path)
    if not target.exists():
        return f"文件不存在: {path}"
    text = target.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        return f"未找到要替换的内容，编辑失败: {path}"
    if count > 1:
        return f"old_string 在文件中出现了 {count} 次，不唯一，请提供更多上下文。"
    target.write_text(text.replace(old_string, new_string), encoding="utf-8")
    return f"已完成替换: {path}"


@tool
def append_file(path: str, content: str) -> str:
    """在工作区内某个文件末尾追加内容。文件不存在时会创建。

    适用场景：分段生成大文档时，先 write_file 写骨架，再用此工具逐段追加章节。

    Args:
        path: 相对工作区根的文件路径。
        content: 要追加的内容（会直接接在文件末尾，注意自己加换行）。
    """
    target = _resolve_for_read(path)
    if not target.exists():
        # 文件不存在时创建（等同于 write_file）
        stored = _categorize(path)
        target = _resolve_safe(stored)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"文件不存在，已创建并写入 {len(content)} 个字符: {stored}"

    # 追加模式
    with target.open("a", encoding="utf-8") as f:
        f.write(content)
    new_size = target.stat().st_size
    return f"已追加 {len(content)} 个字符到 {path}，文件现在 {new_size} 字节"


def resolve_written_file(rel_path: str) -> dict | None:
    """给定 agent 写文件时传的路径，返回该文件的真实信息，供前端实时预览。

    处理了两层路径变换：
    1. 裸文件名会被 _categorize 归类到 <ext>/ 子目录；
    2. 每个会话的文件隔离在 workspace/<session>/ 下。

    返回 {path, content}：
    - path：相对「工作区根」的完整相对路径（含会话目录），与 /workspace/tree 的 path 一致，
            前端可直接用它匹配文件树或调用 /workspace/file 读取；
    - content：文件当前完整文本内容（截断到 MAX_READ_BYTES）。
    找不到或非文本文件时返回 None。
    """
    target = _resolve_for_read(rel_path)
    if not target.exists() or not target.is_file():
        return None
    settings = get_settings()
    try:
        # 相对工作区根（含会话子目录），与 tree 的 path 字段一致
        full_rel = target.resolve().relative_to(settings.workspace_path.resolve()).as_posix()
    except ValueError:
        return None
    data = target.read_bytes()
    if len(data) > MAX_READ_BYTES:
        data = data[:MAX_READ_BYTES]
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return {"path": full_rel, "content": content}


@tool
def publish_skill(skill_path: str) -> str:
    """将工作区内的 skill 目录发布到技能库，使其可在对话中通过 load_skill 加载。

    Args:
        skill_path: 工作区内 skill 目录的相对路径（必须包含 SKILL.md 或 skill.md）

    Returns:
        发布结果：技能名称和描述，或错误信息

    Examples:
        publish_skill("my-skill")  # 发布 workspace/my-skill/ 目录
        publish_skill("skills/data-analysis")  # 发布 workspace/skills/data-analysis/

    Skill 目录要求：
    - 必须包含 SKILL.md 或 skill.md（frontmatter 定义 name 和 description）
    - 可选 resources/ 子目录存放资源文件
    - 发布后可通过 load_skill(name) 在对话中调用
    """
    from app.agent.skills import registry

    try:
        # 解析工作区路径
        source_dir = _resolve_safe(skill_path)

        if not source_dir.exists():
            return f"错误：路径不存在: {skill_path}"

        if not source_dir.is_dir():
            return f"错误：{skill_path} 不是目录"

        # 查找 SKILL.md
        skill_md = registry._find_skill_md(source_dir)
        if skill_md is None:
            return f"错误：{skill_path} 目录下未找到 SKILL.md 或 skill.md 文件"

        # 解析 frontmatter
        name, description = registry._parse_frontmatter(skill_md)
        if not name:
            return f"错误：SKILL.md 的 frontmatter 缺少 'name' 字段"

        # 验证 skill 结构
        valid, error = registry.validate_skill(source_dir)
        if not valid:
            return f"错误：Skill 验证失败: {error}"

        # 复制到技能目录
        settings = get_settings()
        skills_dir = settings.store_path / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)

        target_dir = skills_dir / name

        # 如果已存在，先删除旧版本
        if target_dir.exists():
            shutil.rmtree(target_dir)

        # 复制整个目录
        shutil.copytree(source_dir, target_dir)

        return f"✅ Skill '{name}' 发布成功！\n描述: {description}\n\n现在可以通过 load_skill('{name}') 加载使用。"

    except ValueError as e:
        return f"错误：{e}"
    except Exception as e:
        return f"发布失败: {e}"


WORKSPACE_TOOLS = [list_files, read_file, write_file, edit_file, append_file, publish_skill]
