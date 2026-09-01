"""向量数据库 - 双集合设计（512d / 1024d），切换模型无需重建。"""
import json

import chromadb
from chromadb.config import Settings

from app.config import get_settings
from app.rag.embeddings import get_embedding_model


def _collection_name(dim: int) -> str:
    return f"kb_{dim}"


class VectorStore:
    """Chroma 向量数据库封装，同时维护 512d 和 1024d 两个 collection。"""

    def __init__(self):
        settings = get_settings()
        chroma_path = settings.store_path / "chroma"
        chroma_path.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(chroma_path),
            settings=Settings(anonymized_telemetry=False),
        )
        self._chroma_path = chroma_path
        self._embedding_model = get_embedding_model()

        # 两套 collection 和 section_index
        self._collections: dict[int, object] = {}
        self._section_indexes: dict[int, dict] = {}
        for dim in (512, 1024):
            name = _collection_name(dim)
            self._collections[dim] = self.client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
            self._section_indexes[dim] = {}
            self._load_section_index(dim)

    @property
    def dim(self) -> int:
        return self._embedding_model.dim

    @property
    def collection(self):
        """当前模型对应的 collection。"""
        return self._collections[self.dim]

    @property
    def _section_index(self) -> dict:
        return self._section_indexes[self.dim]

    @_section_index.setter
    def _section_index(self, value: dict):
        self._section_indexes[self.dim] = value

    @property
    def _index_path(self):
        return self._chroma_path / f"section_index_{self.dim}.json"

    # ── 持久化 ──

    def _load_section_index(self, dim: int):
        path = self._chroma_path / f"section_index_{dim}.json"
        if path.exists():
            try:
                self._section_indexes[dim] = json.loads(
                    path.read_text(encoding="utf-8")
                )
            except Exception:
                self._section_indexes[dim] = {}

    def _save_section_index(self):
        try:
            self._index_path.write_text(
                json.dumps(self._section_index, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ── 跨 collection 信息 ──

    def collection_info(self, dim: int) -> dict:
        """返回指定维度 collection 的统计信息。"""
        c = self._collections[dim]
        idx = self._section_indexes[dim]
        return {
            "dim": dim,
            "chunks": c.count(),
            "sections": len(idx),
        }

    def all_collections_info(self) -> dict:
        return {str(d): self.collection_info(d) for d in (512, 1024)}

    # ── 文档管理 ──

    def add_documents(self, doc_id: str, chunks: list[dict]):
        """添加文档分块到当前模型的 collection。"""
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        embeddings = self._embedding_model.encode(texts)

        ids = [f"{doc_id}:{c['chunk_id']}" for c in chunks]

        metadatas = [
            {
                "doc_id": str(doc_id),
                "chunk_id": c["chunk_id"],
                "section_id": c.get("section_id", 0),
                "section_title": c.get("section_title", "")[:200],
                "source": c.get("source", ""),
            }
            for c in chunks
        ]

        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

        # 构建 section 内存索引 + 持久化
        for c in chunks:
            key = f"{doc_id}:{c.get('section_id', 0)}"
            if key not in self._section_index:
                self._section_index[key] = {
                    "title": c.get("section_title", ""),
                    "text": c.get("section_text", c["text"]),
                    "summary": c.get("section_summary", ""),
                }
        self._save_section_index()

    def _ensure_index_synced(self):
        """检查磁盘索引是否比内存多（外部更新）。"""
        if not self._index_path.exists():
            return
        try:
            disk = json.loads(self._index_path.read_text(encoding="utf-8"))
            if len(disk) > len(self._section_index):
                for k, v in disk.items():
                    if k not in self._section_index:
                        self._section_index[k] = v
        except Exception:
            pass

    def search(self, query: str, top_k: int = 3, doc_ids: list[str] = None) -> list[dict]:
        """语义检索（使用当前模型的 collection）。

        Args:
            query: 搜索查询
            top_k: 返回结果数
            doc_ids: 可选，限定只在这些文档中搜索。None 表示全库搜索。
        """
        self._ensure_index_synced()
        query_embedding = self._embedding_model.encode([query])[0]

        query_kwargs = dict(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )
        if doc_ids:
            query_kwargs["where"] = {"doc_id": {"$in": doc_ids}}

        results = self.collection.query(**query_kwargs)

        chunks = []
        if results["ids"] and results["ids"][0]:
            for i, _chunk_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i]
                doc_id = meta["doc_id"]
                section_id = meta.get("section_id")
                section_title = meta.get("section_title", "")

                section_text = results["documents"][0][i]
                if section_id is not None:
                    key = f"{doc_id}:{section_id}"
                    if key in self._section_index:
                        section_text = self._section_index[key]["text"]
                        section_title = self._section_index[key]["title"] or section_title

                chunks.append({
                    "text": results["documents"][0][i],
                    "doc_id": doc_id,
                    "chunk_id": meta["chunk_id"],
                    "section_id": section_id,
                    "section_title": section_title,
                    "section_text": section_text,
                    "distance": results["distances"][0][i] if "distances" in results else 0.0,
                })

        return chunks

    def delete_document(self, doc_id: str):
        """从两个 collection 中删除文档。"""
        prefix = f"{doc_id}:"
        for dim in (512, 1024):
            idx = self._section_indexes[dim]
            keys_to_del = [k for k in idx if k.startswith(prefix)]
            for k in keys_to_del:
                del idx[k]
            # 持久化
            path = self._chroma_path / f"section_index_{dim}.json"
            try:
                path.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            col = self._collections[dim]
            results = col.get(where={"doc_id": str(doc_id)})
            if results["ids"]:
                col.delete(ids=results["ids"])

    # ── 按 section 读取（供 read_document 用，避免 load 整篇原文） ──

    def _sorted_section_keys(self, doc_id: str) -> list[str]:
        """返回某文档所有 section 的 key，按 section_id 数字序排。"""
        prefix = f"{doc_id}:"
        keys = [k for k in self._section_index if k.startswith(prefix)]

        def _sid(k: str) -> int:
            tail = k.split(":", 1)[1] if ":" in k else "0"
            return int(tail) if tail.isdigit() else 0

        return sorted(keys, key=_sid)

    def list_sections(self, doc_id: str) -> list[dict]:
        """列出某文档的 section 目录（不含正文），供模型挑选要读哪几段。

        返回 [{"section_id": int, "title": str, "chars": int}, ...]，按 section_id 排序。
        section_index 可能只在内存/磁盘其一，先同步一次再读。
        """
        self._ensure_index_synced()
        out = []
        for k in self._sorted_section_keys(str(doc_id)):
            tail = k.split(":", 1)[1] if ":" in k else "0"
            info = self._section_index[k]
            out.append({
                "section_id": int(tail) if tail.isdigit() else tail,
                "title": info.get("title", ""),
                "chars": len(info.get("text", "")),
            })
        return out

    def get_sections(self, doc_id: str, section_ids: list[int]) -> list[dict]:
        """按 section_id 取指定段落的完整正文（保持传入顺序，跳过不存在的）。

        返回 [{"section_id", "title", "text"}, ...]。
        """
        self._ensure_index_synced()
        out = []
        for sid in section_ids:
            key = f"{doc_id}:{sid}"
            info = self._section_index.get(key)
            if info is None:
                continue
            out.append({
                "section_id": sid,
                "title": info.get("title", ""),
                "text": info.get("text", ""),
            })
        return out

    def clear_collection(self, dim: int):
        """清空指定维度的 collection（用于强制重建）。"""
        col = self._collections[dim]
        ids = col.get()["ids"]
        if ids:
            col.delete(ids=ids)
        self._section_indexes[dim].clear()
        path = self._chroma_path / f"section_index_{dim}.json"
        try:
            path.write_text("{}", encoding="utf-8")
        except Exception:
            pass


# 全局单例
_vector_store = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
