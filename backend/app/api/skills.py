"""Skills API: upload, list, and delete Anthropic Agent Skills."""
import shutil
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.agent.skills import registry
from app.config import get_settings

router = APIRouter()


@router.get("/skills")
async def list_skills():
    """列出所有已上传的 skills（名称 + 描述）。"""
    skills = registry.scan_skills()
    return {"skills": skills}


@router.get("/skills/{skill_name}")
async def get_skill_content(skill_name: str):
    """获取指定 skill 的完整内容（SKILL.md 文件内容）。"""
    try:
        content = registry.read_skill_content(skill_name)
        return {"name": skill_name, "content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' 不存在")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取失败: {e}")


@router.post("/skills/upload")
async def upload_skill(files: list[UploadFile] = File(...)):
    """上传 skill 定义文件。

    支持三种格式：
    1. .zip 包（包含 SKILL.md 及可选资源文件）
    2. 单个 SKILL.md 文件（从 frontmatter 提取 name，自动创建文件夹）
    3. 多个文件（文件夹上传，自动从文件路径提取结构）

    Returns:
        {"name": "...", "description": "...", "status": "ok"}
    """
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="未选择文件")

    skills_root = get_settings().store_path / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    # 多文件上传（文件夹模式）
    if len(files) > 1:
        return await _handle_multiple_files(files, skills_root)

    # 单文件上传
    file = files[0]
    filename = file.filename or "upload"
    data = await file.read()

    # 处理 zip 包
    if filename.endswith(".zip"):
        return await _handle_zip_upload(data, skills_root)

    # 处理单个 SKILL.md
    if filename == "SKILL.md" or filename.endswith(".md"):
        return await _handle_single_md(data, skills_root)

    raise HTTPException(
        status_code=400,
        detail="仅支持 .zip 或 SKILL.md 文件。Zip 应包含技能文件夹；SKILL.md 会根据 frontmatter 的 name 自动创建文件夹。",
    )


@router.delete("/skills/{skill_name}")
async def delete_skill(skill_name: str):
    """删除指定 skill 的整个文件夹。"""
    try:
        registry.delete_skill(skill_name)
        return {"status": "ok", "message": f"Skill '{skill_name}' 已删除"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' 不存在")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")


async def _handle_zip_upload(data: bytes, skills_root: Path) -> dict:
    """解压 zip 包到 skills/ 目录，验证结构。"""
    with zipfile.ZipFile(BytesIO(data)) as zf:
        # 找到 SKILL.md 所在的顶层文件夹
        skill_md_path = None
        for name in zf.namelist():
            if name.endswith("SKILL.md") and name.count("/") <= 1:
                skill_md_path = name
                break

        if not skill_md_path:
            raise HTTPException(
                status_code=400,
                detail="Zip 包中未找到 SKILL.md（应在根目录或一层子目录内）",
            )

        # 提取技能名（SKILL.md 所在的文件夹名，或从 frontmatter 读取）
        if "/" in skill_md_path:
            skill_folder_name = skill_md_path.split("/")[0]
        else:
            # SKILL.md 在 zip 根目录，需从内容提取 name
            skill_md_content = zf.read(skill_md_path).decode("utf-8")
            skill_folder_name = _extract_name_from_md(skill_md_content)

        target_dir = skills_root / skill_folder_name

        # 如果同名 skill 已存在，先删除
        if target_dir.exists():
            shutil.rmtree(target_dir)

        target_dir.mkdir(parents=True, exist_ok=True)

        # 解压（保留目录结构，但去掉顶层文件夹名如果有的话）
        for member in zf.namelist():
            # 跳过目录项和 __MACOSX 等垃圾
            if member.endswith("/") or "__MACOSX" in member or member.startswith("."):
                continue

            # 去掉顶层文件夹前缀
            if "/" in skill_md_path and member.startswith(skill_folder_name + "/"):
                rel_path = member[len(skill_folder_name) + 1 :]
            else:
                rel_path = member

            if not rel_path:
                continue

            out_path = target_dir / rel_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(zf.read(member))

    # 验证
    valid, error = registry.validate_skill(target_dir)
    if not valid:
        shutil.rmtree(target_dir)
        raise HTTPException(status_code=400, detail=f"Skill 验证失败: {error}")

    # 使用 _find_skill_md 查找技能文件
    skill_md = registry._find_skill_md(target_dir)
    if skill_md is None:
        shutil.rmtree(target_dir)
        raise HTTPException(status_code=400, detail="未找到 SKILL.md 或 skill.md 文件")

    name, description = registry._parse_frontmatter(skill_md)
    return {"name": name, "description": description, "status": "ok"}


async def _handle_single_md(data: bytes, skills_root: Path) -> dict:
    """处理单个 SKILL.md 文件，从 frontmatter 提取 name 创建文件夹。"""
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="SKILL.md 必须是 UTF-8 编码的文本文件")

    skill_name = _extract_name_from_md(content)
    skill_dir = skills_root / skill_name

    # 如果同名 skill 已存在，先删除
    if skill_dir.exists():
        shutil.rmtree(skill_dir)

    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    # 验证
    valid, error = registry.validate_skill(skill_dir)
    if not valid:
        shutil.rmtree(skill_dir)
        raise HTTPException(status_code=400, detail=f"Skill 验证失败: {error}")

    # 使用 _find_skill_md 查找技能文件
    skill_md = registry._find_skill_md(skill_dir)
    if skill_md is None:
        shutil.rmtree(skill_dir)
        raise HTTPException(status_code=400, detail="未找到 SKILL.md 或 skill.md 文件")

    name, description = registry._parse_frontmatter(skill_md)
    return {"name": name, "description": description, "status": "ok"}


