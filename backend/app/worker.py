"""简单的后台任务队列 worker。

用法：
    python -m app.worker

在独立进程中运行，轮询任务队列并执行耗时操作。
"""
import time
import json
from pathlib import Path
from app.config import get_settings
from app.knowledge.ingest import fetch_url, crawl_site, parse_file
from app.store import knowledge as kb
from app.rag.indexing import index_document
from app.api.knowledge import _structurize_text, _dated_dir

TASK_QUEUE_DIR = Path(get_settings().store_path) / "task_queue"
TASK_QUEUE_DIR.mkdir(parents=True, exist_ok=True)


def process_url_task(task_data):
    """处理 URL 抓取任务。"""
    doc_id = task_data["doc_id"]
    url = task_data["url"]
    crawl = task_data["crawl"]
    max_depth = task_data.get("max_depth", 2)
    max_pages = task_data.get("max_pages", 30)

    try:
        print(f"[Worker] Processing URL task: doc_id={doc_id}, url={url}, crawl={crawl}")

        # 抓取
        if crawl:
            title, text, _pages = crawl_site(url, max_depth, max_pages)
            html = None
        else:
            title, text, html = fetch_url(url)

        # 结构化
        processed_text = _structurize_text(text, is_html=True)
        char_count = len(processed_text)

        # 更新数据库
        kb.save_text(doc_id, processed_text)
        from app.store.knowledge import _get_conn, _lock
        with _lock:
            conn = _get_conn()
            conn.execute(
                "UPDATE documents SET name = ?, char_count = ?, size = ? WHERE id = ?",
                (title, char_count, char_count, doc_id)
            )
            conn.commit()

        # 索引到向量库
        index_document(str(doc_id), processed_text, url)

        # 保存原始 HTML
        raw_path = _dated_dir("url") / f"{doc_id}.html"
        raw_path.write_text(html if html is not None else text, encoding="utf-8")
        rel_path = raw_path.relative_to(get_settings().upload_path).as_posix()
        kb.update_file_path(doc_id, rel_path)

        # 标记为 ready
        kb.update_status_and_char_count(doc_id, "ready", char_count)
        print(f"[Worker] Completed doc_id={doc_id}, {char_count} chars")

    except Exception as e:
        print(f"[Worker] Failed doc_id={doc_id}: {e}")
        kb.update_status_and_char_count(doc_id, "failed", 0)
        from app.store.knowledge import _get_conn, _lock
        with _lock:
            conn = _get_conn()
            conn.execute(
                "UPDATE documents SET error = ? WHERE id = ?",
                (str(e), doc_id)
            )
            conn.commit()


def process_file_task(task_data):
    """处理文件上传任务。"""
    doc_id = task_data["doc_id"]
    file_path = task_data["file_path"]
    filename = task_data["filename"]
    ext = task_data["ext"]

    try:
        print(f"[Worker] Processing file task: doc_id={doc_id}, file={filename}")

        # 解析
        data = Path(file_path).read_bytes()
        text = parse_file(data, ext)

        # 结构化
        is_html = ext.lower() in {'.html', '.htm'}
        processed_text = _structurize_text(text, is_html=is_html)
        char_count = len(processed_text)

        # 更新数据库
        kb.save_text(doc_id, processed_text)
        from app.store.knowledge import _get_conn, _lock
        with _lock:
            conn = _get_conn()
            conn.execute(
                "UPDATE documents SET char_count = ? WHERE id = ?",
                (char_count, doc_id)
            )
            conn.commit()

        # 索引
        index_document(str(doc_id), processed_text, filename)

        # 标记为 ready
        kb.update_status_and_char_count(doc_id, "ready", char_count)
        print(f"[Worker] Completed doc_id={doc_id}, {char_count} chars")

    except Exception as e:
        print(f"[Worker] Failed doc_id={doc_id}: {e}")
        kb.update_status_and_char_count(doc_id, "failed", 0)


def run_worker():
    """主循环：轮询任务队列并处理。"""
    print(f"[Worker] Started, watching {TASK_QUEUE_DIR}")

    while True:
        # 查找所有 .json 任务文件
        task_files = sorted(TASK_QUEUE_DIR.glob("*.json"))

        if task_files:
            task_file = task_files[0]
            print(f"[Worker] Found task: {task_file.name}")

            try:
                task_data = json.loads(task_file.read_text(encoding="utf-8"))
                task_type = task_data.get("type")

                if task_type == "url":
                    process_url_task(task_data)
                elif task_type == "file":
                    process_file_task(task_data)
                else:
                    print(f"[Worker] Unknown task type: {task_type}")

                # 处理完成，删除任务文件
                task_file.unlink()

            except Exception as e:
                print(f"[Worker] Task processing error: {e}")
                # 重命名为 .error 避免重复处理
                task_file.rename(task_file.with_suffix(".error"))

        # 休眠 1 秒
        time.sleep(1)


if __name__ == "__main__":
    run_worker()
