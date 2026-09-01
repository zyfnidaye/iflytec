"""知识库接口：上传文件 / 抓取网页 / 列表 / 预览 / 删除。

解析成文本后存库，供预览与将来的 RAG 检索。
JSON/YAML 额外尝试加载为服务链路图（保留拓扑能力）。
"""
from datetime import date
from pathlib import Path
import asyncio
import hashlib

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
import html2text

from app.agent.tools.topology import load_topology_from_file
from app.config import get_settings
from app.knowledge import ingest
from app.store import knowledge as kb
# 懒加载：只在需要时导入（避免启动时加载 embedding 模型）
# from app.rag.indexing import index_document, delete_document_index
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

router = APIRouter()

TOPOLOGY_EXTS = {".json", ".yaml", ".yml"}


def _get_llm():
    """获取 LLM 实例（复用 agent 的配置）"""
    settings = get_settings()
    return ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url or None,  # 空字符串转 None
        timeout=120.0,
    )


def _structurize_text(raw_text: str, is_html: bool = False) -> str:
    """方案 A：结构化文本转 Markdown。

    - HTML：用 html2text 规则引擎（秒级，零成本）
    - 其他：简单清理空白符
    """
    if len(raw_text) < 100:
        return raw_text

    if is_html:
        # HTML → Markdown（保留代码块、表格、列表、标题）
        try:
            h = html2text.HTML2Text()
            h.ignore_links = False
            h.ignore_images = False
            h.ignore_emphasis = False
            h.body_width = 0  # 不自动换行
            h.unicode_snob = True
            h.skip_internal_links = True
            markdown = h.handle(raw_text)
            return markdown.strip()
        except Exception as e:
            print(f"[WARN] html2text failed: {e}, using raw text")
            return raw_text
    else:
        # 非 HTML：简单清理多余空白
        import re
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', raw_text)  # 多个空行压缩为两个
        return text.strip()


def _summarize_large_doc(structured_text: str, title: str) -> str:
    """方案 B：大文档（>5万字）额外生成摘要+目录，提升检索精度。

    在结构化文本前插入摘要和章节目录，帮助 RAG 快速定位相关内容。
    """
    prompt = f"""你的任务：为这篇大文档生成摘要和章节目录，帮助快速定位内容。

文档标题：{title}

要求：
1. 生成 200-300 字的整体摘要（核心内容、适用场景、主要章节）
2. 提取主要章节标题，生成目录（最多 20 条，格式：1. 章节名）
3. 输出格式严格按照下面的模板：

# 📄 文档摘要
{{你的摘要内容}}

# 📑 章节目录
1. {{章节1}}
2. {{章节2}}
...

---

下面是文档正文（不要在输出里重复正文，只输出摘要和目录）：

{structured_text[:50000]}
"""  # 只看前 5 万字提取目录

    try:
        llm = _get_llm()
        response = llm.invoke([HumanMessage(content=prompt)])
        summary_toc = response.content.strip()
        # 拼接：摘要+目录 + 分隔符 + 原结构化文本
        return f"{summary_toc}\n\n---\n\n{structured_text}"
    except Exception as e:
        print(f"[WARN] Summarize failed: {e}, using structured text only")
        return structured_text


async def _async_summarize_and_update(doc_id: int, structured_text: str, title: str, source: str):
    """后台异步：为大文档生成摘要，更新文本和向量库。"""
    try:
        # LLM 生成摘要（阻塞调用放在 executor 里）
        import asyncio
        loop = asyncio.get_event_loop()
        summarized_text = await loop.run_in_executor(
            None, _summarize_large_doc, structured_text, title
        )

        # 更新存储的文本
        kb.save_text(doc_id, summarized_text)

        # 重新索引（用带摘要的版本）
        from app.rag.indexing import index_document, delete_document_index
        delete_document_index(str(doc_id))
        index_document(str(doc_id), summarized_text, source=source)

        # 更新字数和状态为 ready
        final_char_count = len(summarized_text)
        kb.update_status_and_char_count(doc_id, "ready", final_char_count)

        print(f"[INFO] Document {doc_id} summarized: {final_char_count} chars, status updated to ready")

    except Exception as e:
        print(f"[ERROR] Async summarize failed for doc {doc_id}: {e}")
        # 更新状态为失败
        kb.update_status_and_char_count(doc_id, "failed", 0)


