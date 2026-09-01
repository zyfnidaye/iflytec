"""飞书云文档拉取器 —— 从 i讯飞平台(xfchat)拉取 wiki 文档入知识库。

设计：
- 复用 feishu.py 的 _get_token() 拿 tenant_access_token（async 函数）
- 支持输入完整 URL 或纯 node_token
- wiki 类型：仅支持 docx 类型文档（sheet/bitable 暂不支持）
- docx 类型：通过导出 PDF 再解析（绕过 blocks API 限制）
- 返回 (title, content) 二元组，供 knowledge.py 的入库管线消费
- 导航页递归：文档正文里嵌入的 wiki 超链接会被递归拉取一层，
  子文档正文合并进主文档，最终合成一篇入库（见 fetch_feishu_doc_async）。
"""
import asyncio
import re
from urllib.parse import urlparse, unquote

import httpx

# i讯飞开放平台域名（飞书兼容 API）
XF_BASE = "https://open.xfchat.iflytek.com"
# 所有请求必须带浏览器 UA（WAF 拦无 UA 的请求）
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


async def fetch_feishu_doc_async(url_or_token: str, timeout: int = 20) -> tuple[str, str]:
    """拉取飞书文档并递归合并子文档（支持 wiki 和普通 docx）—— async 版本。

    导航页处理：主文档正文里嵌入的 wiki 超链接（如"产品文档地址"表格里的链接）
    会被递归拉取一层，每个子文档的正文追加到主文档末尾，最终合成一篇。
    这样导航页 + 所有被链接的子文档内容都在同一篇里，可整体检索。

    Args:
        url_or_token: 完整 wiki/docx URL 或 token
        timeout: 每步 HTTP 请求的超时秒数

    Returns:
        (title, content): 主文档标题 + 合并后的 markdown 正文（含子文档）

    Raises:
        ValueError: 权限不足 / 文档类型不支持 / 解析失败
        httpx.HTTPError: 网络请求失败
    """
    # 1) 判断文档类型并提取 token
    doc_type, doc_token = _parse_feishu_url(url_or_token)
    if not doc_token:
        raise ValueError(f"无法解析文档 token: {url_or_token!r}")

    print(f"[飞书抓取] 类型={doc_type}, doc_token={doc_token}")

    # 2) 拿 tenant_access_token（复用 feishu.py 的 async 函数）
    from app.api.feishu import _get_token
    access_token = await _get_token()
    if not access_token:
        raise ValueError("无法获取 tenant_access_token，检查飞书应用凭证配置")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {access_token}",
    }

    # 3) 根据文档类型拉取主文档
    async with httpx.AsyncClient() as client:
        if doc_type == "wiki":
            # wiki 类型：需要先调 get_node 获取 obj_token，然后递归子链接
            title, blocks = await _fetch_wiki_doc(client, doc_token, headers, timeout)
            content = _blocks_to_markdown(blocks)
            if not content.strip():
                raise ValueError(f"文档《{title}》正文为空或解析失败")

            # 递归一层：提取主文档里嵌入的 wiki 子链接，逐个拉取并合并
            child_tokens = _extract_wiki_links(blocks)
            # 去重 + 排除指向自己的链接
            seen = {doc_token}
            merged_parts = [content]
            ok_count = fail_count = 0
            for i, ct in enumerate(child_tokens, 1):
                if ct in seen:
                    continue
                seen.add(ct)
                try:
                    c_title, c_blocks = await _fetch_wiki_doc(client, ct, headers, timeout)
                    c_content = _blocks_to_markdown(c_blocks)
                    if c_content.strip():
                        # 用一级标题包裹子文档，保留归属层级
                        merged_parts.append(f"\n\n# {c_title}\n\n{c_content}")
                        ok_count += 1
                        print(f"[飞书文档] ({i}/{len(child_tokens)}) ok  {ct} 《{c_title}》 {len(c_content)}字")
                except Exception as e:  # noqa: BLE001
                    # 单个子文档失败不影响整体（可能是表格/多维表等非 docx 类型）
                    fail_count += 1
                    print(f"[飞书文档] ({i}/{len(child_tokens)}) skip {ct}: {e}")

            print(f"[飞书文档] 递归完成: {ok_count} 篇成功 / {fail_count} 篇跳过 / 共 {len(child_tokens)} 个链接")
            return title, "\n\n".join(merged_parts)
        else:
            # docx 类型：直接拉取 blocks → 转 markdown，不递归
            title, blocks = await _fetch_docx_doc(client, doc_token, headers, timeout)
            content = _blocks_to_markdown(blocks)
            if not content.strip():
                raise ValueError(f"文档《{title}》正文为空或解析失败")
            return title, content


