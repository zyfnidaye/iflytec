"""知识库检索工具集 —— agentic search + RAG 结合，保证"完全按文档、周全准确"。

设计（借鉴 Claude Code 的 Glob/Grep/Read + RAG 语义入口）：
- list_knowledge_docs : 列出有哪些文档（对应 Glob，先看全局）
- retrieve_knowledge  : RAG 完整管线语义检索（doc filter + 向量 + BM25 + 全文拼接），
                        返回权威上下文 + 命中文档 id 列表（告诉 agent 接下来能 read 哪些）
- grep_knowledge      : BM25 关键词精确检索（对应 Grep），可限定文档，返回命中位置
- read_document       : 按 doc_id 读整篇原文（对应 Read），带 offset/limit 分页，
                        枚举/对比类问题靠它读全、逐条列举、绝不遗漏采样

agent 循环：retrieve 定位 → 判断够不够/周全 → 不够换 query 重试 or grep 精确定位
           → 枚举题 read_document 读全文 → 严格基于原文回答。

不写死关键词、不写死版本号 —— 所有判断由 agent 根据文档名和检索结果自行决定。
"""
import re

from langchain_core.tools import tool


@tool
def list_knowledge_docs() -> str:
    """列出知识库中所有已索引文档（按文件夹分组，含 doc_id、名称、字数）。

    回答任何接口/API/技术文档问题前先调用它，了解知识库里有哪些文档，
    并拿到 doc_id 以便后续用 read_document 读整篇原文。
    """
    from app.store import knowledge as kb

    docs = kb.list_documents()
    if not docs:
        return "知识库为空，尚未上传任何文档。"

    # 按 folder 分组（未来嵌套时可递归渲染树形，现在先扁平分组）
    by_folder = {}
    for d in docs:
        folder = d.get("folder") or "（未分类）"
        by_folder.setdefault(folder, []).append(d)

    lines = ["知识库文档列表（按文件夹分组）：\n"]
    for folder in sorted(by_folder.keys()):
        docs_in_folder = by_folder[folder]
        lines.append(f"\n📁 {folder}（{len(docs_in_folder)}篇）")
        for d in docs_in_folder:
            name = d["name"]
            status = d["status"]
            chars = d.get("char_count", 0)
            lines.append(f"  [doc_id={d['id']}] {name}（{chars}字, {status}）")

    return (
        "\n".join(lines) +
        "\n\n提示：retrieve_knowledge 可传 folder 参数定向检索某个文件夹。用 read_document(doc_id) 可读完整原文。"
    )


