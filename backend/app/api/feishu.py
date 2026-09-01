"""i讯飞客服机器人接入（飞书兼容协议）：事件回调 → 调 agent → 回复。

设计要点：
- i讯飞平台用飞书兼容协议，但域名是 open.xfchat.iflytek.com，且 WAF 会拦
  没有浏览器 User-Agent 的请求 → 直接用 httpx 带 UA 调 REST，不用 lark SDK。
- 事件回调要求 3 秒内响应，但 agent 回答要十几秒 → 立即 200 ACK + 后台异步处理。
- 不重构核心对话逻辑：adapter 用 httpx 内部自调 /api/chat，消费 SSE 拼出完整回答。
- thread_id 用 chat_id，天然实现每个会话独立上下文。
- event_id 去重（事件会重试）。
- URL 验证挑战 + 验签（可选加密）。
"""
import asyncio
import json
import time

import httpx
import lark_oapi as lark
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import get_settings

router = APIRouter()

# i讯飞开放平台域名（飞书兼容 API，但独立域名 + WAF）
_XF_DOMAIN = "https://open.xfchat.iflytek.com"
# WAF 拦无 UA 的请求，所有调用都带浏览器 UA
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# 已处理的 event_id（内存去重，够用；重启清空可接受）
_seen_events: set[str] = set()
_SEEN_MAX = 5000  # 防内存无限增长

# tenant_access_token 缓存（token 有效期 7200s，提前 300s 刷新）
_token_cache: dict = {"token": "", "expire_at": 0.0}


async def _get_token() -> str:
    """拿 tenant_access_token，带缓存。失败返回空串。"""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expire_at"]:
        return _token_cache["token"]
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_XF_DOMAIN}/open-apis/auth/v3/tenant_access_token/internal",
                headers={"Content-Type": "application/json", "User-Agent": _UA},
                json={"app_id": s.feishu_app_id, "app_secret": s.feishu_app_secret},
            )
        data = resp.json()
        if data.get("code") == 0:
            _token_cache["token"] = data["tenant_access_token"]
            # expire 是秒数，提前 300s 过期以留余量
            _token_cache["expire_at"] = now + data.get("expire", 7200) - 300
            return _token_cache["token"]
        print(f"[i讯飞] 拿 token 失败: {data}")
    except Exception as e:  # noqa: BLE001
        print(f"[i讯飞] 拿 token 异常: {e}")
    return ""


def _mark_seen(event_id: str) -> bool:
    """记录 event_id，返回 True 表示首次（应处理），False 表示重复（应跳过）。"""
    if not event_id:
        return True  # 没有 id 就不去重，照常处理
    if event_id in _seen_events:
        return False
    if len(_seen_events) >= _SEEN_MAX:
        _seen_events.clear()  # 简单清空，避免内存膨胀
    _seen_events.add(event_id)
    return True


def _extract_text(msg: dict) -> str:
    """从飞书消息体提取纯文本。仅处理 text 类型；富文本/图片等返回空串。"""
    if msg.get("message_type") != "text":
        return ""
    try:
        content = json.loads(msg.get("content", "{}"))
        text = content.get("text", "").strip()
        # 群聊 @机器人 会带 @_user_1 之类的占位，去掉
        import re
        text = re.sub(r"@_user_\d+", "", text).strip()
        return text
    except Exception:
        return ""


