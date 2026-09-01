# 部门产品智能客服机器人

基于大模型 + RAG 的智能客服系统，支持产品功能介绍、使用方法解答、问题排障等场景。

## 项目背景

讯飞 AI 工程院各部门均有自己的平台或 API 产品，业务方在使用过程中需要向技术支持咨询功能使用、参数配置、报错排障等问题。本系统通过知识库检索 + 大模型生成的方式，自动化处理常见问题，释放技术支持人力。

## 核心功能

- 📚 **知识库问答**：基于飞书文档、FAQ 等知识源，准确回答产品相关问题
- 🔍 **智能检索**：向量检索 + BM25 混合检索，确保高召回率
- 🤖 **多端部署**：Web 页面 + 飞书机器人，统一后端服务
- 💬 **流式输出**：SSE 实时返回，用户体验流畅
- 📝 **对话历史**：SQLite 持久化，支持上下文连续对话
- 🛠️ **工具调度**：Agent 自主决策调用 17 个工具（检索、读文档、文件操作等）

## 系统架构

```
用户端: Web页面 / 飞书机器人 / API接口
          ↓
FastAPI 后端 + LangGraph Agent (ReAct模式)
          ↓
17个工具: 知识库检索、文档读取、文件操作、拓扑分析...
          ↓
知识库层: ChromaDB (向量) + SQLite (文档内容)
          ↓
外部服务: Claude API (讯飞) + 飞书开放平台
```

### 技术选型

**方案：大模型 + RAG（检索增强生成）**

- ✅ **优点**：
  - 无需训练，快速部署
  - 支持增量更新，添加文档即生效
  - 回答可追溯来源，可信度高
  - 知识库易于维护和扩展

- ❌ **缺点**：
  - 依赖检索质量，检索不准会影响回答
  - 首次查询需建立向量索引（约 1-2 秒）
  - 单次查询响应时间 2-10 秒（检索 + LLM 推理）

**Agent 框架：LangGraph ReAct**
- 自主决策调用工具
- 支持复杂推理和多轮交互
- 可观测性强（每步工具调用都有日志）

**向量检索：bge-small-zh-v1.5 + ChromaDB**
- 混合检索：向量相似度 + BM25 关键词匹配
- 中文优化，召回率高

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 16+

### 1. 后端启动

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入必需配置：
# - ANTHROPIC_API_KEY（必填）
# - FEISHU_APP_ID / FEISHU_APP_SECRET（使用飞书机器人时必填）

# 启动服务
python main.py
```

后端默认运行在 `http://localhost:8123`

### 2. 前端启动

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端默认运行在 `http://localhost:5173`

### 3. 飞书机器人配置（可选）