@tool
def retrieve_knowledge(query: str, folder: str | None = None) -> str:
    """【首选】语义检索知识库，返回最相关的权威原文片段。

    走完整 RAG 管线：自动匹配相关文档 → 向量语义检索 → BM25 关键词兜底 → 拼接全文。
    这是定位答案的首选工具：不知道确切关键词、想快速找到"答案大概在哪些文档"时用它。

    Args:
        query: 检索问题
        folder: 可选，指定只在某个文件夹的文档里检索（先用 list_knowledge_docs
                查看有哪些文件夹）。按问题类型定向检索能显著提升精度，例如报错排障
                问题查「FAQ」文件夹、接口问题查「产品接口文档」文件夹。不传则全库检索。

    返回内容包含命中的文档 id 列表。若检索结果不足以周全回答（尤其是"有哪些/全部/
    对比"这类枚举问题），请对命中的文档调用 read_document 读整篇原文，逐条核对，
    不要只依赖这里返回的片段（片段是按相似度采样的，可能不完整）。

    结果不理想时：换个说法/换关键词重新调用本工具，或用 grep_knowledge 精确定位。
    """
    from app.rag.retrieval import retrieve_context_ex
    from app.agent.workspace_context import mark_kb_retrieve_done, record_citations

    # 指定 folder：先拿该文件夹（含子文件夹）所有 doc_id，限定检索范围
    doc_ids = None
    if folder:
        from app.store import knowledge as kb
        ids = kb.get_doc_ids_by_folder(folder)
        if not ids:
            return f"文件夹「{folder}」为空或不存在。用 list_knowledge_docs 查看有哪些文件夹。"
        doc_ids = [str(i) for i in ids]

    context, _q, hit_doc_ids, best_distance, hits = retrieve_context_ex(query, doc_ids=doc_ids)

    # 记录段落级引用（跨轮累积去重，供前端展示；不影响返回给模型的字符串）
    if hits:
        record_citations(hits)

    if not context:
        mark_kb_retrieve_done(has_result=False)
        return (
            f"知识库中未找到与「{query}」相关的内容。\n\n"
            "这可能意味着：\n"
            "1. 该问题超出知识库覆盖范围（通用/外部信息）\n"
            "2. 查询表述与文档用词不匹配，可尝试换关键词重新检索\n"
            "3. 用 grep_knowledge 对核心关键词做精确匹配二次确认\n\n"
            "若双重确认知识库确实无此内容，请在回答末尾加上：\n"
            "「如需进一步帮助，请联系技术支持 yfzhang79」"
        )

    # 相关性阈值判断：余弦距离 > 0.42 视为低质量匹配（假命中）
    # 余弦距离范围 [0, 2]：0=完全相同，1=正交，2=完全相反
    # 实测值："Java最新版本"=0.426, "Python最新版本"=0.417, "Go最新版本"=0.509
    # 真相关查询："计量授权"=0.354, "签名鉴权"=0.298
    # 设为 0.42 可过滤技术栈名称的假命中，保留真正相关的业务文档
    RELEVANCE_THRESHOLD = 0.4

    # 把 doc_id 列表映射成文档名（用于给 agent 的 header，引用时显示文档名而不是 id）
    doc_names = []
    doc_mapping_lines = []  # 给 agent 的映射表
    if hit_doc_ids:
        from app.store import knowledge as kb
        for did in hit_doc_ids:
            doc = kb.get_document(int(did))
            if doc:
                name = doc['name']
                doc_names.append(f"《{name}》")
                doc_mapping_lines.append(f"  - doc_id={did} → 《{name}》")
    doc_names_str = "、".join(doc_names) if doc_names else "未知"
    doc_mapping = "\n".join(doc_mapping_lines) if doc_mapping_lines else ""

    if best_distance > RELEVANCE_THRESHOLD:
        # 低质量匹配：返回结果但不设 has_coverage，允许后续联网
        mark_kb_retrieve_done(has_result=False)
        header = (
            f"检索到部分相关内容（来源文档：{doc_names_str}），但相关性较低（distance={best_distance:.3f}）：\n\n"
            f"命中文档映射（引用时用文档名）：\n{doc_mapping}\n\n"
        )
        footer = (
            "\n\n---\n"
            "⚠️ 这些内容与查询的相关性不高，可能不是你要找的答案。\n"
            "建议：换关键词重新检索，或使用 web_search 查找外部信息。"
        )
    else:
        # 高质量匹配：设 has_coverage，阻止联网（优先使用知识库）
        mark_kb_retrieve_done(has_result=True)
        header = (
            f"检索到相关内容（来源文档：{doc_names_str}）：\n\n"
            f"命中文档映射（引用时用文档名）：\n{doc_mapping}\n\n"
        )
        # footer 分场景：只有「枚举/对比」类问题才引导去看文档章节目录
        # （这类问题片段采样易漏，看目录能逐条列全）；普通问题给收敛式收尾，
        # 避免每次都勾着模型再调一轮徒增延迟。
        # 注意：read_document 现在是「先目录、再按章读」，不再一次性拉整篇。
        _ENUM_HINTS = ("哪些", "全部", "所有", "列举", "枚举", "对比", "区别", "差异", "清单", "有几")
        if any(h in query for h in _ENUM_HINTS):
            footer = (
                "\n\n---\n"
                "这是枚举/对比类问题，片段是按相似度采样的可能不完整。"
                f"请对上述文档调用 read_document(doc_id) 先看章节目录逐条列全，"
                "再按需 read_document(doc_id, sections=[...]) 读具体章节核对，切勿只凭片段作答。"
            )
        else:
            footer = (
                "\n\n---\n"
                "若以上内容已足够回答，请直接基于它作答；"
                "仅当明显不完整时才用 read_document(doc_id) 看目录、再按章精读。"
            )

    return header + context + footer



