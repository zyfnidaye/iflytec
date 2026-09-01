"""服务链路图（拓扑）工具。

支持解析用户上传的结构化拓扑文件（JSON / YAML），构建有向图，
并为智能体提供查询能力：某服务的上游/下游、依赖链、影响面等。

约定的拓扑文件格式（灵活容错，字段名尽量兼容常见写法）:

    {
      "services": [
        {"name": "order-api", "desc": "订单服务", "type": "http"},
        ...
      ],
      "edges": [
        {"from": "order-api", "to": "mysql-order", "protocol": "jdbc"},
        ...
      ]
    }

也兼容 edges 用 "source"/"target"、"caller"/"callee" 等命名。
"""
import json
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import tool

# 当前加载的拓扑（进程内单例；多会话隔离可后续按 thread_id 拆分）
_GRAPH: dict[str, Any] = {"services": {}, "out": {}, "in": {}, "edges": []}


def _edge_ends(edge: dict) -> tuple[str | None, str | None]:
    src = edge.get("from") or edge.get("source") or edge.get("caller") or edge.get("src")
    dst = edge.get("to") or edge.get("target") or edge.get("callee") or edge.get("dst")
    return src, dst


def load_topology_from_file(file_path: str) -> str:
    """从磁盘上的 JSON/YAML 文件加载拓扑到进程内。返回加载摘要。"""
    p = Path(file_path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    return _ingest(raw)


def _ingest(raw: dict) -> str:
    services: dict[str, dict] = {}
    for svc in raw.get("services", []):
        if isinstance(svc, str):
            services[svc] = {"name": svc}
        else:
            name = svc.get("name") or svc.get("id")
            if name:
                services[name] = svc

    out: dict[str, list] = {}
    inn: dict[str, list] = {}
    edges = []
    for edge in raw.get("edges", []) or raw.get("links", []) or raw.get("dependencies", []):
        src, dst = _edge_ends(edge)
        if not src or not dst:
            continue
        edges.append({"from": src, "to": dst, **{k: v for k, v in edge.items()}})
        out.setdefault(src, []).append(dst)
        inn.setdefault(dst, []).append(src)
        # 边里出现但未在 services 声明的节点也补进去
        services.setdefault(src, {"name": src})
        services.setdefault(dst, {"name": dst})

    _GRAPH["services"] = services
    _GRAPH["out"] = out
    _GRAPH["in"] = inn
    _GRAPH["edges"] = edges
    return f"已加载拓扑：{len(services)} 个服务，{len(edges)} 条依赖边。"


@tool
def topology_overview() -> str:
    """获取当前已加载服务链路图的总览：服务数量、依赖边数量、服务清单。"""
    services = _GRAPH["services"]
    if not services:
        return "当前没有已加载的链路图。请先让用户上传拓扑文件（JSON/YAML）。"
    lines = [f"共 {len(services)} 个服务，{len(_GRAPH['edges'])} 条依赖边。\n服务清单："]
    for name, meta in sorted(services.items()):
        desc = meta.get("desc") or meta.get("description") or ""
        lines.append(f"  - {name}{('：' + desc) if desc else ''}")
    return "\n".join(lines)


@tool
def get_dependencies(service: str, direction: str = "downstream") -> str:
    """查询某个服务的直接依赖关系。

    Args:
        service: 服务名。
        direction: "downstream" 查它调用的下游；"upstream" 查调用它的上游。
    """
    services = _GRAPH["services"]
    if service not in services:
        avail = ", ".join(sorted(services)) or "（空）"
        return f"未找到服务 '{service}'。可用服务：{avail}"
    if direction == "upstream":
        neighbors = _GRAPH["in"].get(service, [])
        label = "上游（调用方）"
    else:
        neighbors = _GRAPH["out"].get(service, [])
        label = "下游（被调用方）"
    if not neighbors:
        return f"服务 '{service}' 没有{label}。"
    return f"服务 '{service}' 的{label}：\n" + "\n".join(f"  -> {n}" for n in neighbors)


def _traverse(service: str, adj_key: str, max_depth: int) -> list[list[str]]:
    """从 service 出发按 adj_key 方向做路径遍历，返回所有链路（防环）。"""
    adj = _GRAPH[adj_key]
    paths: list[list[str]] = []

    def dfs(node: str, path: list[str], depth: int):
        nexts = adj.get(node, [])
        if depth >= max_depth or not nexts:
            paths.append(path)
            return
        for nxt in nexts:
            if nxt in path:  # 防环
                paths.append(path + [f"{nxt}(环)"])
                continue
            dfs(nxt, path + [nxt], depth + 1)

    dfs(service, [service], 0)
    return paths


@tool
def trace_chain(service: str, direction: str = "downstream", max_depth: int = 6) -> str:
    """追踪某服务的完整调用链路（递归展开上游或下游）。

    Args:
        service: 起点服务名。
        direction: "downstream" 展开下游依赖链；"upstream" 展开上游影响面。
        max_depth: 最大展开深度，默认 6。
    """
    if service not in _GRAPH["services"]:
        avail = ", ".join(sorted(_GRAPH["services"])) or "（空）"
        return f"未找到服务 '{service}'。可用服务：{avail}"
    adj_key = "in" if direction == "upstream" else "out"
    label = "上游影响面" if direction == "upstream" else "下游依赖链"
    paths = _traverse(service, adj_key, max_depth)
    lines = [f"'{service}' 的{label}（共 {len(paths)} 条链路）："]
    for path in paths:
        arrow = " <- " if direction == "upstream" else " -> "
        lines.append("  " + arrow.join(path))
    return "\n".join(lines)


TOPOLOGY_TOOLS = [topology_overview, get_dependencies, trace_chain]
