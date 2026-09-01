"""向量库一致性守护任务。

后台 asyncio 循环，每隔 vector_guard_interval 秒自检一次向量库与知识库
是否对应，发现不一致（孤儿向量 / 缺失索引）自动修复并记录日志。
"""
import asyncio
import logging

from app.config import get_settings
from app.rag.sync import sync_vectorstore

logger = logging.getLogger("vector_guardian")

# 后台任务句柄，供启停管理
_task: asyncio.Task | None = None


async def _guard_loop():
    """守护循环：定期同步向量库。"""
    interval = get_settings().vector_guard_interval
    logger.info(f"向量库守护任务启动，检查间隔 {interval} 秒")

    while True:
        try:
            await asyncio.sleep(interval)
            # sync 是同步阻塞调用，放到线程池执行，避免卡住事件循环
            result = await asyncio.to_thread(sync_vectorstore)
            removed = result["removed_orphans"]
            indexed = result["reindexed"]
            if removed or indexed:
                logger.warning(
                    f"向量库自检发现不一致并已修复："
                    f"清除孤儿 {removed}，补索引 {indexed}"
                )
            else:
                logger.info(
                    f"向量库自检通过，共 {result['total_docs']} 篇文档，一致。"
                )
        except asyncio.CancelledError:
            logger.info("向量库守护任务收到停止信号，退出。")
            break
        except Exception as e:
            # 单次失败不影响后续循环
            logger.error(f"向量库自检出错（忽略，下次继续）：{e}")


def start_guardian():
    """启动守护任务（应用启动时调用）。interval<=0 则不启动。"""
    global _task
    interval = get_settings().vector_guard_interval
    if interval <= 0:
        logger.info("向量库守护任务已禁用（vector_guard_interval<=0）")
        return
    if _task is None or _task.done():
        _task = asyncio.create_task(_guard_loop())


async def stop_guardian():
    """优雅停止守护任务（应用关闭时调用）。"""
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
