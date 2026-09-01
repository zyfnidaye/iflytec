"""上传接口：接收链路图文件。结构化文件（JSON/YAML）会立即解析进拓扑。"""
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.agent.tools.topology import load_topology_from_file
from app.config import get_settings

router = APIRouter()

STRUCTURED_EXT = {".json", ".yaml", ".yml"}


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    settings = get_settings()
    filename = file.filename or "upload.bin"
    dest = settings.upload_path / filename
    content = await file.read()
    dest.write_bytes(content)

    ext = dest.suffix.lower()
    if ext in STRUCTURED_EXT:
        try:
            summary = load_topology_from_file(str(dest))
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"拓扑文件解析失败：{e}"
            )
        return {
            "filename": filename,
            "type": "topology",
            "summary": summary,
        }

    # 其它类型（如图片架构图）仅保存，具体理解交给对话时的视觉能力
    return {
        "filename": filename,
        "type": "file",
        "summary": f"已保存 {filename}（{len(content)} bytes）。若为架构图片，可在对话中直接提问。",
    }