@tool
def grep_knowledge(keyword: str, doc_id: int | None = None, folder: str | None = None) -> str:
    """【精确】按关键词在知识库里做 BM25 关键词匹配，返回命中的段落及所属文档。

    适合已知确切术语（接口名、路径、版本号、字段名）时精确定位，作为语义检索的补充。

    Args:
        keyword: 关键词
        doc_id: 可选，只在指定文档内搜索
        folder: 可选，只在指定文件夹的文档内搜索（与 doc_id 互斥，优先用 doc_id）

    返回每条命中的：所属文档、段落标题、匹配片段。命中后可用 read_document 读该文档全文。
    """
    from app.rag.retrieval import _keyword_search
    from app.agent.workspace_context import mark_kb_grep_done

    results = _keyword_search(keyword, top_k=20)
    if not results:
        mark_kb_grep_done(has_result=False)
        return (
            f"关键词 '{keyword}' 未匹配到任何段落。\n"
            "若已做过语义检索(retrieve_knowledge)且也未命中，说明知识库确实无此内容。\n"
            "此时可使用 web_search 查找外部信息。"
        )

    mark_kb_grep_done(has_result=True)

    # 按 doc_id 或 folder 过滤（doc_id 优先）
    if doc_id is not None:
        prefix = f"{doc_id}:"
        results = [r for r in results if str(r.get("key", "")).startswith(prefix)]
        if not results:
            return f"在 doc_id={doc_id} 内未匹配到关键词 '{keyword}'。"
    elif folder is not None:
        from app.store import knowledge as kb
        folder_doc_ids = set(str(i) for i in kb.get_doc_ids_by_folder(folder))
        if not folder_doc_ids:
            return f"文件夹「{folder}」为空或不存在。"
        # key 形如 "doc_id:section_id"
        results = [r for r in results if str(r.get("key", "")).split(":", 1)[0] in folder_doc_ids]
        if not results:
            return f"在文件夹「{folder}」内未匹配到关键词 '{keyword}'。"

    lines = [f"关键词 '{keyword}' 命中 {len(results)} 段："]
    from app.store import knowledge as kb
    for i, r in enumerate(results, 1):
        key = str(r.get("key", ""))
        did = key.split(":", 1)[0] if ":" in key else "?"
        title = r.get("title", "")
        body = (r.get("summary") or r.get("text", ""))[:300].replace("\n", " ")
        # 把 doc_id 换成文档名
        doc = kb.get_document(int(did)) if did.isdigit() else None
        doc_name = f"《{doc['name']}》" if doc else f"doc_id={did}"
        lines.append(f"[{i}] {doc_name} | {title}\n    {body}")

    lines.append("\n提示：read_document(doc_id) 先返回该文档章节目录，再按需 read_document(doc_id, sections=[...]) 读具体章节正文。")
    return "\n\n".join(lines)


# 一次性返回全部选定 section 的正文上限（防超大文档一次读爆上下文）
_READ_MAX_CHARS = 16000
# 兜底：文档没有 section 索引时，回退按字符切页的每页大小
_FALLBACK_PAGE_CHARS = 8000


