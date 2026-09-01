"""FastAPI 入口。"""
import os

# 必须在导入任何 HuggingFace 相关库之前设置：强制离线，只用本地模型缓存。
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, conversations, feishu, knowledge, skills, upload, workspace
from app.config import get_settings
from app.rag.guardian import start_guardian, stop_guardian

# 配置日志：同时输出到控制台和文件
log_dir = Path(__file__).parent.parent / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "server.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),  # 控制台
        logging.FileHandler(log_file, encoding="utf-8"),  # 文件
    ],
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：拉起向量库一致性守护任务
    start_guardian()
    yield
    # 关闭：优雅停止守护任务
    await stop_guardian()


app = FastAPI(title="公司学习助手 · Code Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(conversations.router, prefix="/api", tags=["conversations"])
app.include_router(knowledge.router, prefix="/api", tags=["knowledge"])
app.include_router(skills.router, prefix="/api", tags=["skills"])
app.include_router(upload.router, prefix="/api", tags=["upload"])
app.include_router(workspace.router, prefix="/api", tags=["workspace"])
app.include_router(feishu.router, prefix="/api", tags=["feishu"])


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "model": settings.anthropic_model,
        "api_key_set": bool(settings.anthropic_api_key),
    }