async def _fetch_wiki_doc(
    client: httpx.AsyncClient, node_token: str, headers: dict, timeout: int
) -> tuple[str, list[dict]]:
    """拉取 wiki 文档，返回 (标题, blocks 列表)。

    需要先调 get_node 获取 obj_token，再拉 blocks。

    Raises:
        ValueError: 节点解析失败 / 非 docx 类型 / blocks 读取失败
    """
    # 解析 wiki 节点 → 真实文档 obj_token + 类型
    r = await client.get(
        f"{XF_BASE}/open-apis/wiki/v2/spaces/get_node",
        headers=headers,
        params={"token": node_token},
        timeout=timeout,
    )
    data = r.json()
    if data.get("code") != 0:
        msg = data.get("msg", "unknown")
        raise ValueError(f"get_node 失败 (code={data.get('code')}): {msg}")

    node = (data.get("data") or {}).get("node") or {}
    obj_token = node.get("obj_token")
    obj_type = node.get("obj_type")
    title = node.get("title") or "未命名文档"

    if not obj_token:
        raise ValueError("未获取到 obj_token，文档可能不存在或应用无权限访问")
    if obj_type != "docx":
        raise ValueError(
            f"暂不支持 {obj_type} 类型文档，目前只支持 docx（飞书文档）。"
        )

    # 分页拉全所有块（page_size 上限 500）
    blocks: list[dict] = []
    page_token = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        r = await client.get(
            f"{XF_BASE}/open-apis/docx/v1/documents/{obj_token}/blocks",
            headers=headers,
            params=params,
            timeout=timeout,
        )
        data = r.json()
        if data.get("code") != 0:
            msg = data.get("msg", "unknown")
            raise ValueError(f"blocks 读取失败 (code={data.get('code')}): {msg}")
        d = data.get("data") or {}
        blocks.extend(d.get("items") or [])
        if d.get("has_more") and d.get("page_token"):
            page_token = d["page_token"]
        else:
            break

    return title, blocks


async def _fetch_docx_doc(
    client: httpx.AsyncClient, doc_token: str, headers: dict, timeout: int
) -> tuple[str, list[dict]]:
    """拉取普通 docx 文档，返回 (标题, blocks 列表)。

    直接用 doc_token 拉取 blocks（不走导出 PDF）。

    Raises:
        ValueError: blocks 读取失败
    """
    print(f"[飞书抓取] 直接拉取 docx blocks: {doc_token}")

    # 分页拉全所有块（page_size 上限 500）
    blocks: list[dict] = []
    page_token = None
    title = "未命名文档"

    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token

        url = f"{XF_BASE}/open-apis/docx/v1/documents/{doc_token}/blocks"
        r = await client.get(url, headers=headers, params=params, timeout=timeout)
        data = r.json()

        if data.get("code") != 0:
            msg = data.get("msg", "unknown")
            raise ValueError(f"blocks 读取失败 (code={data.get('code')}): {msg}")

        d = data.get("data") or {}
        items = d.get("items") or []
        blocks.extend(items)

        # 尝试从第一页的第一个 block 提取标题
        if not page_token and items:
            first_block = items[0]
            if first_block.get("block_type") == 1:  # page 块
                page_data = first_block.get("page") or {}
                if page_data.get("elements"):
                    title_text = []
                    for elem in page_data["elements"]:
                        if elem.get("text_run"):
                            title_text.append(elem["text_run"].get("content", ""))
                    if title_text:
                        title = "".join(title_text).strip()

        if d.get("has_more") and d.get("page_token"):
            page_token = d["page_token"]
        else:
            break

    return title, blocks


