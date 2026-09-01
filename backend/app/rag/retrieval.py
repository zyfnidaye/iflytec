"""RAG 检索和 prompt 构建（混合检索：向量 + BM25 RRF 融合）。"""
import re

from app.rag.config import (
    RETRIEVAL_TOP_K,
    MAX_CONTEXT_CHARS,
    HYBRID_ENABLED,
    HYBRID_RRF_K,
)
from app.rag.vectorstore import get_vector_store


def _match_docs(query: str) -> list[str] | None:
    """根据查询自动匹配知识库文档名，返回匹配的 doc_id 列表。无匹配返回 None。"""
    from app.store import knowledge as kb

    docs = kb.list_documents()
    if not docs:
        return None

    q_lower = query.lower()
    q_tokens = set()
    for v in re.findall(r"(?<![a-z0-9])v?\d+(?:\.\d+)*(?![a-z0-9])", q_lower):
        q_tokens.add(v)
        q_tokens.add(v.lstrip("v"))
        if "." in v:
            q_tokens.add(v.split(".")[0])
    for seq in re.findall(r"[一-鿿]{2,}", q_lower):
        q_tokens.update(seq[i:i+2] for i in range(len(seq) - 1))
    q_tokens.update(re.findall(r"(?<![a-z])[a-z0-9]{3,}(?![a-z])", q_lower))
    if not q_tokens:
        return None

    matches = []
    for d in docs:
        name_lower = d["name"].lower()
        name_tokens = set()
        for v in re.findall(r"(?<![a-z0-9])v?\d+(?:\.\d+)*(?![a-z0-9])", name_lower):
            name_tokens.add(v)
            name_tokens.add(v.lstrip("v"))
            if "." in v:
                name_tokens.add(v.split(".")[0])
        for seq in re.findall(r"[一-鿿]{2,}", name_lower):
            name_tokens.update(seq[i:i+2] for i in range(len(seq) - 1))
        name_tokens.update(re.findall(r"(?<![a-z])[a-z0-9]{3,}(?![a-z])", name_lower))
        overlap = q_tokens & name_tokens
        if overlap:
            matches.append((str(d["id"]), len(overlap), d["name"]))

    if not matches:
        return None

    matches.sort(key=lambda x: -x[1])
    best_score = matches[0][1]
    matches = [m for m in matches if m[1] >= max(best_score, 2)]
    matched_ids = [m[0] for m in matches]
    print(f"[RAG] Doc filter: query='{query[:50]}' -> matched {len(matched_ids)} docs: {[m[2][:30] for m in matches]}")
    return matched_ids


def _has_exact_id(query: str) -> bool:
    """判断 query 是否含「精确标识符」：数字串（错误码/版本号）、路径、接口名。

    这类词向量模型不敏感（11200/11201/11202 在向量空间几乎重合），
    应优先用精确匹配而非向量检索。
    """
    if not query:
        return False
    # 4位以上连续数字（错误码/端口/版本，如 11200、40001、v3）
    if re.search(r"\d{4,}", query):
        return True
    # 带斜杠的路径（/v2/xxx、wss://xxx）
    if "/" in query:
        return True
    # 错误码/接口名常见形态：数字+中文（"11200错误"）、code=xxx
    if re.search(r"(code|错误码|error)\s*[=:：]?\s*\d", query, re.IGNORECASE):
        return True
    return False


def _tokenize(text: str) -> list[str]:
    """分词：中文字符、完整路径、英文单词/版本号、字符 bigram 模糊匹配。"""
    tokens = []
    lowered = text.lower()
    for path in re.findall(r"/[a-zA-Z0-9/_]+", lowered):
        tokens.append(path)
        tokens.extend(re.findall(r"[a-zA-Z0-9]+", path))
    tokens.extend(re.findall(r"(?<![a-z0-9])v\d+(?![a-z0-9])", lowered))
    # 纯数字 token：错误码（11200）、端口、版本号。向量模型对这些不敏感，
    # BM25 必须保留才能做精确匹配兜底（否则"11200"这类查询永远 0 命中）。
    tokens.extend(re.findall(r"\d+", lowered))
    cjk_pattern = re.compile(
        r"[⺀-⿟　-〿㇀-㇯㐀-䶿"
        r"一-鿿豈-﫿︰-﹏]+"
    )
    chinese_seqs = cjk_pattern.findall(lowered)
    tokens.extend(s for s in chinese_seqs if len(s) >= 2)
    for seq in chinese_seqs:
        tokens.extend(seq[i:i+2] for i in range(len(seq) - 1))
    tokens.extend(re.findall(r"\b[a-z]{3,}\b", lowered))
    return tokens


