"""会话历史接口：列表 / 详情 / 删除。"""
from fastapi import APIRouter, HTTPException

from app.store import conversations as convo

router = APIRouter()


@router.get("/conversations")
async def list_conversations():
    return {"conversations": convo.list_conversations()}


@router.get("/conversations/{thread_id}")
async def get_conversation(thread_id: str):
    messages = convo.get_messages(thread_id)
    if not messages:
        # 空会话或不存在：返回空列表而非报错，前端好处理
        return {"thread_id": thread_id, "messages": []}
    return {"thread_id": thread_id, "messages": messages}


@router.delete("/conversations/{thread_id}")
async def delete_conversation(thread_id: str):
    convo.delete_conversation(thread_id)
    return {"ok": True}