def _extract_wiki_links(blocks: list[dict]) -> list[str]:
    """从 blocks 里提取所有嵌入的 wiki 超链接，返回去重后的 node_token 列表（保序）。

    飞书文档里指向其他 wiki 文档的链接有两种结构，都要处理：
    1. text_run.text_element_style.link.url —— 普通超链接，值 percent-encoded
       （如 https%3A%2F%2F...%2Fwiki%2FI14Kw...），解码后取 /wiki/ 后一段。
    2. mention_doc —— 飞书「文档提及」，明文 url + 直接可用的 token 字段。
       导航页表格里的「产品文档地址」大多是这种。
    只收 /wiki/ 链接，忽略外部普通网址。
    """
    tokens: list[str] = []
    seen: set[str] = set()

    def _add(tok: str):
        if tok and tok not in seen:
            seen.add(tok)
            tokens.append(tok)

    for block in blocks:
        # 遍历 block 里所有可能带 elements 的字段（heading/text/table_cell 等）
        for field_val in block.values():
            if not isinstance(field_val, dict):
                continue
            elements = field_val.get("elements")
            if not isinstance(elements, list):
                continue
            for elem in elements:
                # 结构 1：普通超链接
                link = (elem.get("text_run") or {}).get("text_element_style", {}).get("link")
                if link and link.get("url"):
                    url = unquote(link["url"])
                    if "/wiki/" in url:
                        _add(_extract_node_token(url))

                # 结构 2：文档提及（mention_doc）—— 优先用明文 token，兜底解析 url
                mention = elem.get("mention_doc")
                if mention:
                    m_url = mention.get("url", "")
                    if "/wiki/" in m_url:
                        _add(mention.get("token") or _extract_node_token(m_url))

    return tokens


def _blocks_to_markdown(blocks: list[dict]) -> str:
    """将飞书 blocks 转成带层级标题的 markdown。

    飞书 block_type 映射（常见的）：
    - 1: page（文档根，忽略）
    - 2: text（正文段落）
    - 3-11: heading1-9（标题，转成 # ~ #########）
    - 12: bullet（无序列表）
    - 13: ordered（有序列表）
    - 14: code（代码块，讯飞平台）
    - 31/32: table / table_cell（表格，拍平成文本行）
    - 其余：未知类型，提取 text 元素作为纯文本
    """
    lines = []
    for block in blocks:
        bt = block.get("block_type")
        if bt == 1:  # page 根节点，跳过
            continue

        # 代码块特殊处理（讯飞平台的代码块类型是 14）
        if bt == 14:  # code block
            code_obj = block.get("code") or {}
            code_content = ""
            # 代码块的文本在 elements 里
            elements = code_obj.get("elements") or []
            for elem in elements:
                if elem.get("text_run"):
                    code_content += elem["text_run"].get("content", "")

            if code_content.strip():
                lines.append("```")
                lines.append(code_content.rstrip())
                lines.append("```")
            continue

        # 提取文本内容（飞书的 text 元素结构：{"elements": [{"text_run": {"content": "..."}}]}）
        text = _extract_text_from_block(block, bt)
        if not text.strip():
            continue

        # 按类型转换
        if 3 <= bt <= 11:  # heading1-9
            level = bt - 2  # heading1=3 -> #, heading2=4 -> ##, ...
            lines.append(f"{'#' * level} {text}")
        elif bt == 2:  # 正文
            lines.append(text)
        elif bt == 12:  # bullet 无序列表
            lines.append(f"- {text}")
        elif bt == 13:  # ordered 有序列表
            lines.append(f"1. {text}")
        elif bt in (31, 32):  # table / table_cell
            lines.append(text)  # 表格拍平成文本行
        else:
            # 未知类型，提取文本保底
            lines.append(text)

    return "\n\n".join(lines)


