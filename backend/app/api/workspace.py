"""工作区浏览接口：供前端展示智能体读写的文件。

与 agent 工具共用同一个 WORKSPACE_ROOT 安全边界。文件按会话（thread_id）
分子目录存放：workspace/<thread_id>/...，避免多会话文件混在一起。
"""
import io
import shutil
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.config import get_settings

router = APIRouter()


def _safe(rel: str):
    root = get_settings().workspace_path
    target = (root / rel.lstrip("/\\")).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径越界")
    return target, root


def _safe_session_dir(thread_id: str):
    """解析会话目录，防止 thread_id 穿越。返回 (dir_path, root)。"""
    root = get_settings().workspace_path
    target = (root / thread_id.strip().lstrip("/\\")).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="会话路径越界")
    if target == root:
        raise HTTPException(status_code=400, detail="缺少会话标识")
    return target, root


@router.get("/workspace/tree")
async def tree():
    """返回工作区内所有文件，按会话（顶层子目录）分组。

    - session: 顶层目录名（thread_id）；根目录下的散落文件归到 "_root" 组
    - path: 相对工作区根的完整相对路径（下载/预览/删除都用它）
    - rel: 相对所属会话目录的路径（前端展示更简洁）
    """
    root = get_settings().workspace_path
    groups: dict[str, list[dict]] = {}

    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel_path = p.relative_to(root)
        parts = rel_path.parts
        if len(parts) == 1:
            session = "_root"
            rel = parts[0]
        else:
            session = parts[0]
            rel = "/".join(parts[1:])
        groups.setdefault(session, []).append({
            "path": rel_path.as_posix(),
            "rel": rel,
            "name": p.name,
            "size": p.stat().st_size,
            "mtime": p.stat().st_mtime,
        })

    # 组按最近修改时间倒序，便于最新会话排前面
    sessions = [
        {
            "session": sid,
            "files": files,
            "latest": max((f["mtime"] for f in files), default=0),
        }
        for sid, files in groups.items()
    ]
    sessions.sort(key=lambda g: -g["latest"])

    # 同时保留扁平列表，兼容旧前端
    flat = [f["path"] for g in sessions for f in g["files"]]
    return {"sessions": sessions, "files": flat}


@router.get("/workspace/file")
async def read(path: str):
    """读取工作区内某个文件的文本内容。"""
    target, _ = _safe(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        return {"path": path, "content": target.read_text(encoding="utf-8")}
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="非文本文件，无法预览")


@router.get("/workspace/download")
async def download(path: str):
    """下载工作区内的单个文件（含二进制文件）。"""
    target, _ = _safe(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        target,
        filename=target.name,
        media_type="application/octet-stream",
    )


@router.get("/workspace/download-session")
async def download_session(session: str):
    """把某个会话目录下所有文件打包成 zip 下载。"""
    session_dir, _root = _safe_session_dir(session)
    if not session_dir.exists() or not session_dir.is_dir():
        raise HTTPException(status_code=404, detail="会话目录不存在")

    files = [p for p in session_dir.rglob("*") if p.is_file()]
    if not files:
        raise HTTPException(status_code=404, detail="该会话没有文件")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            # zip 内路径相对会话目录，保留子目录结构
            zf.write(p, arcname=p.relative_to(session_dir).as_posix())
    buf.seek(0)

    zip_name = f"{session_dir.name}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@router.delete("/workspace/file")
async def delete(path: str):
    """删除工作区内的文件或目录。"""
    target, _ = _safe(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"deleted": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")
