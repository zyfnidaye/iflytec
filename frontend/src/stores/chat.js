import { defineStore } from 'pinia'
import {
  streamChat,
  fetchConversations,
  fetchConversationMessages,
  deleteConversation,
} from '../api/client.js'
import { useWorkspaceStore } from './workspace.js'

// 简单生成一个会话 id
function newThreadId() {
  return 'thread-' + Math.random().toString(36).slice(2, 10)
}

const DEFAULT_SPEED = 25 // 默认吐字速度（ms/字符），越小越快
const LS_KEY = 'code-agent:threadId'
const LS_SPEED = 'code-agent:typewriterSpeed'

// 记住上次的会话 id，刷新后接着用
function initialThreadId() {
  try {
    return localStorage.getItem(LS_KEY) || newThreadId()
  } catch {
    return newThreadId()
  }
}

function persistThreadId(id) {
  try {
    localStorage.setItem(LS_KEY, id)
  } catch {
    // localStorage 不可用则忽略
  }
}

// 旧预设(全体加速前) → 新预设的映射，保证存过旧值的用户也享受加速
const LEGACY_SPEED_MAP = { 100: 50, 50: 25, 20: 10, 5: 3 }

function loadSpeed() {
  try {
    const v = localStorage.getItem(LS_SPEED)
    if (!v) return DEFAULT_SPEED
    const n = Number(v)
    return LEGACY_SPEED_MAP[n] ?? n
  } catch {
    return DEFAULT_SPEED
  }
}