async def _ask_agent(text: str, thread_id: str) -> str:
    """内部自调 /api/chat，消费 SSE 流拼出完整回答。"""
    s = get_settings()
    payload = {
        "message": text,
        "thread_id": thread_id,
        "use_knowledge": True,
        "use_web": False,
    }
    answer_parts: list[str] = []
    error_msg = None
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", s.feishu_chat_url, json=payload) as resp:
                if resp.status_code != 200:
                    return f"（agent 返回错误 {resp.status_code}，请稍后重试或联系技术支持）"
                event = None
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data = line[len("data:"):].strip()
                        try:
                            obj = json.loads(data)
                        except Exception:
                            continue
                        if event == "token":
                            answer_parts.append(obj.get("text", ""))
                        elif event == "error":
                            error_msg = obj.get("message", "未知错误")
    except Exception as e:  # noqa: BLE001
        return f"（处理出错：{e}，请稍后重试或联系技术支持）"

    if error_msg:
        return f"（处理出错：{error_msg}，请稍后重试或联系技术支持）"
    answer = "".join(answer_parts).strip()

    # DEBUG: 打印原始答案，看是否包含警告
    print(f"[DEBUG 飞书] 原始答案长度: {len(answer)}")
    if "未经知识库检索" in answer:
        print(f"[DEBUG 飞书] ⚠️ 检测到警告文字！答案前100字: {answer[:100]}")

    # 强制过滤警告文字（防止 LLM 自己生成）
    answer = answer.replace("⚠️ 本回答未经知识库检索核实，可能存在不准确或与公司文档不符之处，请谨慎参考。", "")
    answer = answer.replace("\n\n\n", "\n\n").strip()

    return answer or "（未能生成回答，请换个问法或联系技术支持）"


async def _send_message(chat_id: str, text: str) -> bool:
    """调 i讯飞 IM API 发文本消息（httpx + 浏览器 UA 绕 WAF）。"""
    token = await _get_token()
    if not token:
        print("[i讯飞] 无 token，发消息中止")
        return False
    payload = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_XF_DOMAIN}/open-apis/im/v1/messages",
                params={"receive_id_type": "chat_id"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": _UA,
                },
                json=payload,
            )
        data = resp.json()
        if data.get("code") == 0:
            return True
        print(f"[i讯飞] 发消息失败: {data}")
    except Exception as e:  # noqa: BLE001
        print(f"[i讯飞] 发消息异常: {e}")
    return False


async def _handle_message(event: dict):
    """后台任务：解析消息 → 问 agent → 发回。"""
    try:
        msg = event.get("message", {})
        chat_id = msg.get("chat_id", "")
        text = _extract_text(msg)
        if not chat_id or not text:
            return  # 非文本消息或缺 chat_id，忽略

        # 用 chat_id 作为 thread_id（每个会话独立上下文）
        answer = await _ask_agent(text, thread_id=f"feishu-{chat_id}")
        await _send_message(chat_id, answer)
    except Exception as e:  # noqa: BLE001
        print(f"[i讯飞] 处理消息异常: {e}")


def _decrypt_if_needed(raw: dict) -> dict:
    """若配了 encrypt_key，事件体是 {'encrypt': '...'}，需解密成明文 dict。"""
    s = get_settings()
    if "encrypt" in raw and s.feishu_encrypt_key:
        cipher = lark.AESCipher(s.feishu_encrypt_key)
        plain = cipher.decrypt_str(raw["encrypt"])
        return json.loads(plain)
    return raw


@router.post("/feishu/event")
async def feishu_event(request: Request):
    """飞书事件订阅回调。立即 ACK + 后台异步处理，避免 3 秒超时。"""
    s = get_settings()
    if not s.feishu_enabled:
        return JSONResponse({"msg": "feishu disabled"}, status_code=403)

    raw = await request.json()
    body = _decrypt_if_needed(raw)

    # 1. URL 验证挑战：飞书配置回调地址时先发 challenge，原样返回
    if body.get("type") == "url_verification":
        return JSONResponse({"challenge": body.get("challenge", "")})

    # 2. 验签：校验 verification token（schema 2.0 在 header.token，1.0 在 token）
    token = (body.get("header") or {}).get("token") or body.get("token")
    if s.feishu_verification_token and token != s.feishu_verification_token:
        return JSONResponse({"msg": "invalid token"}, status_code=401)

    # 3. 事件去重（飞书会重试）
    event_id = (body.get("header") or {}).get("event_id") or body.get("uuid", "")
    if not _mark_seen(event_id):
        return JSONResponse({})  # 重复事件，直接 ACK 不处理

    # 4. 只处理接收消息事件
    header = body.get("header") or {}
    event_type = header.get("event_type") or body.get("event", {}).get("type", "")
    if event_type == "im.message.receive_v1":
        event = body.get("event", {})
        # 立即起后台任务，不等待处理完成
        asyncio.create_task(_handle_message(event))

    # 5. 立即 ACK（3 秒内返回）
    return JSONResponse({})
