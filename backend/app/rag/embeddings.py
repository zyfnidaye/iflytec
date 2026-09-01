"""Embedding 模型管理 - 支持 BGE-large / BGE-small 切换。"""
import os
from pathlib import Path

# 必须在 import sentence_transformers 之前设置
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from sentence_transformers import SentenceTransformer

# ── 可用模型注册表 ──
_MODEL_CACHE = Path(__file__).resolve().parent.parent.parent / "store" / "model_cache" / "models"

MODELS = {
    "bge-small": {
        "name": "BGE-Small",
        "path": str(_MODEL_CACHE / "BAAI--bge-small-zh-v1.5" / "snapshots" / "master"),
        "dim": 512,
        "fallback": "BAAI/bge-small-zh-v1.5",
    },
    "bge-large": {
        "name": "BGE-Large",
        "path": str(_MODEL_CACHE / "BAAI--bge-large-zh-v1.5" / "snapshots" / "master"),
        "dim": 1024,
        "fallback": "BAAI/bge-large-zh-v1.5",
    },
}

# 当前选中的模型 key
_current_model_key = "bge-small"

# 持久化模型选择的文件
_MODEL_SELECTION_FILE = _MODEL_CACHE / ".selected_model"


def _load_selection() -> str:
    try:
        if _MODEL_SELECTION_FILE.exists():
            return _MODEL_SELECTION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return "bge-small"


def _save_selection(key: str):
    try:
        _MODEL_SELECTION_FILE.write_text(key, encoding="utf-8")
    except Exception:
        pass


def load_model_by_key(key: str) -> SentenceTransformer:
    """加载指定 key 的模型（供后台索引使用，用完可释放）。"""
    cfg = MODELS[key]
    model_path = cfg["path"]
    if not Path(model_path).exists():
        model_path = cfg["fallback"]
    print(f"Loading {cfg['name']} ({cfg['dim']}d) for background indexing...")
    return SentenceTransformer(model_path)


class EmbeddingModel:
    """Embedding 模型管理器，支持运行时切换。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        global _current_model_key
        _current_model_key = _load_selection()
        self._model = None
        self._model_key = None
        self._load()

    def _load(self):
        if self._model_key == _current_model_key and self._model is not None:
            return
        cfg = MODELS[_current_model_key]
        model_path = cfg["path"]
        if not Path(model_path).exists():
            model_path = cfg["fallback"]
        print(f"Loading {cfg['name']} from: {model_path}")
        self._model = SentenceTransformer(model_path)
        self._model_key = _current_model_key
        print(f"Embedding model ready: {cfg['name']}, dimension: {cfg['dim']}")

    @property
    def dim(self) -> int:
        return MODELS[_current_model_key]["dim"]

    @property
    def model_key(self) -> str:
        return _current_model_key

    @classmethod
    def switch_model(cls, key: str) -> dict:
        global _current_model_key
        if key not in MODELS:
            raise ValueError(f"Unknown model: {key}, available: {list(MODELS.keys())}")
        if key == _current_model_key:
            return {"model": key, "dim": MODELS[key]["dim"], "changed": False}
        _current_model_key = key
        _save_selection(key)
        if cls._instance is not None:
            cls._instance._model_key = None
            cls._instance._load()
        return {"model": key, "dim": MODELS[key]["dim"], "changed": True}

    @classmethod
    def get_current_model_info(cls) -> dict:
        key = _current_model_key
        return {
            "model": key,
            "name": MODELS[key]["name"],
            "dim": MODELS[key]["dim"],
            "available": list(MODELS.keys()),
        }

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()


_embedding_model = None


def get_embedding_model() -> EmbeddingModel:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = EmbeddingModel()
    return _embedding_model
