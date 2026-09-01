"""应用配置：从 .env 读取，集中管理。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"
    # 自定义 API 地址：对接公司内部 Anthropic 兼容网关时填；留空则用官方地址
    anthropic_base_url: str = ""

    # ── Subagent 工厂配置 ──
    # 派生的子助手默认用的模型；留空则回退到 anthropic_model（主模型）。
    # 子助手多是「按指令埋头干活」的执行体，用更快/更便宜的 Haiku 提速中间轮、
    # 省成本；主路 agent 仍用 anthropic_model（Opus）保证综合作答质量。
    # agent 定义（agents/*.md frontmatter 的 model 字段）可逐个覆盖此默认值。
    subagent_model: str = "claude-haiku-4-5"
    # 子助手内部 ReAct 循环的最大迭代次数（防跑飞）
    subagent_max_iterations: int = 20
    # 子助手单次 API 调用的最大输出 token
    subagent_max_tokens: int = 8192

    # 智能体文件读写的安全边界目录
    workspace_root: str = "./store/workspace"
    upload_dir: str = "./store/uploads"

    cors_origins: str = "http://localhost:5173"

    # 向量库一致性守护任务：每隔多少秒自检一次（0 表示禁用）
    vector_guard_interval: int = 1800  # 默认 30 分钟

    # ── 飞书机器人接入 ──
    feishu_app_id: str = ""              # 飞书应用 App ID
    feishu_app_secret: str = ""          # 飞书应用 App Secret
    feishu_verification_token: str = ""  # 事件订阅验签 token
    feishu_encrypt_key: str = ""         # 事件加密 key（可选，配了才解密）
    feishu_enabled: bool = False         # 飞书接入总开关
    # 飞书 adapter 内部自调的本地 chat 地址（避免重构核心对话逻辑）
    feishu_chat_url: str = "http://127.0.0.1:8123/api/chat"

    @property
    def workspace_path(self) -> Path:
        p = Path(self.workspace_root).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def upload_path(self) -> Path:
        p = Path(self.upload_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def store_path(self) -> Path:
        """通用存储根目录（包含 workspace、uploads、skills、kb_text 等）。"""
        p = Path("./store").resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def resolved_subagent_model(self) -> str:
        """子助手实际使用的模型：优先 subagent_model，留空回退主模型。"""
        return self.subagent_model.strip() or self.anthropic_model

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