def _extract_text_from_block(block: dict, block_type: int) -> str:
    """从 block 里提取纯文本内容。

    飞书 block 的文本可能在：block["heading1"], block["text"], block["bullet"], block["ordered"] 等
    字段，每个字段都是 {"elements": [{"text_run": {"content": "..."}}, ...]} 结构。
    """
    # 常见文本字段名（按 block_type 推测优先字段）
    if 3 <= block_type <= 11:
        # heading1-9
        field = f"heading{block_type - 2}"
    elif block_type == 2:
        field = "text"
    elif block_type == 12:
        field = "bullet"  # 无序列表
    elif block_type == 13:
        field = "ordered"  # 有序列表
    elif block_type == 32:
        field = "table_cell"
    else:
        field = "text"  # 兜底

    content_obj = block.get(field)
    if not content_obj:
        # 兜底：遍历可能的字段
        for f in ("text", "bullet", "ordered", "heading1", "heading2", "heading3", "heading4", "table_cell"):
            if f in block and block[f]:
                content_obj = block[f]
                break

    if not content_obj:
        return ""

    # 提取 elements 里所有 text_run 的 content，拼接
    elements = content_obj.get("elements") or []
    parts = []
    for elem in elements:
        if "text_run" in elem:
            parts.append(elem["text_run"].get("content", ""))
    return "".join(parts)


def _extract_node_token(url_or_token: str) -> str:
    """从完整 URL 或纯 token 中提取 node_token。

    支持：
    - https://yf2ljykclb.xfchat.iflytek.com/wiki/PKAmwQtmvikRkXkZqeJrJDw1zVw
    - PKAmwQtmvikRkXkZqeJrJDw1zVw

    Returns:
        node_token（URL 最后一段，通常是字母数字组合）
    """
    s = url_or_token.strip()
    if not s:
        return ""

    # 先试按 URL 解析
    if s.startswith("http://") or s.startswith("https://"):
        parsed = urlparse(s)
        # path 通常是 /wiki/{node_token}，取最后一段
        parts = [p for p in parsed.path.split("/") if p]
        if parts and parts[0] == "wiki" and len(parts) >= 2:
            return parts[-1]
        # 兜底：path 最后非空段
        if parts:
            return parts[-1]
        return ""

    # 不是 URL → 当作纯 token（去掉可能的查询参数/锚点）
    token = s.split("?")[0].split("#")[0].strip()
    return token


def _parse_feishu_url(url_or_token: str) -> tuple[str, str]:
    """解析飞书文档 URL，返回 (文档类型, token)。

    支持：
    - https://xxx.xfchat.iflytek.com/wiki/xxxxx  → ("wiki", "xxxxx")
    - https://xxx.xfchat.iflytek.com/docx/xxxxx  → ("docx", "xxxxx")
    - https://xxx.xfchat.iflytek.com/docs/xxxxx  → ("docx", "xxxxx")
    - 纯 token → ("wiki", "xxxxx") 兜底当作 wiki

    Returns:
        (doc_type, token): 文档类型（"wiki"或"docx"）和 token
    """
    s = url_or_token.strip()
    if not s:
        return "", ""

    # URL 格式
    if s.startswith("http://") or s.startswith("https://"):
        parsed = urlparse(s)
        parts = [p for p in parsed.path.split("/") if p]

        if len(parts) >= 2:
            path_type = parts[0]
            token = parts[-1]  # 取最后一段作为 token

            if path_type == "wiki":
                return "wiki", token
            elif path_type in ("docx", "docs", "doc"):
                return "docx", token

        # 兜底：有路径就取最后段，默认 wiki
        if parts:
            return "wiki", parts[-1]
        return "", ""

    # 纯 token，默认当作 wiki
    token = s.split("?")[0].split("#")[0].strip()
    return "wiki", token

