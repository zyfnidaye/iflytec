"""文档分块和索引到向量库。

两级索引策略：
1. 第一级：按 Markdown 标题切割为 section
2. 第二级：section 内部按 H4 边界 + 字符级切为 chunk
3. 检索时：小块匹配 → 反向定位完整 section → 拼接为上下文
"""
import re

from app.rag.config import (
    MIN_HEADING_LEVEL,
    MAX_SECTION_SIZE,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    SECTION_OVERLAP,
)


def split_sections(
    text: str,
    max_section_size: int = MAX_SECTION_SIZE,
    min_heading_level: int = MIN_HEADING_LEVEL,
) -> list[dict]:
    """将文档按 Markdown 标题边界分割为 section。

    min_heading_level 指定在**哪一级**标题处切分：
    - 1: 每个标题都切
    - 3: 只在 ### 处切，#/## 作为 metadata 前缀注入，#### 留在 section 内

    例如 API 文档 min_heading_level=3：
      # 系统名              → metadata 前缀
      ## 功能模块            → metadata 前缀
      ### POST /v2/upload   → 唯一切分点
      #### 请求参数          → 留在 section 内
      #### 返回示例          → 留在 section 内

    Returns:
        [{"section_id": 0, "text": "...", "title": "..."}, ...]
    """
    sections = []
    HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
    # SECTION_OVERLAP from config

    lines = text.split("\n")
    current_section: list[str] = []
    current_title = "引言"
    heading_stack: list[tuple[int, str]] = []
    # 上下文标题：level < min_heading_level 的标题缓存，注入每个 section 开头
    context_headings: list[str] = []
    section_id = 0

    def _emit_section(section_text: str, title: str):
        nonlocal section_id
        if not section_text.strip():
            return
        # 过滤纯标题空壳（正文不足 80 字符跳过）
        if len(section_text.strip()) < 80:
            return
        # 上下文标题（# / ##）已包含在 title 中，不注入 chunk 文本，
        # 避免同一文档的所有 chunk 共享 ~200 字相同前缀、稀释 embedding 区分度
        if len(section_text) > max_section_size:
            step = max_section_size - SECTION_OVERLAP
            for i in range(0, len(section_text), step):
                sub = section_text[i : i + max_section_size]
                if sub.strip():
                    sections.append({
                        "section_id": section_id,
                        "text": sub,
                        "title": f"{title} (第 {i // step + 1} 部分)",
                    })
                    section_id += 1
        else:
            sections.append({
                "section_id": section_id,
                "text": section_text,
                "title": title,
            })
            section_id += 1

    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            title_text = m.group(2).strip()

            # 更新标题栈
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title_text))

            if level < min_heading_level:
                # 低于切分级别 → 不切，只记录为上下文 metadata
                context_headings.append(line)
                current_section.append(line)
            elif level == min_heading_level:
                # 命中了切分级别（如 ###）→ 保存上一个 section，开始新的
                if current_section:
                    _emit_section("\n".join(current_section).strip(), current_title)
                current_title = " > ".join(t for _, t in heading_stack)
                current_section = [line]
            else:
                # 更深级别（如 ####）→ 不切，留在当前 section 内
                current_section.append(line)
        else:
            current_section.append(line)

    if current_section:
        _emit_section("\n".join(current_section).strip(), current_title)

    return sections if sections else [{"section_id": 0, "text": text, "title": "全文"}]


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """将长文本按语义边界分块。

    1. 优先在 #### 标题边界切分（每个接口独立成块）
    2. 其次在段落边界、句子边界切分
    """
    if not text or len(text) <= chunk_size:
        return [text] if text else []

    # 优先按 H4 标题边界切分（保留标题行在每块开头）
    h4_chunks = _split_by_headings(text, level=4)
    if len(h4_chunks) > 1:
        # H4 子块可能仍超长，递归处理
        result = []
        for hc in h4_chunks:
            if len(hc) > chunk_size:
                result.extend(_char_chunk(hc, chunk_size, overlap))
            else:
                if hc.strip():
                    result.append(hc.strip())
        return result

    return _char_chunk(text, chunk_size, overlap)