function persistSpeed(ms) {
  try {
    localStorage.setItem(LS_SPEED, ms)
  } catch {
    // 忽略
  }
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    threadId: initialThreadId(),
    messages: [], // { role: 'user'|'assistant', content, tools: [] }
    streaming: false,
    conversations: [], // { thread_id, title, created_at, updated_at }
    typewriterQueue: [], // 打字机任务队列
    typewriterRunning: false, // 是否有打字机任务正在运行
    typewriterSpeed: loadSpeed(), // 打字机速度（ms/字符），默认 50
    // Artifact 状态：当前正在生成的文档预览
    currentArtifact: null, // { id, title, type, content } 或 null
    abortController: null, // 当前请求的中断控制器（用于停止生成）
    cancelled: false, // 本轮是否已被用户主动停止（打字机循环据此立即刹车）
  }),
  getters: {
    // 当前会话标题（用于顶栏显示）
    currentTitle(state) {
      const c = state.conversations.find((x) => x.thread_id === state.threadId)
      return c ? c.title : ''
    },
  },
  actions: {
    // 处理打字机队列
    async processTypewriterQueue() {
      if (this.typewriterRunning || this.typewriterQueue.length === 0) return

      this.typewriterRunning = true
      while (this.typewriterQueue.length > 0) {
        // 已被用户停止：丢弃剩余队列，立即退出
        if (this.cancelled) {
          this.typewriterQueue = []
          break
        }
        const task = this.typewriterQueue.shift()
        await task() // 等待当前任务完成
      }
      this.typewriterRunning = false
    },

    // 拉取会话列表
    async loadList() {
      try {
        const data = await fetchConversations()
        this.conversations = data.conversations || []
      } catch {
        // 静默失败，不阻塞聊天
      }
    },
    // 加载某个历史会话到当前视图
    async loadConversation(threadId) {
      if (this.streaming) return
      const data = await fetchConversationMessages(threadId)
      this.threadId = threadId
      persistThreadId(threadId)
      this.messages = (data.messages || []).map((m) => ({
        role: m.role,
        content: m.content,
        // 历史工具调用统一标记为已完成
        tools: (m.tools || []).map((t) => ({ ...t, status: t.status || 'done' })),
      }))
    },
    // 新建空会话
    newConversation() {
      if (this.streaming) return
      this.threadId = newThreadId()
      persistThreadId(this.threadId)
      this.messages = []
    },
    // 删除会话；若删的是当前会话则新建一个
    async removeConversation(threadId) {
      await deleteConversation(threadId)
      if (threadId === this.threadId) this.newConversation()
      await this.loadList()
    },
    // 兼容旧调用
    reset() {
      this.newConversation()
    },
    setSpeed(ms) {
      this.typewriterSpeed = ms
      persistSpeed(ms)
    },
    async send(text, imageDataUrls = [], useKnowledge = true, forceRetrieval = false, useWeb = false) {
      if (this.streaming || !text.trim()) return

      // 清空打字机队列（开始新会话）
      this.typewriterQueue = []
      this.typewriterRunning = false
      this.tokenBuffer = ''  // 用于积攒 token，遇边界才 flush
      this.markdownBuffer = ''  // 用于暂存不完整的 Markdown 块（表格、代码块、列表）
      this.lastRenderedLength = 0  // 记录上次渲染的内容长度，用于增量渲染

      // 捕获当前速度设置，整个消息期间保持一致
      const speed = this.typewriterSpeed

      const isFirst = this.messages.length === 0
      this.messages.push({ role: 'user', content: text, tools: [] })
      // tools 元素带 status: 'running'|'done'|'error'，统一展示工具调用进度
      // thinking: 思考过程文本（预留方案A）
      // thinkingVisible: 是否显示思考过程
      this.messages.push({
        role: 'assistant',
        content: '',
        tools: [],
        sources: [],  // RAG 引用来源（retrieve_knowledge 命中的段落，跨轮累积去重）
        streaming: true,
        thinking: '',  // 预留：Extended Thinking 的思考内容
        thinkingVisible: false  // 是否显示思考区域
      })
      // 关键：从响应式数组取回代理引用，后续对它的修改才会触发逐 token 重渲。
      // 若直接用 push 前的普通对象修改，会绕过 Vue 代理，界面只在最后整段刷新。
      const assistant = this.messages[this.messages.length - 1]
      this.streaming = true
      this.cancelled = false
      this.abortController = new AbortController()
      console.log('[Chat] streaming started, streaming =', this.streaming, ', speed =', speed, 'ms/char')

      // 辅助函数：将积攒的 buffer flush 为一个打字机任务
      const flushBuffer = () => {
        if (!this.tokenBuffer) return
        const chunk = this.tokenBuffer
        this.tokenBuffer = ''

        this.typewriterQueue.push(() => {
          return new Promise((resolve) => {
            if (this.cancelled) return resolve()
            assistant.content += chunk
            // 停顿时间 = 固定延迟 + chunk 长度微调（成组输出应该很快）
            setTimeout(resolve, Math.max(5, chunk.length * speed * 0.1))
          })
        })
        this.processTypewriterQueue()
      }

      await streamChat(
        { message: text, threadId: this.threadId, imageDataUrls, useKnowledge, forceRetrieval, useWeb, signal: this.abortController.signal },
        {
          onToken: (t) => {
            console.log('[Token]', t.length, 'chars, streaming =', this.streaming, ', content length =', assistant.content.length)

            // 积攒到 buffer
            this.tokenBuffer += t

            // 边界检测：只在句尾标点、换行时才 flush（不包括空格）
            const sentenceBoundaries = /[。！？.!?\n]$/
            const isLongEnough = this.tokenBuffer.length > 20

            // 触发 flush 的条件：
            // 1. 命中句尾边界（最后一个字符是标点或换行）
            // 2. buffer 超过 20 字符且遇到空格（按词组输出）
            // 3. buffer 超过 50 字符（防止一句话太长不刷新）
            if (sentenceBoundaries.test(this.tokenBuffer) ||
                (isLongEnough && t.includes(' ')) ||
                this.tokenBuffer.length > 50) {
              flushBuffer()
            }
          },
          onTool: (tool) => {
            // 第一个工具调用时，显示"正在思考"状态
            if (assistant.tools.length === 0) {
              assistant.thinkingVisible = true
            }

            // 写文件类工具：同一文件多次操作合并到一行，复用已有条目
            if (['write_file', 'edit_file', 'append_file'].includes(tool.name)) {
              const path = tool.input?.path || ''
              const existing = assistant.tools.find(
                (x) => x.name === tool.name && x.input?.path === path
              )
              if (existing) {
                existing.id = tool.id
                existing.status = 'running'
                return
              }
            }
            assistant.tools.push({ ...tool, status: 'running' })
          },
          // 预留方案A：Extended Thinking 事件处理
          onThinkingStart: () => {
            assistant.thinkingVisible = true
            assistant.thinking = ''
          },
          onThinking: (text) => {
            assistant.thinking += text
          },
          onThinkingEnd: () => {
            // 思考结束，保留显示
          },
          onToolDone: (payload) => {
            const t = assistant.tools.find((x) => x.id === payload.id)
            if (t) t.status = payload.ok ? 'done' : 'error'
          },
          // 子助手内部工具调用：push 进同一 tools 列表，打 subagent 标记，
          // 前端据此缩进 + 加"↳ 子助手"前缀，复用现有工具卡渲染。
          onSubagentTool: (payload) => {
            if (assistant.tools.length === 0) assistant.thinkingVisible = true
            assistant.tools.push({ ...payload, status: 'running', subagent: true })
          },
          onSubagentToolDone: (payload) => {
            const t = assistant.tools.find((x) => x.id === payload.id)
            if (t) t.status = payload.ok ? 'done' : 'error'
          },
          onSubagentText: (payload) => {
            // 子助手的阶段性文本（多为告警），暂不单独渲染，打日志便于排查
            console.log('[Subagent]', payload.text)
          },
          onFileWritten: (payload) => {
            // 后端已把真实路径+内容推来：直接实时预览 + 刷新工作区文件树
            const ws = useWorkspaceStore()
            ws.showLivePreview(payload.name, payload.path, payload.content)
            ws.loadTree()
          },
          onArtifactUpdate: (payload) => {
            // 更新当前 artifact 状态，触发右侧预览面板更新
            this.currentArtifact = {
              id: payload.id,
              title: payload.title,
              type: payload.type,
              content: payload.content,
            }
            console.log('[Artifact] Updated:', payload.title, 'content length:', payload.content.length)
          },
          onWarning: (msg) => {
            // 第二层防护：未经知识库检索的回答，前端置顶显示免责提示
            assistant.content = `> ${msg}\n\n${assistant.content}`
          },
          onError: (msg) => {
            assistant.content += `\n\n> ⚠️ 出错：${msg}`
          },
          onInterrupted: () => {
            console.log('[Chat] interrupted')
            this._finishInterrupt(assistant)
          },
          onDone: () => {
            console.log('[Chat] streaming done')
            // 关键修复：流式结束时强制 flush 剩余的 buffer
            flushBuffer()
            this.streaming = false
            // 标记流式结束，触发完整渲染（带代码高亮）
            assistant.streaming = false
            // 写文件完成：标记悬浮小窗状态为"已完成"
            const ws = useWorkspaceStore()
            ws.markLivePreviewDone()
            // artifact 延迟清空
            setTimeout(() => {
              this.currentArtifact = null
            }, 2000)
          },
        }
      )
      this.streaming = false
      this.abortController = null
      console.log('[Chat] stream ended, streaming =', this.streaming)
      // 首条消息后会话才出现在库里；每轮结束刷新列表（更新标题/排序）
      if (isFirst) persistThreadId(this.threadId)
      await this.loadList()
    },

    /** 停止生成：立即刹车 + 中断请求。服务端检测到断开后会保存已生成的部分内容。 */
    stop() {
      if (!this.streaming) return
      console.log('[Chat] user requested stop')
      // 1. 先立起停止标志：正在跑的打字机循环下一步就会退出
      this.cancelled = true
      this.typewriterQueue = []
      this.typewriterRunning = false
      // 2. 中断网络请求（触发 AbortError → onInterrupted，服务端也会收到断开）
      if (this.abortController) {
        this.abortController.abort()
        this.abortController = null
      }
      // 3. 立即在当前显示的最后一条消息上标记（不等异步回调）
      const last = this.messages[this.messages.length - 1]
      if (last && last.role === 'assistant') this._finishInterrupt(last)
    },

    /** 中断收尾：停流、标记未跑完的工具、追加"已停止"提示（幂等，多次调用只标一次）。 */
    _finishInterrupt(assistant) {
      this.streaming = false
      this.cancelled = true
      this.typewriterQueue = []
      // 未完成的工具调用标记为已停止
      if (assistant?.tools) {
        assistant.tools.forEach((t) => {
          if (t.status === 'running') t.status = 'error'
        })
      }
      if (assistant && !assistant._interruptMarked) {
        assistant._interruptMarked = true
        assistant.content += assistant.content.trim()
          ? '\n\n_（已停止生成）_'
          : '_（已停止生成）_'
      }
      const ws = useWorkspaceStore()
      ws.markLivePreviewDone()
    },
  },
})