def _extract_name_from_md(content: str) -> str:
    """从 SKILL.md 内容中提取 frontmatter 的 name 字段。

    如果没有 frontmatter，返回默认名称。
    """
    if not content.startswith("---\n"):
        # 没有 frontmatter，使用默认名称
        return "custom_skill"

    end = content.find("\n---\n", 4)
    if end == -1:
        raise HTTPException(status_code=400, detail="SKILL.md frontmatter 未正确闭合")

    import yaml

    frontmatter_text = content[4:end]
    try:
        meta = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML 解析失败: {e}")

    if not isinstance(meta, dict):
        raise HTTPException(status_code=400, detail="frontmatter 必须是 YAML 字典")

    name = meta.get("name", "").strip()
    if not name:
        raise HTTPException(
            status_code=400, detail="frontmatter 必须包含 name 字段且不能为空"
        )

    # 文件夹名只允许字母数字下划线短横线
    import re

    if not re.match(r"^[\w\-]+$", name):
        raise HTTPException(
            status_code=400,
            detail=f"Skill name '{name}' 包含非法字符，仅允许字母、数字、下划线和短横线",
        )

    return name


async def _handle_multiple_files(files: list[UploadFile], skills_root: Path) -> dict:
    """处理多文件上传（文件夹模式）。

    从浏览器的文件夹选择器上传的文件，提取文件夹结构并保存。
    """
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")

    # 查找 SKILL.md 或 skill.md 文件，确定技能文件夹名称
    skill_md_file = None
    folder_name = None

    for file in files:
        filename = file.filename or ""
        # 浏览器上传的文件名格式可能是 "folder/file.md" 或 "file.md"
        if "/" in filename:
            parts = filename.split("/")
            folder_name = parts[0]  # 顶层文件夹名
            if parts[-1].lower() == "skill.md":
                skill_md_file = file
                break
        elif filename.lower() == "skill.md":
            skill_md_file = file

    if not skill_md_file:
        raise HTTPException(status_code=400, detail="未找到 SKILL.md 或 skill.md 文件")

    # 如果没有从路径提取到文件夹名，从 SKILL.md 内容提取
    if not folder_name:
        content = (await skill_md_file.read()).decode("utf-8")
        await skill_md_file.seek(0)  # 重置文件指针
        folder_name = _extract_name_from_md(content)

    target_dir = skills_root / folder_name

    # 如果同名 skill 已存在，先删除
    if target_dir.exists():
        shutil.rmtree(target_dir)

    target_dir.mkdir(parents=True, exist_ok=True)

    # 保存所有文件
    for file in files:
        filename = file.filename or ""
        if not filename:
            continue

        # 提取相对路径（去掉顶层文件夹名）
        if "/" in filename:
            parts = filename.split("/")
            if len(parts) > 1:
                # 去掉顶层文件夹，保留子路径
                rel_path = "/".join(parts[1:])
            else:
                rel_path = parts[0]
        else:
            rel_path = filename

        if not rel_path:
            continue

        # �过滤隐藏文件和系统文件
        if rel_path.startswith(".") or "__MACOSX" in rel_path:
            continue

        file_path = target_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        content = await file.read()
        file_path.write_bytes(content)

    # 验证
    valid, error = registry.validate_skill(target_dir)
    if not valid:
        shutil.rmtree(target_dir)
        raise HTTPException(status_code=400, detail=f"Skill 验证失败: {error}")

    # 使用 _find_skill_md 查找技能文件
    skill_md = registry._find_skill_md(target_dir)
    if skill_md is None:
        shutil.rmtree(target_dir)
        raise HTTPException(status_code=400, detail="未找到 SKILL.md 或 skill.md 文件")

    name, description = registry._parse_frontmatter(skill_md)
    return {"name": name, "description": description, "status": "ok"}


    return name