@tool
def read_document(doc_id: int, sections: list[int] | None = None) -> str:
    """【按目录读原文】读取某篇文档——不传 sections 时先给「章节目录」，传了才给对应正文。

    文档在索引时已按章节切好。本工具分两步用，避免把整篇大文档一次性灌进上下文：

    1) 先只传 doc_id → 返回该文档的**章节目录**（每章的 section_id、标题、字数），
       不含正文。枚举/对比类问题（"有哪些/全部/列举"）看这份目录就能逐条列全、不漏。
    2) 再传 sections=[要读的 section_id 列表] → 只返回这几章的完整正文，按需精读。

    典型用法：
      read_document(101)                 # 先看目录，了解全篇结构
      read_document(101, sections=[20,22]) # 只读第 20、22 章正文

    参数：
    - doc_id   : 文档 id（来自 list_knowledge_docs / retrieve_knowledge / grep_knowledge）
    - sections : 要读取正文的 section_id 列表；缺省（None）则返回章节目录。
    """
    from app.store import knowledge as kb
    from app.rag.vectorstore import get_vector_store

    doc = kb.get_document(doc_id)
    if doc is None:
        return f"未找到 doc_id={doc_id} 的文档。请先用 list_knowledge_docs 确认可用的 doc_id。"

    vs = get_vector_store()
    doc_key = str(doc_id)
    catalog = vs.list_sections(doc_key)

    # 文档没有 section 索引（老数据/解析未分章）→ 回退到按字符切页读原文，
    # 保证任何文档都能读到，不因缺索引而彻底读不了。
    if not catalog:
        return _read_by_chars(doc_id, doc, sections)

    # ── 模式一：不传 sections → 返回章节目录 ──
    if not sections:
        total_chars = sum(s["chars"] for s in catalog)
        lines = [
            f"【{doc['name']}】(doc_id={doc_id}) 章节目录，共 {len(catalog)} 章 / 约 {total_chars} 字：\n"
        ]
        for s in catalog:
            lines.append(f"  [section_id={s['section_id']}] {s['title']}（{s['chars']}字）")
        lines.append(
            "\n提示：枚举/对比类问题看以上目录即可逐条列全。"
            f"要读某章正文请调用 read_document(doc_id={doc_id}, sections=[章节id...])，可一次传多章。"
        )
        return "\n".join(lines)

    # ── 模式二：传了 sections → 返回对应正文（有字符上限保护） ──
    got = vs.get_sections(doc_key, sections)
    if not got:
        valid = ", ".join(str(s["section_id"]) for s in catalog)
        return (
            f"未找到 doc_id={doc_id} 中的 section {sections}。"
            f"可用的 section_id：{valid}"
        )

    parts = [f"【{doc['name']}】(doc_id={doc_id}) 选读 {len(got)} 章：\n"]
    used = 0
    truncated = []
    for sec in got:
        body = sec["text"]
        remaining = _READ_MAX_CHARS - used
        if remaining <= 0:
            truncated.append(sec["section_id"])
            continue
        if len(body) > remaining:
            body = body[:remaining] + "…"
            truncated.append(sec["section_id"])
        parts.append(f"### [section_id={sec['section_id']}] {sec['title']}\n{body}")
        used += len(body)

    if truncated:
        parts.append(
            f"\n---\n[已达单次读取上限 {_READ_MAX_CHARS} 字，section {truncated} 被截断/略过。"
            f"如需完整内容请分批调用 read_document(doc_id={doc_id}, sections=[...])。]"
        )
    return "\n\n".join(parts)


def _read_by_chars(doc_id: int, doc: dict, sections: list[int] | None) -> str:
    """兜底：文档无 section 索引时，按字符切页读原文。
    复用 sections[0] 当作页码（第几页，从 0 起），保持单参数签名不额外加 offset。"""
    from app.store import knowledge as kb

    text = kb.load_text(doc_id)
    if not text:
        return f"doc_id={doc_id}（{doc['name']}）没有可读正文（可能解析失败或为空）。"

    total = len(text)
    page = (sections[0] if sections else 0) or 0
    if page < 0:
        page = 0
    offset = page * _FALLBACK_PAGE_CHARS
    if offset >= total:
        return f"page={page} 已超出文档范围（共 {total} 字），无更多内容。"

    end = min(offset + _FALLBACK_PAGE_CHARS, total)
    header = f"【{doc['name']}】(doc_id={doc_id}) 第 {page} 页 字符 {offset}-{end}/{total}（本文档无章节索引，按页读）\n\n"
    if end < total:
        footer = f"\n\n---\n[还有内容未读。继续读请调用 read_document(doc_id={doc_id}, sections=[{page + 1}])。]"
    else:
        footer = "\n\n---\n[已读到文档末尾。]"
    return header + text[offset:end] + footer


# 导出工具列表
KNOWLEDGE_TOOLS = [
    list_knowledge_docs,
    retrieve_knowledge,
    grep_knowledge,
    read_document,
]