# ── BM25 索引缓存 ──
# BM25 的语料统计只与知识库内容有关，与查询词无关；同一份语料反复重建纯属浪费。
# 而 RAG 默认每条消息都跑检索，重建开销（对全库分词 + 建模）会被放大。
# 这里按 _section_index 的"内容签名"缓存 BM25：签名不变直接复用，变了才重建。
# 不逐个挂失效钩子（改动 _section_index 的路径有多条，漏一个就是脏缓存），
# 改用签名感知——无论增删文档 / reindex / 切换模型，只要语料变了签名就变。
_BM25_CACHE: dict = {"sig": None, "keys": None, "bm25": None}


def _section_index_signature(index: dict) -> tuple:
    """为 section_index 算一个廉价内容签名，用于判断 BM25 缓存是否失效。

    只做 len()/哈希、不分词，远比重建索引便宜。可捕获：
    - 增删段落 → 段落数变；内容编辑 → 总字符数变；文档增删 → 键集合哈希变。
    """
    total_chars = 0
    for v in index.values():
        total_chars += len(v.get("text", ""))
    return (len(index), total_chars, hash(frozenset(index.keys())))


def _get_bm25(vs):
    """取当前语料的 BM25 索引（带缓存）。返回 (keys, bm25)，语料为空时返回 (None, None)。"""
    from rank_bm25 import BM25Okapi

    index = vs._section_index
    if not index:
        return None, None

    sig = _section_index_signature(index)
    if _BM25_CACHE["sig"] == sig and _BM25_CACHE["bm25"] is not None:
        return _BM25_CACHE["keys"], _BM25_CACHE["bm25"]

    items = list(index.items())
    keys = [k for k, _ in items]
    corpus = [_tokenize(info["text"]) for _, info in items]
    bm25 = BM25Okapi(corpus)

    _BM25_CACHE.update(sig=sig, keys=keys, bm25=bm25)
    return keys, bm25


def _keyword_search(query: str, top_k: int = 20) -> list[dict]:
    """BM25 关键词兜底搜索（BM25 索引带缓存，语料不变则复用）。

    返回: [{"key": "doc:section", "title": "...", "text": "...", "summary": "...", "hits": score}, ...]
    """
    vs = get_vector_store()
    keys, bm25 = _get_bm25(vs)
    if not keys:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scores = bm25.get_scores(query_tokens)
    ranked = sorted(zip(keys, scores), key=lambda x: -x[1])

    result = []
    for key, score in ranked:
        if score <= 0:
            break
        info = vs._section_index[key]
        result.append({
            "key": key,
            "title": info["title"],
            "text": info.get("summary") or info["text"],
            "summary": info.get("summary", ""),
            "hits": int(score),
        })

    return result[:top_k]


def _rrf_fuse(vector_results: list[dict], bm25_results: list[dict], k: int = 60) -> list[dict]:
    """RRF (Reciprocal Rank Fusion) 融合向量检索和 BM25 结果。

    RRF 公式：score = Σ 1/(k + rank_i)，其中 k 是平滑参数（典型值 60）。

    Args:
        vector_results: 向量检索结果，格式 [{"key": "doc:section", "distance": 0.x, ...}, ...]
        bm25_results: BM25 结果，格式 [{"key": "doc:section", "hits": score, ...}, ...]
        k: RRF 平滑参数，越大越平滑（降低排名差异影响）

    Returns:
        融合后的结果列表，按 RRF 分数降序排列，格式与 vector_results 一致（补充 rrf_score）
    """
    # 1. 构建 key -> rank 映射
    vector_ranks = {r["key"]: i for i, r in enumerate(vector_results)}
    bm25_ranks = {r["key"]: i for i, r in enumerate(bm25_results)}

    # 2. 所有候选 key（去重）
    all_keys = set(vector_ranks.keys()) | set(bm25_ranks.keys())

    # 3. 计算 RRF 分数
    rrf_scores = {}
    for key in all_keys:
        score = 0.0
        if key in vector_ranks:
            score += 1.0 / (k + vector_ranks[key])
        if key in bm25_ranks:
            score += 1.0 / (k + bm25_ranks[key])
        rrf_scores[key] = score

    # 4. 按 RRF 分数排序，返回完整对象（优先用 vector_results 的元数据）
    key_to_obj = {}
    for r in vector_results:
        key_to_obj[r["key"]] = r
    for r in bm25_results:
        if r["key"] not in key_to_obj:
            # BM25 独有的结果，构造为 vector_results 兼容格式
            key_to_obj[r["key"]] = {
                "key": r["key"],
                "title": r["title"],
                "text": r.get("summary") or r["text"],
                "summary": r.get("summary", ""),
                "doc_id": r["key"].split(":", 1)[0],
                "section_id": r["key"].split(":", 1)[1] if ":" in r["key"] else None,
                "distance": 0.5,  # BM25 独有结果给个中等距离
            }

    ranked = sorted(all_keys, key=lambda k: -rrf_scores[k])
    result = []
    for key in ranked:
        obj = key_to_obj[key].copy()
        obj["rrf_score"] = rrf_scores[key]
        result.append(obj)

    return result