class UrlRequest(BaseModel):
    url: str
    crawl: bool = False  # True=递归抓取多页文档站；False=只抓单页
    max_depth: int = 2  # 递归深度上限
    max_pages: int = 50  # 抓取页数上限


def _category(ext: str) -> str:
    """按扩展名归类到文件夹名。"""
    ext = ext.lower().lstrip(".")
    return ext or "other"


def _dated_dir(category: str) -> Path:
    """返回 uploads/<category>/<今天日期>/ 目录，自动创建。"""
    d = get_settings().upload_path / category / date.today().isoformat()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _unique_path(directory: Path, filename: str) -> Path:
    """同名文件加序号避免覆盖。"""
    target = directory / filename
    if not target.exists():
        return target
    stem, suffix = Path(filename).stem, Path(filename).suffix
    i = 1
    while True:
        cand = directory / f"{stem}_{i}{suffix}"
        if not cand.exists():
            return cand
        i += 1


def _parse_and_store(doc_id: int, data: bytes, ext: str, file_size: int) -> tuple[str, int]:
    """解析 → 结构化 → 存正文 → 更新字数/大小。返回 (正文, 字数)。

    同步函数（含 CPU 密集的解析），调用方负责放进 executor。
    上传首次索引与替换更新共用，避免复制解析逻辑。
    """
    text = ingest.parse_file(data, ext)
    is_html = ext.lower() in {'.html', '.htm'}
    processed_text = _structurize_text(text, is_html=is_html)
    char_count = len(processed_text)

    kb.save_text(doc_id, processed_text)

    from app.store.knowledge import _get_conn, _lock
    with _lock:
        conn = _get_conn()
        conn.execute(
            "UPDATE documents SET char_count = ?, size = ? WHERE id = ?",
            (char_count, file_size, doc_id),
        )
        conn.commit()

    return processed_text, char_count


@router.post("/knowledge/upload")
async def upload_knowledge(file: UploadFile = File(...)):
    filename = file.filename or "upload.bin"
    ext = Path(filename).suffix.lower()
    data = await file.read()

    # 内容哈希去重：同一字节内容已就绪 → 直接复用，跳过解析/embedding
    content_hash = hashlib.sha256(data).hexdigest()
    existing = kb.get_document_by_hash(content_hash)
    if existing:
        return {
            "id": existing["id"],
            "name": existing["name"],
            "status": existing["status"],
            "char_count": existing["char_count"],
            "note": "内容未变化，已复用现有文档",
        }

    # 原始文件按 类型/日期 组织存放
    settings = get_settings()
    category = _category(ext)
    raw_path = _unique_path(_dated_dir(category), filename)
    raw_path.write_bytes(data)
    rel_path = raw_path.relative_to(settings.upload_path).as_posix()

    # 立即创建文档记录（状态为 indexing）
    doc_id = kb.add_document(
        filename, "file", ext or "?", len(data), "indexing", 0, None, rel_path,
        content_hash=content_hash,
    )

    # 后台异步处理（不阻塞响应）
    asyncio.create_task(
        _async_parse_and_index_file(doc_id, raw_path, filename, ext, len(data))
    )

    # 立即返回（前端不会被阻塞）
    return {
        "id": doc_id,
        "name": filename,
        "status": "indexing",
        "char_count": 0,
        "note": "",
    }


