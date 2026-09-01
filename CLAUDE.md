# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

公司内部「日常学习助手」智能体。后端 LangGraph + FastAPI 接 Claude（走公司 Anthropic 兼容网关），前端 Vue 3 + Vite。四大能力：理解服务链路图、在受控工作区读写代码、基于上传知识库检索回答（本地 RAG）、加载用户上传的 skill。

## Commands

后端依赖装在 `backend/.venv` 里（**不要装进全局**），所有 pip 都走清华源：

```bash
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

RAG 依赖（torch/sentence-transformers/chromadb）已在 requirements.txt 里，但 **torch 装清华源会是 CUDA 版、Windows 下缺 DLL**。若 `c10.dll` 加载失败，改装 CPU 版并确保系统有 VC++ Redistributable：
```bash
./.venv/Scripts/python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
# 缺运行库则装：https://aka.ms/vs/17/release/vc_redist.x64.exe
```
BGE embedding 模型首次需联网下载（~100MB，走 hf-mirror.com 镜像），之后强制离线只读本地缓存。

一键启停（项目根目录，PowerShell）：

```powershell
.\start.ps1 -Reload   # 前后端各开一个窗口，后端热重载
.\stop.ps1            # 按端口 8123 / 5173 关进程（含 --reload 派生的 worker）
```

单独跑：

```bash
# 后端（8123）—— 必须带 --reload-dir app，否则 .venv 变动会触发误重启
cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --reload-dir app --port 8123
# 前端（5173，/api 代理到 8123）
cd frontend && npm run dev
# 前端构建校验（无独立测试套件，用它当冒烟测试）
cd frontend && npx vite build
```

健康检查：`curl http://localhost:8123/api/health` → `api_key_set` 必须为 `true` 才能对话。

配置：复制 `backend/.env.example` 为 `backend/.env`，填 `ANTHROPIC_API_KEY` 与 `ANTHROPIC_BASE_URL`（公司网关地址）。`.env` 改动 `--reload` 不会重载（配置用 `lru_cache` 缓存在进程启动时），需手动重启。

## Architecture

### Agent 是无状态的，上下文靠 sqlite 回放
[graph.py](backend/app/agent/graph.py) 里的 `create_react_agent` **不挂 checkpointer**。每次 `/api/chat` 请求，[chat.py](backend/app/api/chat.py) 从 sqlite（[store/conversations.py](backend/app/store/conversations.py)）读出该 `thread_id` 的历史消息，连同新消息一起喂给 agent，流式结束后再把 user / assistant 消息落盘。**这意味着**：多轮上下文与「重启后仍能续聊」都由 sqlite 驱动，不是 LangGraph 内存态。历史只回放文本，不重放工具调用、不重放图片。

### LangGraph 版本锁定带来的 API 差异
装的是 `langgraph==0.2.62`。系统提示词参数是 `state_modifier`（新版才叫 `prompt`）——升级 langgraph 前不要改这里。注意 `state_modifier` 现在是 **callable**（不是静态字符串），用于每次请求动态注入 skill 列表。工具用 `@tool` 装饰，集中在 [agent/tools/](backend/app/agent/tools/)，在 graph.py 里 `WORKSPACE_TOOLS + TOPOLOGY_TOOLS + SKILL_TOOLS` 组装。

### SSE 流式协议
`/api/chat` 用 SSE，事件类型：`token`（逐字文本）、`tool`（工具调用名+参数）、`done`、`error`。前端 [api/client.js](frontend/src/api/client.js) 的 `streamChat` 手写解析这套协议；[stores/chat.js](frontend/src/stores/chat.js) 消费。错误也走 `error` 事件推给前端，避免前端干等。