def retrieve_context(query: str, top_k: int = RETRIEVAL_TOP_K) -> tuple[str, str]:
    """检索相关文档并拼接为上下文。返回 (context, user_message)。"""
    context, _query, _hit_ids, _distance, _hits = retrieve_context_ex(query, top_k)
    return context, _query


def retrieve_context_ex(
    query: str, top_k: int = RETRIEVAL_TOP_K, doc_ids: list[str] | None = None
) -> tuple[str, str, list[str], float, list[dict]]:
    """检索相关文档并拼接为上下文（混合检索：向量 + BM25 RRF 融合）。

    Args:
        query: 检索问题
        top_k: 返回 top-k 个 chunk
        doc_ids: 可选，指定只在这些文档里检索。不传则自动匹配文档。

    返回 (context, query, hit_doc_ids, best_distance, hits)。
    - hit_doc_ids: 本次检索命中的文档 id 列表（去重、按命中顺序）
    - best_distance: 最佳匹配的余弦距离（越小越相关，范围 [0, 2]）
    - hits: 段落级引用列表，每项含 {doc_id, section_id, section_title, snippet, distance}
    """

    # 1. 文档过滤：外部传入 doc_ids 则用它，否则自动匹配
    if doc_ids is None:
        doc_ids = _match_docs(query)

    # 2. 向量检索
    # 之前固定 max(top_k, 30)：不管 RETRIEVAL_TOP_K 配多少，至少拉 30 个 chunk，
    # 混合检索启用后 BM25 也按这个数走，两路结果经 RRF 融合，候选集越大、
    # 拼接的 context 越大，直接拖慢响应。改为贴近 top_k，只留小余量给 RRF 去重损耗。
    effective_top_k = max(top_k + 5, top_k)
    vector_store = get_vector_store()
    vector_chunks = vector_store.search(query, top_k=effective_top_k, doc_ids=doc_ids)

    # 3. BM25 检索（如果启用混合检索，总是执行）
    # 注意：必须和向量检索一样受 doc_ids 过滤，否则 doc_ids 收窄范围时
    # BM25 仍会从全库拉入不相关段落，经 RRF 混入结果，context 被无谓拉大、拖慢响应。
    bm25_results = []
    if HYBRID_ENABLED:
        # 混合检索模式：总是跑 BM25，用 RRF 融合
        vs = vector_store
        keys, bm25_model = _get_bm25(vs)
        if keys and bm25_model:
            query_tokens = _tokenize(query)
            if query_tokens:
                scores = bm25_model.get_scores(query_tokens)
                ranked = sorted(zip(keys, scores), key=lambda x: -x[1])
                doc_id_set = set(doc_ids) if doc_ids else None
                for key, score in ranked:
                    if score <= 0:
                        break
                    if doc_id_set is not None and key.split(":", 1)[0] not in doc_id_set:
                        continue
                    info = vs._section_index[key]
                    bm25_results.append({
                        "key": key,
                        "title": info["title"],
                        "text": info.get("summary") or info["text"],
                        "summary": info.get("summary", ""),
                        "hits": float(score),
                    })
                    if len(bm25_results) >= effective_top_k:
                        break

    # 4. 融合逻辑
    if HYBRID_ENABLED and vector_chunks and bm25_results:
        # 混合检索：RRF 融合
        # 将 vector_chunks 转换为 key 索引格式
        vector_as_key_list = []
        for chunk in vector_chunks:
            sid = chunk.get("section_id")
            doc_id = chunk.get("doc_id", "")
            key = f"{doc_id}:{sid}" if sid is not None else f"chunk_{chunk.get('chunk_id', 0)}"
            vector_as_key_list.append({
                "key": key,
                "chunk": chunk,  # 保留原始 chunk 对象
                "distance": chunk.get("distance", 999.0),
            })

        # RRF 融合
        fused = _rrf_fuse(vector_as_key_list, bm25_results, k=HYBRID_RRF_K)

        # 重建 chunks（按融合后的排序）
        chunks = []
        for item in fused[:effective_top_k]:
            if "chunk" in item:
                # 来自 vector_chunks
                chunks.append(item["chunk"])
            else:
                # 来自 BM25（向量未命中）
                key = item["key"]
                doc_id = key.split(":", 1)[0]
                section_id = key.split(":", 1)[1] if ":" in key else None
                si_key = key if ":" in key else ""
                si = vector_store._section_index.get(si_key, {})
                chunks.append({
                    "text": item["text"],
                    "doc_id": doc_id,
                    "section_id": section_id,
                    "section_title": item["title"],
                    "section_text": si.get("text", item["text"]),
                    "distance": 0.5,  # BM25 独有，给中等距离
                    "chunk_id": 0,
                })
    elif not vector_chunks:
        # 向量完全未命中，尝试纯 BM25 兜底
        if _has_exact_id(query):
            kw = _keyword_search(query, top_k=top_k)
            if kw:
                r = kw[0]
                sections = [{
                    "title": r["title"],
                    "text": r.get("summary") or r.get("text", ""),
                    "summary": r.get("summary", ""),
                    "doc_id": r["key"].split(":", 1)[0],
                    "section_id": r["key"].split(":", 1)[1] if ":" in r["key"] else None,
                    "distance": 0.0,
                }]
                ctx = "\n\n---\n\n".join(
                    f"[片段 {i}: {s['title']}]\n{s['text']}"
                    for i, s in enumerate(sections, 1)
                )
                hits = [{
                    "doc_id": s["doc_id"],
                    "section_id": s["section_id"],
                    "section_title": s["title"],
                    "snippet": s["text"][:200],
                    "distance": 0.0,
                } for s in sections]
                return ctx, query, [s["doc_id"] for s in sections], 0.0, hits
        return "", query, [], 999.0, []
    else:
        # 未启用混合检索，或 BM25 无结果，只用向量
        chunks = vector_chunks

    if not chunks:
        return "", query, [], 999.0, []

    # 记录最佳相关性（最小距离）
    best_distance = min(chunk.get("distance", 999.0) for chunk in chunks)

    # 记录命中的文档 id（保持首次出现顺序）
    hit_doc_ids: list[str] = []
    for chunk in chunks:
        did = str(chunk.get("doc_id", ""))
        if did and did not in hit_doc_ids:
            hit_doc_ids.append(did)

    # 5. 去重（按 doc_id:section_id 去重；同 section 的多个 chunk 取最小 distance）
    seen_sections: set = set()
    sections: list[dict] = []
    for chunk in chunks:
        sid = chunk.get("section_id")
        doc_id = chunk.get("doc_id", "")
        key = f"{doc_id}:{sid}" if sid is not None else f"chunk_{chunk.get('chunk_id', 0)}"
        if key in seen_sections:
            continue
        seen_sections.add(key)
        si_key = f"{doc_id}:{sid}" if sid is not None else ""
        si = vector_store._section_index.get(si_key, {})
        sections.append({
            "title": chunk.get("section_title") or chunk.get("source", ""),
            "text": chunk.get("section_text", chunk["text"]),
            "summary": si.get("summary", ""),
            "doc_id": str(doc_id),
            "section_id": sid,
            "distance": chunk.get("distance", 999.0),
        })

    # 6. 拼接（统一用全文）
    context_parts = []
    total_chars = 0
    # 预加载文档名映射（用于在片段 header 里显示文档名）
    from app.store import knowledge as kb
    doc_names = {}
    for doc_id in hit_doc_ids:
        doc = kb.get_document(int(doc_id))
        if doc:
            doc_names[doc_id] = doc["name"]

    for i, sec in enumerate(sections, 1):
        title = sec["title"]
        text = sec.get("text", "")
        if not text:
            continue
        # header 格式：[片段 N: 《文档名》 > 章节标题]
        doc_id = sec.get("doc_id", "")
        doc_name = doc_names.get(doc_id, "")
        header = f"[片段 {i}: 《{doc_name}》 > {title}]\n" if doc_name else f"[片段 {i}: {title}]\n"
        remaining = MAX_CONTEXT_CHARS - total_chars - len(header) - 20
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[:remaining] + "..."
        context_parts.append(header + text)
        total_chars += len(header) + len(text)

    # 7. 构建段落级引用列表（供前端展示具体命中段落）
    hits = []
    for sec in sections:
        snippet = sec.get("text", "")[:200]
        hits.append({
            "doc_id": sec["doc_id"],
            "section_id": sec["section_id"],
            "section_title": sec["title"],
            "snippet": snippet,
            "distance": sec["distance"],
        })

    return "\n\n---\n\n".join(context_parts), query, hit_doc_ids, best_distance, hits


def build_rag_prompt(user_message: str, use_knowledge: bool = True) -> str:
    """构建 RAG prompt。"""

    if not use_knowledge:
        return user_message

    context, _ = retrieve_context(user_message)

    if not context:
        return user_message

    return (
        "请基于以下知识库内容回答用户问题。\n"
        "上下文可能包含多个文档/版本的内容，注意区分来源。\n"
        "对比类问题请主动归纳各版本的差异。\n"
        "知识库中没有的信息，不要自行补充。\n\n"
        f"【知识库内容】\n{context}\n\n"
        f"【用户问题】\n{user_message}"
    )