async def _async_parse_and_index_file(doc_id: int, raw_path: Path, filename: str, ext: str, file_size: int):
    """后台异步：解析文件 → 结构化 → 索引 → 可选摘要。"""
    try:
        # 步骤 1：解析文件（耗时操作放在 executor 里）
        import asyncio
        # 模块级导入被注释掉了，索引函数在函数内按需导入（与 URL 抓取路径一致）
        from app.rag.indexing import index_document
        loop = asyncio.get_event_loop()

        data = raw_path.read_bytes()

        # 步骤 2：解析 + 结构化 + 存正文 + 更新字数（共享 helper）
        processed_text, char_count = await loop.run_in_executor(
            None, _parse_and_store, doc_id, data, ext, file_size
        )

        # 回填 text_hash（正文哈希，Phase 2 diff 锚点）
        kb.set_hashes(doc_id, text_hash=hashlib.sha256(processed_text.encode("utf-8")).hexdigest())

        # 步骤 3：索引到向量库
        await loop.run_in_executor(
            None, index_document, str(doc_id), processed_text, filename
        )

        # 步骤 4：JSON/YAML 尝试加载拓扑图（不阻塞主流程）
        if ext in TOPOLOGY_EXTS:
            try:
                await loop.run_in_executor(
                    None, load_topology_from_file, str(raw_path)
                )
            except Exception:
                pass  # 静默失败

        # 步骤 5：大文档需要摘要（嵌套异步任务）
        needs_summary = char_count > 50000
        if needs_summary:
            asyncio.create_task(_async_summarize_and_update(doc_id, processed_text, filename, filename))
        else:
            # 小文档直接标记为 ready
            kb.update_status_and_char_count(doc_id, "ready", char_count)

        print(f"[INFO] Document {doc_id} parsed and indexed: {char_count} chars")

    except Exception as e:
        print(f"[ERROR] Async parse failed for doc {doc_id}: {e}")
        kb.update_status_and_char_count(doc_id, "failed", 0)
        # 更新错误信息
        from app.store.knowledge import _get_conn, _lock
        with _lock:
            conn = _get_conn()
            conn.execute(
                "UPDATE documents SET error = ? WHERE id = ?",
                (str(e), doc_id)
            )
            conn.commit()