1. 登录 [飞书开放平台](https://open.feishu.cn/)，创建企业自建应用
2. 配置事件订阅 URL：`http://your-domain/api/feishu/events`
3. 开启权限：
   - 接收群聊中 @机器人 消息
   - 获取与发送单聊、群组消息
4. 在 `backend/.env` 中填入：
   ```env
   FEISHU_APP_ID=cli_xxx
   FEISHU_APP_SECRET=xxx
   FEISHU_VERIFICATION_TOKEN=xxx
   ```
5. 将机器人拉入飞书群聊，@机器人 即可使用

## 知识库管理

### 添加文档

#### 方式 1：通过 API

```bash
# 抓取飞书文档
curl -X POST http://localhost:8123/api/knowledge/feishu \
  -H "Content-Type: application/json" \
  -d '{"url": "https://xxx.xfchat.iflytek.com/wiki/xxxxx"}'

# 上传本地文件
curl -X POST http://localhost:8123/api/knowledge/upload \
  -F "file=@document.pdf"
```

#### 方式 2：通过 Web 界面

访问前端页面 → 知识库管理 → 添加文档

### 文档格式支持

- ✅ 飞书 Wiki / Docx
- ✅ Markdown (.md)
- ✅ PDF (.pdf)
- ✅ 纯文本 (.txt)

### 查看已有文档

```bash
curl http://localhost:8123/api/knowledge/docs
```

## 评测与优化

### 运行评测

```bash
cd evaluation

# 安装依赖（如果还没装）
pip install httpx

# 执行自动评测（30个测试问题）
python run_evaluation.py

# 查看结果
cat evaluation_results.json
```

### 评测指标

- **关键词匹配率**：自动评估回答是否包含预期关键词
- **分类准确率**：功能介绍、使用方法、问题排障三类分别统计
- **人工标注**：对每个回答标注 good / ok / bad

### 测试问题分布

- **功能介绍类**：10 题
  - 产品定位、核心功能、应用场景
  - 示例："虚拟人是做什么的？"
  
- **使用方法类**：10 题
  - 接口调用、参数配置、操作步骤
  - 示例："start 接口怎么调用？"
  
- **问题排障类**：10 题
  - 错误码解释、异常处理、排障指引
  - 示例："错误码 10301 怎么处理？"

## 目录结构

```
.
├── backend/                 # 后端服务
│   ├── app/
│   │   ├── agent/          # Agent 逻辑
│   │   │   ├── graph.py    # LangGraph Agent
│   │   │   ├── prompts.py  # System Prompt
│   │   │   └── tools/      # 工具集（17个工具）
│   │   ├── api/            # API 路由
│   │   │   ├── chat.py     # 对话接口（SSE）
│   │   │   ├── feishu.py   # 飞书回调
│   │   │   └── knowledge.py # 知识库管理
│   │   ├── knowledge/      # 知识库处理
│   │   │   ├── feishu_doc.py # 飞书文档抓取
│   │   │   └── rag.py      # RAG 检索
│   │   └── store/          # 数据存储
│   │       ├── chat.db     # 对话历史
│   │       └── kb.db       # 知识库
│   ├── main.py             # 入口文件
│   ├── requirements.txt    # Python 依赖
│   └── .env.example        # 环境变量模板
├── frontend/               # 前端页面
│   ├── src/
│   │   ├── components/     # Vue 组件
│   │   ├── views/          # 页面视图
│   │   └── App.vue         # 主应用
│   └── package.json        # Node 依赖
├── evaluation/             # 评测相关
│   ├── test_questions.json # 30个测试问题
│   ├── run_evaluation.py   # 自动评测脚本
│   └── evaluation_results.json # 评测结果（运行后生成）
├── store/                  # 数据存储目录
│   ├── chat.db            # 对话历史数据库
│   ├── kb.db              # 知识库向量数据库
│   └── workspace/         # 工作区文件
└── README.md              # 本文档
```

## 环境变量配置

编辑 `backend/.env`：

```env
# Claude API (讯飞 AI 云平台) - 必填
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_BASE_URL=https://one.iflytek.com/api/llm/console/chat
ANTHROPIC_MODEL=claude-sonnet-4-6

# 飞书配置（使用飞书机器人时必填）
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=xxx

# 飞书文档抓取（使用飞书文档抓取功能时必填）
FEISHU_DOC_APP_ID=cli_xxx
FEISHU_DOC_APP_SECRET=xxx

# 服务配置
HOST=0.0.0.0
PORT=8123
```

## 技术栈

### 后端

- **Web 框架**：FastAPI 0.104+
- **Agent 框架**：LangGraph + LangChain
- **向量数据库**：ChromaDB
- **Embedding 模型**：bge-small-zh-v1.5 (本地)
- **LLM**：Claude Sonnet 4.6 (讯飞 AI 云平台)
- **数据库**：SQLite
- **异步 HTTP**：httpx

### 前端

- **框架**：Vue 3 + TypeScript
- **构建工具**：Vite
- **UI 库**：Element Plus
- **HTTP 客户端**：Axios

## 常见问题

### Q: 为什么回答慢？

A: 主要耗时在：
1. 向量检索（100-500ms）
2. LLM 推理（2-10秒，取决于模型）

**优化建议**：
- 使用更快的模型（Haiku 代替 Sonnet）
- 减少检索 Top-K 数量
- 启用 Prompt 缓存

### Q: 如何提升回答准确率？

A: 
1. **完善知识库**：补充常见问题、FAQ
2. **优化文档质量**：确保文档结构清晰、内容完整
3. **调整检索参数**：Top-K、相似度阈值
4. **改进 System Prompt**：已内置"检索优先铁律"

### Q: 飞书机器人收不到消息？

A: 检查清单：
1. 事件订阅 URL 是否配置正确且可访问
2. 后端日志是否有飞书回调记录
3. 机器人是否有接收消息和发送消息权限
4. 机器人是否被拉入群聊
5. `.env` 中的 `FEISHU_APP_ID` 等配置是否正确

### Q: 知识库为空怎么办？

A: 
1. 通过 API 抓取飞书文档：`POST /api/knowledge/feishu`
2. 或上传本地文件：`POST /api/knowledge/upload`
3. 查看已有文档：`GET /api/knowledge/docs`

### Q: Agent 不调用检索工具？

A: 
1. 检查 System Prompt 是否生效（已内置"检索优先铁律"）
2. 尝试使用更强的模型（Sonnet 代替 Haiku）
3. 查看后端日志确认工具调用情况

## 安全说明

- **无鉴权**：当前不带身份认证，仅适合内网开发测试
- **敏感信息**：API Key 等配置在 `.env` 中，已加入 `.gitignore`
- **文件沙箱**：工具操作限制在 `backend/store/workspace` 目录内
- **生产部署**：需自行添加认证、访问控制、日志审计等安全机制

## 作业相关

### 使用的 AI 编程工具

- **Claude Code**：全流程使用，从需求分析、架构设计、代码编写到调试优化
- **关键交互记录**：见完整对话历史（已保留开发全过程）

### 完成情况

- ✅ **产品调研**：虚拟人接口、星火 API、错误码体系等
- ✅ **知识库构建**：飞书文档抓取 + 结构化存储 + 向量索引
- ✅ **技术方案**：大模型 + RAG，支持增量更新
- ✅ **多端部署**：Web 页面 + 飞书机器人，统一后端
- ✅ **异常处理**：日志记录、错误提示、中断处理
- ✅ **评测体系**：30 条测试题 + 自动评测脚本
- ⏳ **优化迭代**：需运行评测后根据结果优化

### 三类问题覆盖

系统能回答：

1. **功能介绍类**
   - "虚拟人是做什么的？"
   - "虚拟人支持哪些驱动方式？"
   - "XRTC 协议有什么优势？"

2. **使用方法类**
   - "start 接口怎么调用？"
   - "如何配置 TTS 发音人？"
   - "text_driver 接口需要传哪些参数？"

3. **问题排障类**
   - "错误码 10301 是什么意思？"
   - "错误码 11200 怎么处理？"
   - "WebSocket 连接断开怎么办？"

### 演示录屏

（待补充：3-5 分钟系统演示视频链接）

## 开发者

- **开发工具**：Claude Code (AI 编程工具)
- **主要技术**：LangGraph + RAG + FastAPI + Vue 3
- **开发周期**：使用 AI 工具大幅提效，从 0 到可用约 2-3 天

## 许可证

本项目用于作业提交。