### 文件沙箱是唯一安全边界
[agent/tools/workspace.py](backend/app/agent/tools/workspace.py) 的 `_resolve_safe()` 把所有文件读写限制在 `WORKSPACE_ROOT`（`backend/store/workspace`）内，拦截 `../`、盘符绝对路径（`C:\`）、UNC 路径。[api/workspace.py](backend/app/api/workspace.py) 复用同一边界。改动文件工具时务必保持这个防护。

### 链路图（拓扑）是进程内单例
[agent/tools/topology.py](backend/app/agent/tools/topology.py) 把上传的 JSON/YAML 解析成有向图存进进程内 `_GRAPH`（**非会话隔离，重启即失**）。`edges` 字段名兼容 `from/to`、`source/target`、`caller/callee`。工具：`topology_overview` / `get_dependencies` / `trace_chain`。

### 知识库 + RAG（本地免费 embedding，已接入对话）
摄入：[api/knowledge.py](backend/app/api/knowledge.py) + [knowledge/ingest.py](backend/app/knowledge/ingest.py) 解析文件（txt/md/csv/json/yaml 直读、html 剥标签、pdf→pypdf、docx→python-docx、xlsx→openpyxl）和抓网页 URL（httpx）。元数据存 [store/knowledge.py](backend/app/store/knowledge.py)（`kb.db`），解析正文存 `store/kb_text/<id>.txt`，原始文件按 `uploads/<类型>/<日期>/` 归档。

检索：RAG 已实现且接入对话。[rag/embeddings.py](backend/app/rag/embeddings.py) 用 **BGE-small-zh-v1.5**（本地、免费、512 维），[rag/vectorstore.py](backend/app/rag/vectorstore.py) 用 **Chroma**（持久化到 `store/chroma/`，collection 名 `knowledge_base`）。上传时 [rag/indexing.py](backend/app/rag/indexing.py) 自动分块（500 字/块、50 重叠）并索引；删除时同步清向量库。对话时若前端传 `use_knowledge=true`，[chat.py](backend/app/api/chat.py) 调 [rag/retrieval.py](backend/app/rag/retrieval.py) 检索 Top-K 片段，拼进 prompt 再喂 agent。

**embedding 强制离线**：`TRANSFORMERS_OFFLINE=1` / `HF_HUB_OFFLINE=1` 必须在 **import 任何 HF 库之前**设置（见 [main.py](backend/app/main.py) 顶部 + embeddings.py），否则库在导入时读不到、会联网校验并超时。模型缓存在 `~/.cache/huggingface/hub/`（首次需联网下载，走 `hf-mirror.com` 镜像）。torch 需 CPU 版 + 系统装 VC++ Redistributable，否则 `c10.dll` 加载失败。

### 向量库一致性守护
三层保护防止向量库与 `kb.db` 不一致：①上传/删除实时同步；②后台守护任务 [rag/guardian.py](backend/app/rag/guardian.py)（asyncio 循环，间隔 `vector_guard_interval` 秒，默认 1800，0 禁用，可用环境变量 `VECTOR_GUARD_INTERVAL` 覆盖；由 main.py 的 lifespan 启停）；③手动 `POST /api/knowledge/reindex`。同步逻辑集中在 [rag/sync.py](backend/app/rag/sync.py)（`sync_vectorstore()`，守护任务和 reindex 端点共用）：清孤儿向量 + 补缺失索引。

### Skills（Anthropic Agent Skills 标准）
用户可上传 skill（`SKILL.md` + YAML frontmatter `name`/`description` + 可选资源文件，zip 包或单文件），存 `store/skills/<skill>/`。[agent/skills/registry.py](backend/app/agent/skills/registry.py) 扫描/校验/读取。**渐进式披露**：[graph.py](backend/app/agent/graph.py) 的 `state_modifier` 是 **callable**（每次请求重建系统提示词，注入当前 skill 的 name+description），agent 判断相关后用 [agent/tools/skills.py](backend/app/agent/tools/skills.py) 的 `load_skill` 读完整指令、`read_skill_resource` 读附带文件。新上传的 skill 立即可见，无需重启。API 见 [api/skills.py](backend/app/api/skills.py)。

### 持久化数据都在 backend/store/（gitignore）
`workspace/`（沙箱）、`uploads/`（原始上传，按 类型/日期 归档）、`kb_text/`（解析正文）、`skills/`（上传的 skill）、`chroma/`（向量库）、`chat.db`（会话）、`kb.db`（知识库元数据）。两个自建 sqlite 存储层（conversations、knowledge）结构相同：模块级单连接 + 线程锁，`check_same_thread=False`。

### 前端布局
[App.vue](frontend/src/App.vue) 是 DeepSeek 风格左栏（会话列表 + 知识库 + 技能库 + 工作区），用 [DragHandle.vue](frontend/src/components/DragHandle.vue) 做可拖拽分隔条，尺寸存 localStorage。设计变量集中在 [style.css](frontend/src/style.css) 与 [styles/panels.css](frontend/src/styles/panels.css)。Pinia store 三个：`chat`（threadId 存 localStorage）、`knowledge`、`skills`。输入框可选当前 skill、开关知识库检索（`use_knowledge`）。

**流式渲染与打字机队列**：[stores/chat.js](frontend/src/stores/chat.js) 实现了**基于 Promise 队列的打字机效果**，解决 SSE token 并发到达时的乱码问题。

实现原理：
1. **状态管理**：`typewriterQueue: []`（任务队列）+ `typewriterRunning: false`（执行锁），防止多个处理循环并发。
2. **任务入队**：`onToken` 收到 SSE token 事件时，不直接操作 DOM，而是把打字机逻辑包装成**返回 Promise 的函数**（`() => new Promise(resolve => {...})`）push 进队列，然后调 `processTypewriterQueue()` 触发处理。
3. **串行执行**：`processTypewriterQueue()` 用 `while` 循环 `shift()` 队列首任务并 `await task()`，保证前一任务的 Promise `resolve()` 后才开始下一个。执行中 `typewriterRunning = true` 拦截重复触发。
4. **字符拆分**：任务内用 `Array.from(t)` 把 token 字符串转为**字符数组**（正确处理 UTF-8 多字节字符，避免 `t[i]` 切断中文），递归 `setTimeout(typewriter, 50)` 逐字追加到 `assistant.content`（50ms/字符 = 20 字/秒）。最后一个字符写完后调 `resolve()` 释放队列。
5. **Vue 响应式要点**：token 必须追加到从 `this.messages` 取回的**代理对象**上（`const assistant = this.messages.find(...); assistant.content += ...`），直接改 push 前缓存的原始对象不会触发更新。
6. **渲染优化**：[ChatPanel.vue](frontend/src/components/ChatPanel.vue) 判断 `chat.streaming` 时对最后一条消息用 `<div style="white-space: pre-wrap;">{{ m.content }}</div>` 显示纯文本，流式结束后才走 `v-html="render(m.content)"` 做 markdown 解析，避免每个字符触发一次重排版。

这套机制把「高频并发的网络事件」转换为「有序串行的 UI 动画」，彻底杜绝了多个 `setTimeout` 链交叉执行导致的字符乱序（表现为中文乱码或字符跳跃）。

## Environment gotchas (Windows)

- **PowerShell 5.1 + GBK 代码页（936）**：带中文的 `.ps1` 必须存 **UTF-8 BOM**，否则解析报假语法错。用 Edit 改过 `.ps1` 后需重新补 BOM。
- **`--reload` 的孤儿进程**：uvicorn `--reload` 用 multiprocessing 派生 worker，真正占端口的是子进程，而 Windows 按端口查到的 `OwningProcess` 常是已退出的父 PID。多个孤儿可因 SO_REUSEADDR 同时绑 8123，导致请求被分到旧代码。`stop.ps1` 已处理（追杀 `parent_pid=` 的 spawn worker）；手动清理时留意。
- **git-bash 的 `/tmp` ≠ venv python 的 `/tmp`**：venv python 是 Windows exe，不认 git-bash 的 `/tmp`。跨 bash 与 python 共享临时文件时用项目内相对路径。
- Node 装在 `D:\Dev\Nodejs`；npm 国内源 `https://registry.npmmirror.com`。

## Security posture

后端 API **无鉴权**，仅限本地/内网开发。若要暴露到公司网络必须自行加认证。文件写入仅限沙箱目录。