@router.post("/knowledge/url")
async def add_url(req: UrlRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL 不能为空")

    # 立即创建文档记录（状态为 indexing）
    doc_id = kb.add_document(url, "url", "url", 0, "indexing", 0)

    try:
        # 同步等待抓取完成（会抛出异常如果失败）
        await _async_fetch_and_index_url(doc_id, req)

        # 返回最终状态
        doc = kb.get_document(doc_id)
        return {
            "id": doc_id,
            "name": doc.get("name", url),
            "status": doc.get("status", "ready"),
            "char_count": doc.get("char_count", 0),
        }
    except HTTPException:
        # 抓取失败，删除记录
        kb.delete_document(doc_id)
        raise


async def _async_fetch_and_index_url(doc_id: int, req: UrlRequest):
    """后台异步：抓取 URL → 结构化 → 索引 → 可选摘要。"""
    url = req.url.strip()

    try:
        # 步骤 1：抓取（耗时操作放在 executor 里）
        import asyncio
        # 模块级导入被注释掉了，索引函数在函数内按需导入（与文件上传路径一致）
        from app.rag.indexing import index_document
        loop = asyncio.get_event_loop()

        if req.crawl:
            title, text, _pages = await loop.run_in_executor(
                None, ingest.crawl_site, url, req.max_depth, req.max_pages
            )
            html = None
        else:
            title, text, html = await loop.run_in_executor(
                None, ingest.fetch_url, url
            )

        # 步骤 2：结构化（ingest.fetch_url 已用 lxml 提取，直接使用，不再过 html2text）
        processed_text = text.strip()
        char_count = len(processed_text)

        # 更新文档元数据
        kb.save_text(doc_id, processed_text)

        # 更新标题和字数
        from app.store.knowledge import _get_conn, _lock
        with _lock:
            conn = _get_conn()
            conn.execute(
                "UPDATE documents SET name = ?, char_count = ?, size = ? WHERE id = ?",
                (title, char_count, char_count, doc_id)
            )
            conn.commit()

        # 让出 CPU
        await asyncio.sleep(0)

        # 步骤 3：索引到向量库（分批处理，避免长时间占用 CPU）
        await loop.run_in_executor(
            None, index_document, str(doc_id), processed_text, url
        )

        # 保存原始 HTML
        raw_path = _dated_dir("url") / f"{doc_id}.html"
        raw_path.write_text(html if html is not None else text, encoding="utf-8")
        rel_path = raw_path.relative_to(get_settings().upload_path).as_posix()
        kb.update_file_path(doc_id, rel_path)

        # 步骤 4：大文档需要摘要（嵌套异步任务）
        needs_summary = char_count > 50000
        if needs_summary:
            asyncio.create_task(_async_summarize_and_update(doc_id, processed_text, title, url))
        else:
            # 小文档直接标记为 ready
            kb.update_status_and_char_count(doc_id, "ready", char_count)

        print(f"[INFO] Document {doc_id} fetched and indexed: {char_count} chars")

    except Exception as e:
        print(f"[ERROR] Async fetch failed for doc {doc_id}: {e}")
        kb.update_status_and_char_count(doc_id, "failed", 0)
        # 更新错误信息
        from app.store.knowledge import _get_conn, _lock
        with _lock:
            conn = _get_conn()
            conn.execute(
                "UPDATE documents SET error = ? WHERE id = ?",
                (str(e), doc_id)
            )
            conn.commit()
        # 重新抛出异常，让调用方知道失败了
        raise HTTPException(status_code=500, detail=f"抓取失败: {str(e)}")


# ── 飞书文档入库（从 i讯飞平台拉取 wiki 文档） ──

class FeishuDocRequest(BaseModel):
    url: str  # 完整 wiki URL 或纯 node_token


@router.post("/knowledge/feishu")
async def add_feishu_doc(req: FeishuDocRequest):
    """从飞书（i讯飞平台）拉取 wiki 文档入库，仅支持 docx 类型。"""
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL 不能为空")

    # 立即创建文档记录（状态为 indexing）
    doc_id = kb.add_document(url, "feishu", "feishu", 0, "indexing", 0)

    try:
        # 同步等待拉取完成
        await _async_fetch_and_index_feishu(doc_id, url)

        # 返回最终状态
        doc = kb.get_document(doc_id)
        return {
            "id": doc_id,
            "name": doc.get("name", url),
            "status": doc.get("status", "ready"),
            "char_count": doc.get("char_count", 0),
        }
    except HTTPException:
        # 拉取失败，删除记录
        kb.delete_document(doc_id)
        raise


async def _async_fetch_and_index_feishu(doc_id: int, url: str):
    """后台异步：拉取飞书文档、存文本、索引向量。"""
    from app.knowledge.feishu_doc import fetch_feishu_doc_async
    from app.rag.indexing import index_document

    try:
        # 1) 拉取文档（已是 async，直接 await）
        title, content = await fetch_feishu_doc_async(url)

        # 2) 更新名称和字符数
        char_count = len(content)
        from app.store.knowledge import _get_conn, _lock
        with _lock:
            conn = _get_conn()
            conn.execute(
                "UPDATE documents SET name = ?, char_count = ? WHERE id = ?",
                (title, char_count, doc_id)
            )
            conn.commit()

        # 3) 存原始正文到 kb_text/<doc_id>.txt
        text_file = get_settings().store_path / "kb_text" / f"{doc_id}.txt"
        text_file.parent.mkdir(parents=True, exist_ok=True)
        text_file.write_text(content, encoding="utf-8")

        # 4) 索引向量（同步跑在 executor 里，index_document 内部会自动分块）
        #    注意：doc_id 要传 str（index_document 签名要求），source 传标题便于溯源
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, index_document, str(doc_id), content, title)
        kb.update_status_and_char_count(doc_id, "ready", char_count)

        print(f"[INFO] Feishu doc {doc_id} fetched and indexed: {char_count} chars, title={title!r}")

    except Exception as e:
        print(f"[ERROR] Async feishu fetch failed for doc {doc_id}: {e}")
        kb.update_status_and_char_count(doc_id, "failed", 0)
        # 更新错误信息
        from app.store.knowledge import _get_conn, _lock
        with _lock:
            conn = _get_conn()
            conn.execute(
                "UPDATE documents SET error = ? WHERE id = ?",
                (str(e), doc_id)
            )
            conn.commit()
        raise HTTPException(status_code=500, detail=f"拉取失败: {str(e)}")


