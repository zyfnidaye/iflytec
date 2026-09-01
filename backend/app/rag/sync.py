"""向量库与知识库元数据的一致性同步逻辑。

供两处复用：
- API 端点 /api/knowledge/reindex（手动触发）
- 后台守护任务 guardian.py（定期自检）

注意：已禁用 BGE-Large (1024d)，只使用 BGE-Small (512d)。
"""
from app.rag.indexing import index_document, delete_document_index
from app.store import knowledge as kb


def sync_vectorstore(force: bool = False) -> dict:
    """同步向量库与元数据库（当前模型）。

    force=False: 增量模式，清除孤儿 + 补缺失索引
    force=True:  全量重建当前 collection
    """
    from app.rag.vectorstore import get_vector_store

    vs = get_vector_store()
    meta_docs = {str(d["id"]): d for d in kb.list_documents()}
    meta_ids = set(meta_docs.keys())

    removed, indexed = [], []

    # ── 当前模型 collection 同步 ──
    if force:
        vs.clear_collection(vs.dim)

    results = vs.collection.get()
    vec_ids = {str(m["doc_id"]) for m in results["metadatas"]}

    # 清除孤儿（Chroma 有但 kb.db 没有）
    for doc_id in vec_ids - meta_ids:
        delete_document_index(doc_id)
        removed.append(doc_id)

    # 补缺失索引（kb.db 有但 Chroma 没有）
    for doc_id in meta_ids - vec_ids:
        doc = meta_docs[doc_id]
        if doc["status"] not in ("ready", "indexing"):
            continue
        try:
            text = kb.load_text(int(doc_id))
            if not text:
                continue
            index_document(doc_id, text, source=doc["name"])
            if doc["status"] == "indexing":
                kb.update_status_and_char_count(int(doc_id), "ready", len(text))
            indexed.append(doc_id)
        except Exception as e:
            print(f"[sync] Failed to index doc {doc_id}: {e}")

    # 刷新 vec_ids（索引完成后重新获取当前 collection 实际包含的文档）
    results = vs.collection.get()
    vec_ids = {str(m["doc_id"]) for m in results["metadatas"]}

    # 修复 section_index
    si_fixed = _fix_section_index(vs, meta_docs)

    # ── 不再自动补建另一个模型的 collection（已禁用 BGE-Large） ──

    return {
        "removed_orphans": removed,
        "reindexed": indexed,
        "other_indexed": [],  # 已禁用
        "section_index_fixed": si_fixed,
        "total_docs": len(meta_ids),
    }


def reindex_document(doc_id: str, text: str, source: str) -> None:
    """重建单篇文档的向量索引（用于编辑正文后同步向量库）。

    1. delete_document_index：删除旧向量
    2. index_document：用当前激活模型重建索引

    注意：已禁用 BGE-Large，不再自动补建 1024d collection。
    """
    doc_id = str(doc_id)

    # 1. 删除旧向量
    delete_document_index(doc_id)

    # 2. 重建当前激活模型维度
    index_document(doc_id, text, source=source)


def _fix_section_index(vs, meta_docs: dict) -> list[str]:
    """修复当前模型的 _section_index 缺失。"""
    fixed = []
    results = vs.collection.get()
    if not results["ids"]:
        return fixed

    chroma_docs = {str(m["doc_id"]) for m in results["metadatas"]}

    for doc_id, doc in meta_docs.items():
        if doc["status"] != "ready":
            continue
        key_prefix = f"{doc_id}:"
        has_entries = any(k.startswith(key_prefix) for k in vs._section_index)
        if not has_entries and doc_id in chroma_docs:
            if vs._index_path.exists():
                try:
                    import json
                    disk = json.loads(vs._index_path.read_text(encoding="utf-8"))
                    added = 0
                    for k, v in disk.items():
                        if k.startswith(key_prefix) and k not in vs._section_index:
                            vs._section_index[k] = v
                            added += 1
                    if added:
                        fixed.append(doc_id)
                except Exception:
                    pass

    return fixed