def _split_by_headings(text: str, level: int = 4) -> list[str]:
    """按 H4 标题切分文本，相邻块之间有内容重叠（滑动窗口）。

    每块包含：前一块的后半段 + 当前块 + 下一块的前半段。
    这样每个接口至少出现在 2-3 个相邻 chunk 中。
    """
    prefix = "#" * level + " "
    lines = text.split("\n")
    raw_chunks: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if line.startswith(prefix):
            if current and any(l.strip() for l in current):
                raw_chunks.append(current)
            current = [line]
        else:
            current.append(line)

    if current and any(l.strip() for l in current):
        raw_chunks.append(current)

    if len(raw_chunks) <= 1:
        return [text]

    # 滑动窗口：每块拼接 前一块尾部 + 当前块 + 后一块头部
    result: list[str] = []
    for i, chunk_lines in enumerate(raw_chunks):
        parts: list[str] = []

        # 前一块的内容尾部（取后 1/3）
        if i > 0:
            prev = raw_chunks[i - 1]
            third = max(1, len(prev) // 3)
            parts.extend(prev[-third:])

        # 当前块（合并）去重边界
        parts.extend(chunk_lines)

        # 后一块的内容头部（取前 1/3）
        if i < len(raw_chunks) - 1:
            nxt = raw_chunks[i + 1]
            third = max(1, len(nxt) // 3)
            parts.extend(nxt[:third])

        result.append("\n".join(parts))

    return result


def _char_chunk(text: str, chunk_size: int, overlap: int) -> list[str]:
    """字符级分块：优先在段落/句子边界切分。"""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        if end < len(text):
            cut = -1
            for sep in ("\n\n", "\n", "。", "！", "？", ". ", "! ", "? "):
                pos = chunk.rfind(sep)
                if pos > chunk_size * 0.4:
                    cut = pos + len(sep)
                    break
            if cut > 0:
                chunk = chunk[:cut]
                end = start + len(chunk)

        chunk = chunk.strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap

    return chunks


def _detect_heading_level(text: str) -> int:
    """根据文档内各层级标题数量自动选择最合适的切分级别。

    策略：找标题数量最多的那个层级；如果有多个层级数量相近，选较深的一级。
    例如 H2=3, H3=8, H4=10 → 返回 4（#### 最多且足够细）。
    """
    counts = {lv: 0 for lv in range(1, 7)}
    for line in text.split("\n"):
        s = line.strip()
        for lv in range(1, 7):
            prefix = "#" * lv + " "
            if s.startswith(prefix) and not s.startswith("#" * (lv + 1) + " "):
                counts[lv] += 1
                break

    # 从 H2 开始找：有足够标题数的层级，优先深的
    best = 3  # fallback
    for lv in range(2, 6):
        if counts[lv] >= 3 and counts[lv] >= counts.get(best, 0) * 0.5:
            best = lv
    return best


def _make_summary(section_text: str, section_title: str) -> str:
    """从 section 原文中自动提取摘要：标题 + 路径 + 功能简述。

    不需 LLM——用已有标题、API 路径、首句正文。
    """
    parts = [section_title]

    # 提取所有 API 路径（最多 5 个）
    paths = list(dict.fromkeys(
        re.findall(r"(?:POST|GET|DELETE|PUT)\s*:?\s*(/?\S+)", section_text)
    ))
    if paths:
        parts.append(", ".join(paths[:5]))

    # 提取首句功能描述：取标题后第一句含中文的文本行（保留原文标点，40-80 字）
    lines = section_text.split("\n")
    desc = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("```") or stripped.startswith("|"):
            continue
        # 跳过纯路径、纯英文行
        if not re.search(r"[一-鿿]", stripped):
            continue
        # 跳过太短的（如纯标题残留）
        if len(stripped) < 10:
            continue
        desc = stripped[:80]
        break

    if desc:
        parts.append(desc)

    return " — ".join(parts)


def index_document(doc_id: str, text: str, source: str = ""):
    """将文档分块并索引到向量库（两级索引：大分→小块）。

    Args:
        doc_id: 文档 ID
        text: 文档全文
        source: 文档来源（文件名或 URL）
    """
    from app.rag.vectorstore import get_vector_store

    # 自动检测切分级别
    best_level = _detect_heading_level(text)

    # 第一级：按标题边界切 section
    sections = split_sections(text, min_heading_level=best_level)
    if not sections:
        return

    # 第二级：每个 section 内部再分成小块
    all_chunks = []
    for section in sections:
        small_chunks = chunk_text(section["text"])
        summary = _make_summary(section["text"], section["title"])

        for i, chunk_text_content in enumerate(small_chunks):
            all_chunks.append({
                "text": chunk_text_content,
                "chunk_id": len(all_chunks),
                "section_id": section["section_id"],
                "section_title": section["title"],
                "section_text": section["text"],
                "section_summary": summary,
                "source": source,
            })

    if not all_chunks:
        return

    vector_store = get_vector_store()
    vector_store.add_documents(doc_id, all_chunks)


def delete_document_index(doc_id: str):
    """从向量库删除文档。

    Args:
        doc_id: 文档 ID
    """
    from app.rag.vectorstore import get_vector_store

    vector_store = get_vector_store()
    vector_store.delete_document(doc_id)