# ── 粘贴文本入库（用 subagent 自动整理成 markdown 结构） ──

class PasteRequest(BaseModel):
    text: str
    name: str | None = None  # 可选：用户指定名称；缺省用首行/前30字自动生成


PASTE_MIN_CHARS = 20        # 太短不值得走 LLM 整理
PASTE_MAX_CHARS = 100_000   # 太长会超 subagent max_tokens，并且分块效果差


def _extract_title(text: str, fallback: str) -> str:
    """从原始文本首行提取标题；不合适则回退 fallback。"""
    first_line = ""
    for line in text.split("\n"):
        s = line.strip().lstrip("#").strip()
        if s:
            first_line = s
            break
    if not first_line:
        return fallback
    # 首行超长时截断到 30 字
    if len(first_line) > 30:
        first_line = first_line[:30] + "..."
    return first_line


async def _structure_text_via_subagent(raw_text: str) -> str:
    """调 text-structurer subagent 把纯文本整理成规范 markdown。

    返回整理后的 markdown 文本。subagent 失败时抛出 HTTPException。
    """
    from app.agent.subagents.runner import run_subagent
    from app.agent.skills.registry import get_agent_def

    agent_def = get_agent_def("text-structurer")
    if agent_def is None:
        raise HTTPException(
            status_code=500,
            detail="text-structurer subagent 未找到（检查 store/skills/structure-text/agents/）",
        )

    # 任务提示词：直白说明输入是要整理的原文
    task = f"请把下面这段文本整理成规范的 markdown 结构化文档。直接输出整理结果，不要任何前缀说明。\n\n<原文>\n{raw_text}\n</原文>"

    result_text = ""
    error_msg = None
    async for ev in run_subagent(agent_def, task):
        kind = ev.get("kind")
        if kind == "result":
            result_text = ev.get("text", "").strip()
        elif kind == "error":
            error_msg = ev.get("message", "subagent 执行失败")

    if error_msg:
        raise HTTPException(status_code=500, detail=f"结构化失败：{error_msg}")
    if not result_text:
        raise HTTPException(status_code=500, detail="结构化失败：subagent 未产出内容")

    return result_text


@router.post("/knowledge/paste")
async def paste_knowledge(req: PasteRequest):
    """粘贴纯文本 → subagent 自动整理成 markdown → 索引入库。

    与文件上传/URL 抓取共用后续解析、索引、摘要管线。同步返回，返回时向量库已一致。
    """
    raw = (req.text or "").strip()
    if len(raw) < PASTE_MIN_CHARS:
        raise HTTPException(status_code=400, detail=f"文本过短（至少 {PASTE_MIN_CHARS} 字）")
    if len(raw) > PASTE_MAX_CHARS:
        raise HTTPException(status_code=400, detail=f"文本过长（超过 {PASTE_MAX_CHARS} 字，请拆分后再传）")

    # 1) 用 subagent 整理成 markdown
    structured_md = await _structure_text_via_subagent(raw)

    # 2) 提取标题
    fallback_name = f"粘贴文本-{date.today().isoformat()}"
    doc_name = (req.name or "").strip() or _extract_title(structured_md, fallback_name)
    if not doc_name.endswith(".md"):
        doc_name = f"{doc_name}.md"

    # 3) 归档原始 markdown（供预览/重建索引复用）
    import time as _time
    settings = get_settings()
    filename = f"paste_{int(_time.time() * 1000)}.md"
    raw_path = _unique_path(_dated_dir("paste"), filename)
    raw_path.write_text(structured_md, encoding="utf-8")
    rel_path = raw_path.relative_to(settings.upload_path).as_posix()

    # 4) 内容哈希去重（沿用文件上传的哈希机制）
    content_hash = hashlib.sha256(structured_md.encode("utf-8")).hexdigest()
    existing = kb.get_document_by_hash(content_hash)
    if existing:
        # 清理刚写的重复文件
        try:
            raw_path.unlink()
        except Exception:
            pass
        return {
            "id": existing["id"],
            "name": existing["name"],
            "status": existing["status"],
            "char_count": existing["char_count"],
            "note": "内容未变化，已复用现有文档",
        }

    char_count = len(structured_md)
    doc_id = kb.add_document(
        doc_name, "file", ".md", char_count, "indexing", 0, None, rel_path,
        content_hash=content_hash,
    )

    # 5) 存正文
    kb.save_text(doc_id, structured_md)
    kb.set_hashes(doc_id, text_hash=content_hash)  # 粘贴场景 raw = text，两者同哈希

    # 6) 同步索引到向量库（复用现有管线；小文档秒级完成）
    try:
        from app.rag.indexing import index_document
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, index_document, str(doc_id), structured_md, doc_name
        )
        kb.update_status_and_char_count(doc_id, "ready", char_count)
    except Exception as e:
        kb.update_status_and_char_count(doc_id, "failed", 0)
        from app.store.knowledge import _get_conn, _lock
        with _lock:
            conn = _get_conn()
            conn.execute("UPDATE documents SET error = ? WHERE id = ?", (str(e), doc_id))
            conn.commit()
        raise HTTPException(status_code=500, detail=f"索引失败：{e}")

    return {
        "id": doc_id,
        "name": doc_name,
        "status": "ready",
        "char_count": char_count,
    }


@router.get("/knowledge")
async def list_knowledge():
    return {"documents": kb.list_documents()}


# ── Embedding 模型切换（必须在 /knowledge/{doc_id} 之前，否则被 doc_id 路由拦截） ──

@router.get("/knowledge/embedding-model")
async def get_embedding_model_info():
    """返回当前 embedding 模型信息 + 两个 collection 的统计。"""
    from app.rag.embeddings import EmbeddingModel
    from app.rag.vectorstore import get_vector_store
    info = EmbeddingModel.get_current_model_info()
    info["collections"] = get_vector_store().all_collections_info()
    return info


@router.post("/knowledge/embedding-model")
async def switch_embedding_model(body: dict):
    """切换 embedding 模型（512d / 1024d 各自独立 collection，切换瞬间完成）。

    如果目标 collection 为空，后台自动补建索引。
    """
    from app.rag.embeddings import EmbeddingModel
    from app.rag.vectorstore import get_vector_store
    import asyncio

    model_key = body.get("model", "")
    if not model_key:
        return {"ok": False, "message": "缺少 model 参数，可选: bge-small, bge-large"}

    try:
        result = EmbeddingModel.switch_model(model_key)
    except ValueError as e:
        return {"ok": False, "message": str(e)}

    if result["changed"]:
        vs = get_vector_store()
        info = vs.collection_info(vs.dim)
        need_reindex = info["chunks"] == 0

        if need_reindex:
            asyncio.create_task(_async_reindex_all())
            return {
                "ok": True, "changed": True,
                "model": result["model"], "dim": result["dim"],
                "need_reindex": True,
                "message": f"已切换到 {model_key}（{result['dim']}d），collection 为空，后台自动建索引",
            }
        else:
            return {
                "ok": True, "changed": True,
                "model": result["model"], "dim": result["dim"],
                "need_reindex": False,
                "message": f"已切换到 {model_key}（{result['dim']}d），collection 已有 {info['chunks']} 个向量，立即可用",
            }
    else:
        return {
            "ok": True, "changed": False,
            "model": result["model"], "dim": result["dim"],
            "message": "已是当前模型，无需切换",
        }


# ========== 文件夹管理 ==========
# 注意：这些路由必须声明在 /knowledge/{doc_id} 之前，
# 否则 /knowledge/folders 会被 {doc_id} 拦截（"folders" 无法解析为 int → 422）。

class FolderCreateRequest(BaseModel):
    name: str

class FolderRenameRequest(BaseModel):
    new_name: str

class DocumentMoveRequest(BaseModel):
    folder: str | None = None  # None = 移回根目录


@router.post("/knowledge/folders")
async def create_folder(req: FolderCreateRequest):
    """创建空文件夹。"""
    try:
        return kb.create_folder(req.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/knowledge/folders")
async def list_folders():
    """列出所有文件夹,含文档数统计。"""
    return kb.list_folders()


@router.patch("/knowledge/folders/{folder_id}")
async def rename_folder(folder_id: int, req: FolderRenameRequest):
    """重命名文件夹,同步更新所有关联文档。"""
    try:
        kb.rename_folder(folder_id, req.new_name)
        return {"ok": True, "id": folder_id, "new_name": req.new_name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/knowledge/folders/{folder_id}")
async def delete_folder(folder_id: int):
    """删除空文件夹。若非空则返回 400。"""
    try:
        kb.delete_folder(folder_id)
        return {"ok": True, "id": folder_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/knowledge/{doc_id}/folder")
async def move_document(doc_id: int, req: DocumentMoveRequest):
    """移动文档到文件夹(或移回根目录)。若目标文件夹不存在,自动创建。"""
    try:
        kb.move_document_to_folder(doc_id, req.folder)
        return {"ok": True, "doc_id": doc_id, "folder": req.folder}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge/{doc_id}")
async def get_knowledge(doc_id: int):
    doc = kb.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    doc["text"] = kb.load_text(doc_id)
    return doc


class UpdateDocRequest(BaseModel):
    text: str | None = None  # 更新正文（可选）
    name: str | None = None  # 更新名称（可选）


@router.put("/knowledge/{doc_id}")
async def update_knowledge(doc_id: int, req: UpdateDocRequest):
    """编辑文档正文和/或名称，并同步重建向量索引。

    改名或改正文都会触发向量库重建，确保 source 字段与数据库一致。
    同步执行以保证返回时向量库已一致（单篇文档重建通常在秒级）。
    """
    doc = kb.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    name_changed = False
    text_changed = False
    char_count = doc["char_count"]

    # 1. 更新名称
    if req.name is not None:
        if not req.name.strip():
            raise HTTPException(status_code=400, detail="文档名称不能为空")
        if req.name.strip() != doc["name"]:
            kb.update_name(doc_id, req.name.strip())
            name_changed = True

    # 2. 更新正文
    if req.text is not None:
        new_text = req.text
        char_count = len(new_text)

        # 存新正文
        kb.save_text(doc_id, new_text)

        # 更新字数 + 状态（确保置为 ready）
        from app.store.knowledge import _get_conn, _lock
        with _lock:
            conn = _get_conn()
            conn.execute(
                "UPDATE documents SET char_count = ?, status = 'ready', error = NULL WHERE id = ?",
                (char_count, doc_id),
            )
            conn.commit()
        text_changed = True

    # 3. 如果名称或正文有变化，重建向量索引
    if name_changed or text_changed:
        from app.rag.sync import reindex_document
        loop = asyncio.get_event_loop()
        try:
            # 重新获取最新文档信息（名称可能已更新）
            updated_doc = kb.get_document(doc_id)
            # 读取最新正文
            text_to_index = kb.load_text(doc_id)
            await loop.run_in_executor(
                None, reindex_document, str(doc_id), text_to_index, updated_doc["name"]
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"更新已保存，但向量重建失败：{e}")

    return {"ok": True, "id": doc_id, "char_count": char_count}


@router.post("/knowledge/{doc_id}/replace")
async def replace_knowledge(doc_id: int, file: UploadFile = File(...)):
    """用新文件替换已有文档内容，保持同一 doc_id、不产生重复条目。

    内容未变（哈希相同）直接返回 unchanged；否则覆盖原始文件、重新解析、
    同步重建向量索引（复用 reindex_document）。同步执行，返回时向量库已一致。
    """
    doc = kb.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.get("source_type") != "file":
        raise HTTPException(status_code=400, detail="仅支持替换文件类型文档")

    data = await file.read()
    content_hash = hashlib.sha256(data).hexdigest()

    # 内容没变 → 免重建
    if content_hash == doc.get("content_hash"):
        return {"ok": True, "id": doc_id, "unchanged": True,
                "char_count": doc["char_count"], "note": "内容未变化，无需更新"}

    ext = doc.get("ext") or Path(file.filename or "").suffix.lower() or "?"

    try:
        # 覆盖原始文件：优先写回原 file_path，缺失则新建归档路径
        settings = get_settings()
        if doc.get("file_path"):
            raw_path = settings.upload_path / doc["file_path"]
            raw_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            raw_path = _unique_path(_dated_dir(_category(ext)), doc["name"])
        raw_path.write_bytes(data)
        rel_path = raw_path.relative_to(settings.upload_path).as_posix()

        loop = asyncio.get_event_loop()
        # 解析 + 结构化 + 存正文 + 更新字数
        processed_text, char_count = await loop.run_in_executor(
            None, _parse_and_store, doc_id, data, ext, len(data)
        )

        # 回填哈希 + 路径 + 状态
        kb.set_hashes(
            doc_id,
            content_hash=content_hash,
            text_hash=hashlib.sha256(processed_text.encode("utf-8")).hexdigest(),
        )
        kb.update_file_path(doc_id, rel_path)
        kb.update_status_and_char_count(doc_id, "ready", char_count)

        # 同步重建向量索引（删后重建原语）
        from app.rag.sync import reindex_document
        await loop.run_in_executor(
            None, reindex_document, str(doc_id), processed_text, doc["name"]
        )
    except HTTPException:
        raise
    except Exception as e:
        kb.update_status_and_char_count(doc_id, "failed", 0)
        raise HTTPException(status_code=500, detail=f"替换失败：{e}")

    return {"ok": True, "id": doc_id, "unchanged": False, "char_count": char_count}


@router.delete("/knowledge/{doc_id}")
async def delete_knowledge(doc_id: int):
    # 从向量库删除
    try:
        # 懒加载（模块级导入被注释以避免启动时加载 embedding 模型）
        from app.rag.indexing import delete_document_index
        delete_document_index(str(doc_id))
    except Exception as e:
        print(f"[WARN] Failed to delete document from vector store {doc_id}: {e}")

    # 从 SQLite 删除
    kb.delete_document(doc_id)
    return {"ok": True}


@router.post("/knowledge/reindex")
async def reindex_knowledge():
    """异步重建向量索引：清除孤儿向量 + 补索引缺失文档。

    用于修复因删除失败或索引失败导致的数据不一致。
    复用运行中进程已加载的 embedding 模型，不重复加载。
    立即返回，后台执行。
    """
    # 后台异步执行重建任务
    import asyncio
    asyncio.create_task(_async_reindex_all())

    return {"ok": True, "status": "reindexing", "message": "后台重建索引中，可能需要几分钟"}


async def _async_reindex_all():
    """后台异步：重建所有向量索引。"""
    try:
        from app.rag.sync import sync_vectorstore
        import asyncio

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, sync_vectorstore, True)
        print(f"[INFO] Reindex completed: {result}")
    except Exception as e:
        print(f"[ERROR] Reindex failed: {e}")

