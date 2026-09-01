<script setup>
import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { marked } from 'marked'
import hljs from 'highlight.js'
// 不用预设主题，用自定义 VSCode Dark+ 配色
import { useChatStore } from '../stores/chat.js'
import { useSkillsStore } from '../stores/skills.js'
import { fetchKnowledgeDoc } from '../api/client.js'
import ArtifactPanel from './ArtifactPanel.vue'

const chat = useChatStore()
const skills = useSkillsStore()
const input = ref('')
const pendingImages = ref([]) // data urls
const scroller = ref(null)

// 工具调用折叠状态：key = 消息索引
const toolsExpanded = ref({})

// 引用出处弹窗状态
const citation = ref(null)      // { name, text } | null
const citationLoading = ref(false)

// 来源卡片：单个 snippet 的展开状态，key = `${消息索引}:${来源索引}`
// toggleSource / openSource / relevancePct 定义在 closeCitation 之后
const sourceExpanded = ref({})

// 当前选中的 skill 和知识库开关
const selectedSkills = ref([]) // 数组，支持多选
const useKnowledge = ref(true)
// 强制首轮检索开关：从 localStorage 读取，默认 true（保持防幻觉行为）。
// 关闭后简单问题让模型自主判断是否检索，响应更快。
const forceRetrieval = ref(localStorage.getItem('forceRetrieval') === 'true')
// 联网搜索开关：从 localStorage 读取，默认 false
const useWeb = ref(localStorage.getItem('useWeb') === 'true')
const showSkillMenu = ref(false)

// marked 14.x 已移除 highlight 选项，改用自定义 renderer 在解析时直接高亮。
// 这样流式和结束态都实时带 VSCode 高亮，无需事后 DOM 操作。
const _mdRenderer = new marked.Renderer()
_mdRenderer.code = ({ text, lang }) => {
  let highlighted
  try {
    if (lang && hljs.getLanguage(lang)) {
      highlighted = hljs.highlight(text, { language: lang }).value
    } else {
      highlighted = hljs.highlightAuto(text).value
    }
  } catch {
    // 高亮失败则退回转义纯文本
    highlighted = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  }
  const langClass = lang ? ` language-${lang}` : ''
  return `<pre><code class="hljs${langClass}">${highlighted}</code></pre>`
}
marked.setOptions({ renderer: _mdRenderer })

// 把回答里的引用标注渲染为可点击的引用芯片
// 新格式：《文档名》[doc_id:数字] → 显示文档名，点击用 doc_id
function renderCitations(html) {
  return html.replace(/《([^》]+)》\[doc_id:(\d+)\]/g, (_m, name, id) => {
    return `<sup class="cite" data-doc-id="${id}" title="点击查看《${name}》">《${name}》</sup>`
  })
}

// 渲染 markdown：marked 已配置 highlight（见上方 setOptions），
// 流式和结束都走同一套解析，代码块实时带 VSCode 高亮。
// 复制按钮由 highlightCodeBlocks() 在渲染稳定后单独添加。
function render(md, streaming = false) {
  if (!md) return ''
  return renderCitations(marked.parse(md))
}

// 事件委托：点击引用芯片 → 拉取该文档原文并弹窗
async function onBubbleClick(e) {
  const el = e.target.closest?.('.cite')
  if (!el) return
  const id = el.getAttribute('data-doc-id')
  if (!id) return
  citationLoading.value = true
  citation.value = { name: `doc_id=${id}`, text: '' }
  try {
    const doc = await fetchKnowledgeDoc(id)
    citation.value = { name: doc.name || `doc_id=${id}`, text: doc.text || '（无正文）' }
  } catch (err) {
    citation.value = { name: `doc_id=${id}`, text: '加载出处失败：' + err.message }
  } finally {
    citationLoading.value = false
  }
}

function closeCitation() {
  citation.value = null
}

// 来源卡片：展开/收起长片段
function toggleSource(key) {
  sourceExpanded.value[key] = !sourceExpanded.value[key]
}

// 点击来源卡片头部：直接展示该段落原文（无需再拉整篇）
function openSource(s) {
  const title = s.section_title ? `${s.section_title}（doc_id=${s.doc_id}）` : `doc_id=${s.doc_id}`
  citation.value = { name: title, text: s.snippet || '（无片段内容）' }
  citationLoading.value = false
}

// 余弦距离 [0,2] → 相关度百分比（距离越小越相关）。无 distance 时返回 null 不展示。
function relevancePct(distance) {
  if (distance == null || typeof distance !== 'number') return null
  const pct = Math.round((1 - distance / 2) * 100)
  return Math.max(0, Math.min(100, pct))
}

// 工具元信息：图标 + 动作动词（学 Claude Code：动词 + 目标参数）
const TOOL_META = {
  list_files:        { icon: '📂', action: '浏览' },
  read_file:         { icon: '📖', action: '读取' },
  write_file:        { icon: '✏️', action: '写入' },
  append_file:       { icon: '✏️', action: '追加' },
  edit_file:         { icon: '🔧', action: '编辑' },
  retrieve_knowledge:{ icon: '🔍', action: '检索知识库' },
  grep_knowledge:    { icon: '🔎', action: '精确检索' },
  read_document:     { icon: '📄', action: '读文档' },
  list_knowledge_docs:{ icon: '📚', action: '列出文档' },
  read_skill_resource:{ icon: '📎', action: '读技能资源' },
  load_skill:        { icon: '🧩', action: '加载技能' },
  web_search:        { icon: '🌐', action: '联网搜索' },
  topology_overview: { icon: '🗺️', action: '链路总览' },
  get_dependencies:  { icon: '🔗', action: '查询依赖' },
  trace_chain:       { icon: '🧭', action: '追踪调用链' },
  dispatch_agent:    { icon: '🤝', action: '委托子助手' },
  run_inline_agent:  { icon: '🤝', action: '临时子助手' },
}
const toolMeta = (name) => TOOL_META[name] || { icon: '🛠️', action: name }

// 从工具入参提取「目标」——像 Claude Code 那样显示操作对象
const toolTarget = (tool) => {
  const i = tool.input || {}
  return i.path || i.query || i.subdir || i.node || i.service || i.file || ''
}

async function submit() {
  let text = input.value
  const imgs = pendingImages.value.slice()

  // 如果选择了 skill，在消息前加上提示
  if (selectedSkills.value.length > 0) {
    text = `[使用技能: ${selectedSkills.value.join(', ')}]\n\n${text}`
  }

  input.value = ''
  pendingImages.value = []
  await chat.send(text, imgs, useKnowledge.value, forceRetrieval.value, useWeb.value)
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}

function toggleSkillMenu() {
  showSkillMenu.value = !showSkillMenu.value
  if (showSkillMenu.value) {
    skills.loadList()
  }
}

function selectSkill(name) {
  const index = selectedSkills.value.indexOf(name)
  if (index > -1) {
    // 已选中，取消选择
    selectedSkills.value.splice(index, 1)
  } else {
    // 未选中，添加到选择列表
    selectedSkills.value.push(name)
  }
  // 不关闭菜单，允许继续选择
}

function toggleKnowledge() {
  useKnowledge.value = !useKnowledge.value
}

function toggleForce() {
  forceRetrieval.value = !forceRetrieval.value
  localStorage.setItem('forceRetrieval', forceRetrieval.value)
}

function toggleWeb() {
  useWeb.value = !useWeb.value
  localStorage.setItem('useWeb', useWeb.value)
}

// 切换工具调用展开/折叠
function toggleTools(messageIndex) {
  toolsExpanded.value[messageIndex] = !toolsExpanded.value[messageIndex]
}

// 统计工具调用摘要（带动态计数）
function getToolsSummary(tools) {
  if (!tools || tools.length === 0) return ''

  // 按工具名分组统计
  const counts = {}
  tools.forEach(t => {
    counts[t.name] = (counts[t.name] || 0) + 1
  })

  // 生成摘要文本
  const parts = Object.entries(counts).map(([name, count]) => {
    const meta = toolMeta(name)
    return count > 1 ? `${meta.action} × ${count}` : meta.action
  })

  const total = tools.length
  const running = tools.filter(t => t.status === 'running').length
  const done = tools.filter(t => t.status === 'done').length

  if (running > 0) {
    return `正在使用 ${total} 个工具 (${done}/${total} 完成)：${parts.join('、')}`
  } else {
    return `使用了 ${total} 个工具：${parts.join('、')}`
  }
}

// 给代码块添加复制按钮
function addCopyButton(pre, codeBlock) {
  const button = document.createElement('button')
  button.className = 'code-copy-btn'
  button.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
    </svg>
  `
  button.title = '复制代码'

  button.addEventListener('click', async () => {
    const code = codeBlock.textContent
    try {
      await navigator.clipboard.writeText(code)
      button.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
      `
      button.classList.add('copied')
      setTimeout(() => {
        button.innerHTML = `
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
        `
        button.classList.remove('copied')
      }, 2000)
    } catch (err) {
      console.error('复制失败:', err)
    }
  })

  pre.style.position = 'relative'
  pre.appendChild(button)
}

// 代码块高亮函数
// 给代码块添加复制按钮（高亮由 marked 在 render 时完成，这里只负责按钮）。
// 注意：v-html 每次重渲染会重建 DOM，所以按钮需要在渲染稳定后（流式结束/加载后）添加。
function highlightCodeBlocks() {
  const pres = document.querySelectorAll('.bubble pre')
  if (pres.length === 0) return

  pres.forEach((pre) => {
    if (pre.querySelector('.code-copy-btn')) return // 已有按钮
    const code = pre.querySelector('code')
    if (code) {
      addCopyButton(pre, code)
    }
  })
}

// 流式结束后给代码块加复制按钮（流式中 v-html 不断重渲染会删掉按钮，故等结束）
watch(
  () => chat.streaming,
  (isStreaming) => {
    if (!isStreaming) {
      nextTick(() => {
        setTimeout(() => highlightCodeBlocks(), 100)
      })
    }
  }
)

// 加载历史消息后给代码块加复制按钮
watch(
  () => chat.messages.length,
  (newLen) => {
    if (newLen > 0) {
      nextTick(() => {
        setTimeout(() => highlightCodeBlocks(), 100)
      })
    }
  },
  { immediate: true }
)

// 吐字速度预设：倍速 → ms/字符
const SPEED_PRESETS = [
  { label: '0.5x', ms: 50 },
  { label: '1x',  ms: 25 },
  { label: '2x',  ms: 10 },
  { label: '3x',  ms: 3 },
]

function currentSpeedLabel() {
  const found = SPEED_PRESETS.find(p => p.ms === chat.typewriterSpeed)
  return found ? found.label : '1x'
}

function cycleSpeed() {
  const current = SPEED_PRESETS.findIndex(p => p.ms === chat.typewriterSpeed)
  const next = (current + 1) % SPEED_PRESETS.length
  chat.setSpeed(SPEED_PRESETS[next].ms)
}

function attachImage(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => pendingImages.value.push(reader.result)
  reader.readAsDataURL(file)
  e.target.value = ''
}

// 滚动到底部（使用 requestAnimationFrame 确保 DOM 更新完成）
function scrollToBottom(force = false) {
  requestAnimationFrame(() => {
    const el = scroller.value
    if (!el) return

    // 判断用户是否在底部附近
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 150

    if (force || atBottom) {
      // 直接设置 scrollTop，不用 smooth（避免频繁调用时冲突）
      el.scrollTop = el.scrollHeight
    }
  })
}

// 自动滚到底——新消息时强制滚
watch(
  () => chat.messages.length,
  () => {
    nextTick(() => scrollToBottom(true))
  }
)

// 流式输出时持续滚动（防抖优化）
let scrollTimer = null
watch(
  () => chat.messages.map((m) => m.content).join(''),
  () => {
    if (scrollTimer) return  // 已有待执行的滚动，跳过
    scrollTimer = setTimeout(() => {
      scrollToBottom(false)
      scrollTimer = null
    }, 50)  // 50ms 防抖
  }
)

// 流式状态变化时也滚动
watch(
  () => chat.streaming,
  () => {
    nextTick(() => scrollToBottom(false))
  }
)
</script>

<template>
  <div class="chat-container">
    <!-- 左侧：对话面板 -->
    <div class="chat" :class="{ 'with-artifact': chat.currentArtifact }">
      <div class="messages" ref="scroller">
        <div v-if="chat.messages.length === 0" class="empty">
          <p>👋 我是公司学习助手。</p>
          <p>在左侧上传公司文档构建知识库，我会基于这些资料回答；也可以在下方附上图片让我看图，或让我帮你读写工作区代码。</p>
        </div>
        <div v-for="(m, i) in chat.messages" :key="i" :class="['msg', m.role]">
        <div class="role">{{ m.role === 'user' ? '你' : '助手' }}</div>

        <!-- 思考过程区域（方案B：模拟 / 方案A：真实思考） -->
        <!-- <div v-if="m.role === 'assistant' && m.thinkingVisible" class="thinking-section">
          <div class="thinking-header">
            <span class="thinking-icon">🤔</span>
            <span class="thinking-label">{{ m.thinking ? '思考过程' : '正在思考...' }}</span>
          </div>
          <div v-if="m.thinking" class="thinking-content">
            {{ m.thinking }}
          </div>
          <div v-else class="thinking-dots">
            <span class="dot"></span>
            <span class="dot"></span>
            <span class="dot"></span>
          </div>
        </div> -->

        <!-- 工具调用：折叠显示 -->
        <div v-if="m.tools.length" class="tool-calls-wrapper">
          <!-- 折叠摘要：点击展开 -->
          <div class="tool-summary" @click="toggleTools(i)">
            <span class="tool-summary-icon">{{ toolsExpanded[i] ? '▼' : '▶' }}</span>
            <span class="tool-summary-text">{{ getToolsSummary(m.tools) }}</span>
          </div>

          <!-- 详细列表：展开时显示 -->
          <div v-if="toolsExpanded[i]" class="tool-calls">
            <div v-for="(t, j) in m.tools" :key="j" class="tool-call" :class="[t.status, { 'tc-sub': t.subagent }]">
              <span v-if="t.subagent" class="tc-sub-arrow">↳</span>
              <span class="tc-status">
                <svg v-if="t.status === 'done'" class="tc-check" viewBox="0 0 24 24" width="14" height="14">
                  <path d="M20 6L9 17l-5-5" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <svg v-else-if="t.status === 'error'" class="tc-x" viewBox="0 0 24 24" width="14" height="14">
                  <path d="M18 6L6 18M6 6l12 12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
                </svg>
                <span v-else class="tc-spinner"></span>
              </span>
              <span class="tc-icon">{{ toolMeta(t.name).icon }}</span>
              <span class="tc-action">{{ toolMeta(t.name).action }}</span>
              <span v-if="toolTarget(t)" class="tc-target">{{ toolTarget(t) }}</span>
            </div>
          </div>
        </div>
        <div v-if="m.role === 'assistant' && !m.content && !m.tools.length && chat.streaming" class="thinking">
          <span class="dot"></span>
          <span class="dot"></span>
          <span class="dot"></span>
          <span class="text">思考中</span>
        </div>
        <!-- 根据 streaming 状态选择渲染策略：流式时轻量级解析，完成后完整渲染 + 代码高亮 -->
        <div v-else class="bubble" v-html="render(m.content, m.streaming)" @click="onBubbleClick"></div>

        <!-- 引用来源卡片：展示 retrieve_knowledge 命中的具体段落（按段落去重、跨轮累积） -->
        <div v-if="m.sources && m.sources.length" class="sources-section">
          <div class="sources-head">📎 引用来源（{{ m.sources.length }} 段）</div>
          <div class="source-card" v-for="(s, si) in m.sources" :key="si">
            <div class="source-card-head" @click="openSource(s)">
              <span class="source-doc">📄 doc_id={{ s.doc_id }}</span>
              <span v-if="s.section_title" class="source-sec">{{ s.section_title }}</span>
              <span v-if="relevancePct(s.distance) != null" class="source-score">相关度 {{ relevancePct(s.distance) }}%</span>
            </div>
            <div class="source-snippet">
              {{ sourceExpanded[`${i}:${si}`] ? s.snippet : (s.snippet || '').slice(0, 150) }}<span v-if="!sourceExpanded[`${i}:${si}`] && (s.snippet || '').length > 150">…</span>
            </div>
            <button
              v-if="(s.snippet || '').length > 150"
              class="source-toggle"
              @click="toggleSource(i, si)"
            >{{ sourceExpanded[`${i}:${si}`] ? '收起' : '展开' }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 引用出处弹窗：点击回答里的 [n] 引用芯片时展示对应文档原文 -->
    <div v-if="citation" class="cite-overlay" @click="closeCitation">
      <div class="cite-modal" @click.stop>
        <div class="cite-head">
          <span class="cite-title">📄 {{ citation.name }}</span>
          <span class="cite-close" @click="closeCitation">✕</span>
        </div>
        <div class="cite-body">
          <div v-if="citationLoading" class="cite-loading">加载中…</div>
          <pre v-else>{{ citation.text }}</pre>
        </div>
      </div>
    </div>

    <div class="composer">
      <div class="box">
        <div v-if="pendingImages.length" class="thumbs">
          <img v-for="(src, i) in pendingImages" :key="i" :src="src" />
        </div>
        <textarea
          v-model="input"
          @keydown="onKeydown"
          placeholder="给 学习助手 发送消息"
          rows="1"
        ></textarea>
        <div class="bar">
          <div class="left-tools">
            <div class="tool-selector" @click="toggleSkillMenu">
              <span v-if="selectedSkills.length > 0">🔧 {{ selectedSkills.length }} 个技能</span>
              <span v-else>🔧 选择技能</span>
              <span class="arrow">▾</span>
              <div v-if="showSkillMenu" class="skill-menu" @click.stop>
                <div class="menu-item clear-item" v-if="selectedSkills.length > 0" @click="selectedSkills = []">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  </svg>
                  <span>清空选择</span>
                </div>
                <div
                  v-for="s in skills.skills"
                  :key="s.name"
                  class="menu-item"
                  :class="{ active: selectedSkills.includes(s.name) }"
                  @click="selectSkill(s.name)"
                >
                  <div class="item-content">
                    <input
                      type="checkbox"
                      :checked="selectedSkills.includes(s.name)"
                      @click.stop
                      class="skill-checkbox"
                    />
                    <div class="item-text">
                      <div class="item-name">{{ s.name }}</div>
                      <div class="menu-desc">{{ s.description }}</div>
                    </div>
                  </div>
                </div>
                <div v-if="skills.skills.length === 0" class="menu-empty">暂无技能</div>
              </div>
            </div>
            <div class="tool-selector kb-toggle" :class="{ active: useKnowledge }" @click="toggleKnowledge">
              <span>📚 知识库</span>
              <span class="toggle-indicator">{{ useKnowledge ? '✓' : '○' }}</span>
            </div>
            <div v-if="useKnowledge" class="tool-selector kb-toggle" :class="{ active: forceRetrieval }" @click="toggleForce" title="强制首轮检索知识库：开启更防幻觉但简单问题也会变慢；关闭则让模型自主判断是否检索">
              <span>🔒 强制检索</span>
              <span class="toggle-indicator">{{ forceRetrieval ? '✓' : '○' }}</span>
            </div>
            <div class="tool-selector kb-toggle" :class="{ active: useWeb }" @click="toggleWeb" title="联网搜索（DuckDuckGo）">
              <span>🌐 联网</span>
              <span class="toggle-indicator">{{ useWeb ? '✓' : '○' }}</span>
            </div>
            <div class="tool-selector speed-toggle" @click="cycleSpeed" title="吐字速度">
              <span>⏱ {{ currentSpeedLabel() }}</span>
            </div>
          </div>
          <div class="right-tools">
            <label class="attach" title="附加图片">
              📎
              <input type="file" accept="image/*" @change="attachImage" hidden />
            </label>
            <button v-if="chat.streaming" class="send stop" @click="chat.stop()" title="停止生成">
              <span class="stop-icon"></span>
            </button>
            <button v-else class="send" @click="submit" title="发送">
              <span>↑</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <div class="disclaimer">内容由 AI 生成，请仔细甄别</div>
  </div>

    <!-- 右侧：Artifact 预览面板 -->
    <ArtifactPanel
      v-if="chat.currentArtifact"
      :artifact="chat.currentArtifact"
      @close="chat.currentArtifact = null"
    />
  </div>
</template>

<style scoped>
.chat-container {
  display: flex;
  width: 100%;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  flex: 1;
  min-height: 0;
  min-width: 0;
  transition: flex 0.3s ease;
}

/* 当有 artifact 时，左侧对话面板占 50% */
.chat.with-artifact {
  flex: 0 0 50%;
  max-width: 50%;
}
.messages {
  flex: 1;
  overflow-y: scroll;
  padding: 24px 0;
  min-height: 0;
  /* Firefox：一直显示深色滚动条 */
  scrollbar-width: thin;
  scrollbar-color: #555 #e5e7eb;
}
/* WebKit（Chrome/Edge）：强制一直显示，深色 */
.messages::-webkit-scrollbar {
  width: 12px;
  -webkit-appearance: none;
}
.messages::-webkit-scrollbar-track {
  background: #e5e7eb;
}
.messages::-webkit-scrollbar-thumb {
  background: #555;
  border-radius: 6px;
  border: 2px solid #e5e7eb;
  min-height: 40px;
}
.messages::-webkit-scrollbar-thumb:hover {
  background: #333;
}
/* 居中的内容列，像 DeepSeek 一样限制宽度 */
.msg,
.empty {
  max-width: 760px;
  margin-left: auto;
  margin-right: auto;
  padding-left: 24px;
  padding-right: 24px;
}
.empty {
  color: var(--text-dim);
  text-align: center;
  margin-top: 80px;
  line-height: 1.9;
}
.msg {
  margin-bottom: 22px;
}

/* Assistant 消息：添加流程感 */
.msg.assistant {
  display: flex;
  flex-direction: column;
  gap: 12px; /* 工具区域和回答区域的间距 */
}

/* 思考/工具区域：轻微的视觉分隔 */
.msg.assistant .tool-calls-wrapper {
  padding: 8px 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  margin-bottom: 4px;
}

/* 回答区域：淡入动画 */
.msg.assistant .bubble {
  animation: fade-in-answer 0.4s ease;
}

@keyframes fade-in-answer {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.role {
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 6px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.msg.user {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.msg.user .bubble {
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.3);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  color: var(--text);
  max-width: 70%;
  padding: 4px 14px;
}
.bubble {
  display: inline-block;
  max-width: 100%;
  padding: 4px 12px;
  border-radius: 12px;
  background: transparent;
  line-height: 1.5;
  overflow-x: auto;
  word-wrap: break-word;
  color: var(--text); /* 普通文字用主题色，清晰可读 */
}
.msg.assistant .bubble {
  padding-left: 0;
  padding-right: 0;
  line-height: 1.6;
}
.bubble :deep(p) {
  margin: 8px 0;
}
.bubble :deep(p:first-child) {
  margin-top: 0;
}
.bubble :deep(p:last-child) {
  margin-bottom: 0;
}
.bubble :deep(pre) {
  background: #1e1e1e; /* VSCode 纯黑背景 */
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  padding: 14px;
  border-radius: 10px;
  overflow-x: auto;
  margin: 12px 0;
  border: 1px solid rgba(255, 255, 255, 0.1);
  white-space: pre; /* 保留空白符和换行 */
}
.bubble :deep(pre code) {
  display: block; /* 让 code 填满 pre */
  background: transparent !important; /* 确保 code 没有自己的背景 */
  padding: 0; /* 移除 code 的内边距 */
  margin: 0; /* 移除 code 的外边距 */
  font-family: 'JetBrains Mono', Consolas, 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.5;
  color: #d4d4d4; /* VSCode 默认文字色 */
  white-space: pre; /* 保留空白符和换行 */
}

/* VSCode Dark+ 语法高亮配色 */
.bubble :deep(pre code .hljs-keyword),
.bubble :deep(pre code .hljs-selector-tag),
.bubble :deep(pre code .hljs-literal),
.bubble :deep(pre code .hljs-section),
.bubble :deep(pre code .hljs-link) {
  color: #569cd6; /* 蓝色：关键字 */
}

.bubble :deep(pre code .hljs-string),
.bubble :deep(pre code .hljs-regexp),
.bubble :deep(pre code .hljs-attribute) {
  color: #ce9178; /* 橙色：字符串 */
}

.bubble :deep(pre code .hljs-number),
.bubble :deep(pre code .hljs-meta-string) {
  color: #b5cea8; /* 浅绿：数字 */
}

.bubble :deep(pre code .hljs-comment),
.bubble :deep(pre code .hljs-quote) {
  color: #6a9955; /* 绿色：注释 */
}

.bubble :deep(pre code .hljs-function),
.bubble :deep(pre code .hljs-title) {
  color: #dcdcaa; /* 黄色：函数名 */
}

.bubble :deep(pre code .hljs-type),
.bubble :deep(pre code .hljs-class),
.bubble :deep(pre code .hljs-built_in) {
  color: #4ec9b0; /* 青色：类型 */
}

.bubble :deep(pre code .hljs-variable),
.bubble :deep(pre code .hljs-attr) {
  color: #9cdcfe; /* 浅蓝：变量 */
}

.bubble :deep(pre code .hljs-params) {
  color: #ccc; /* 灰色：参数 */
}
.bubble :deep(code) {
  font-family: 'JetBrains Mono', Consolas, 'Courier New', monospace;
  font-size: 13px;
}
.bubble :deep(:not(pre) > code) {
  /* 行内代码：深色背景 */
  background: rgba(13, 17, 23, 0.7);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  padding: 2px 6px;
  border-radius: 4px;
  color: #e6edf3;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

/* 思考过程区域（Claude Code 风格） */
.thinking-section {
  margin-bottom: 12px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.03);
  border-left: 3px solid rgba(168, 85, 247, 0.5);
  border-radius: 6px;
  animation: fade-in 0.3s ease;
}

.thinking-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.thinking-icon {
  font-size: 16px;
  animation: thinking-pulse 2s ease-in-out infinite;
}

@keyframes thinking-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.6; transform: scale(1.1); }
}

.thinking-label {
  font-size: 13px;
  font-weight: 500;
  color: rgba(168, 85, 247, 0.9);
  letter-spacing: 0.02em;
}

.thinking-content {
  font-size: 13px;
  line-height: 1.6;
  color: rgba(148, 163, 184, 0.85);
  white-space: pre-wrap;
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
}

.thinking-dots {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 4px 0;
}

.thinking-dots .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(168, 85, 247, 0.6);
  animation: thinking-bounce 1.4s infinite ease-in-out;
}

.thinking-dots .dot:nth-child(1) {
  animation-delay: -0.32s;
}

.thinking-dots .dot:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes thinking-bounce {
  0%, 80%, 100% {
    transform: scale(0.8);
    opacity: 0.5;
  }
  40% {
    transform: scale(1.2);
    opacity: 1;
  }
}

/* 工具调用折叠容器 */
.tool-calls-wrapper {
  margin-bottom: 8px;
}

/* 工具调用摘要（VSCode 风格 + 动态效果） */
.tool-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: rgba(255, 255, 255, 0.03);
  border-left: 2px solid rgba(100, 116, 139, 0.3);
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 12.5px;
  color: rgba(148, 163, 184, 0.9);
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
}

.tool-summary:hover {
  background: rgba(255, 255, 255, 0.05);
  border-left-color: rgba(148, 163, 184, 0.5);
}

.tool-summary-icon {
  font-size: 9px;
  color: rgba(148, 163, 184, 0.7);
  transition: transform 0.15s ease;
  font-family: monospace;
  animation: rotate-icon 0.2s ease;
}

@keyframes rotate-icon {
  from { transform: rotate(-90deg); opacity: 0; }
  to { transform: rotate(0deg); opacity: 1; }
}

.tool-summary-text {
  flex: 1;
  font-weight: 400;
  letter-spacing: 0.01em;
  transition: color 0.2s ease;
}

/* 运行中的工具摘要：脉动效果 */
.tool-calls-wrapper:has(.tool-call.running) .tool-summary {
  border-left-color: rgba(59, 130, 246, 0.6);
  animation: pulse-border 2s ease-in-out infinite;
}

@keyframes pulse-border {
  0%, 100% { border-left-color: rgba(59, 130, 246, 0.6); }
  50% { border-left-color: rgba(59, 130, 246, 0.3); }
}

/* 引用来源卡片：展示 retrieve_knowledge 命中的具体段落 */
.sources-section {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sources-head {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  padding: 2px 2px 0;
}
.source-card {
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 8px;
  padding: 8px 10px;
  background: rgba(148, 163, 184, 0.06);
}
.source-card-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  cursor: pointer;
  font-size: 12px;
}
.source-card-head:hover .source-sec { text-decoration: underline; }
.source-doc { font-weight: 600; color: #475569; }
.source-sec { color: #1d4ed8; flex: 1; min-width: 0; }
.source-score { color: #059669; font-size: 11px; white-space: nowrap; }
.source-snippet {
  margin-top: 6px;
  font-size: 12.5px;
  line-height: 1.55;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-word;
}
.source-toggle {
  margin-top: 4px;
  background: none;
  border: none;
  color: #3b82f6;
  font-size: 12px;
  cursor: pointer;
  padding: 2px 0;
}
.source-toggle:hover { text-decoration: underline; }

/* 工具调用 —— 统一一行式（学 Claude Code 风格） */
.tool-calls {
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.tool-call {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 10px;
  border-radius: 8px;
  font-size: 12.5px;
  line-height: 1.4;
  background: transparent;
  transition: all 0.2s ease;
  animation: slide-in 0.3s ease;
}

@keyframes slide-in {
  from {
    opacity: 0;
    transform: translateX(-8px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.tool-call:hover {
  background: rgba(148, 163, 184, 0.08);
}

/* 子助手内部的工具调用：缩进 + 左侧竖线，体现「委托层级」 */
.tool-call.subagent {
  margin-left: 16px;
  padding-left: 10px;
  border-left: 2px solid rgba(148, 163, 184, 0.3);
}
.tc-sub-arrow {
  color: #94a3b8;
  font-size: 12px;
  margin-right: 1px;
}

/* 运行中的工具：左边框动画 */
.tool-call.running {
  border-left: 2px solid rgba(59, 130, 246, 0.5);
  padding-left: 8px;
  background: rgba(59, 130, 246, 0.03);
}

/* 完成的工具：淡入效果 */
.tool-call.done {
  animation: fade-in-done 0.4s ease;
}

@keyframes fade-in-done {
  from {
    background: rgba(34, 197, 94, 0.1);
  }
  to {
    background: transparent;
  }
}
.tc-status {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
}
.tc-check { color: #22c55e; }
.tc-x { color: #ef4444; }
.tc-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(100, 116, 139, 0.25);
  border-top-color: #64748b;
  border-radius: 50%;
  animation: tc-spin 0.7s linear infinite;
}
@keyframes tc-spin {
  to { transform: rotate(360deg); }
}
.tc-icon {
  flex: none;
  font-size: 12px;
  opacity: 0.85;
}
.tc-action {
  flex: none;
  color: #475569;
  font-weight: 500;
}
.tool-call.done .tc-action { color: #334155; }
.tool-call.error .tc-action { color: #ef4444; }
.tc-target {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #64748b;
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 12px;
}
.thinking {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 16px;
  color: var(--text-dim);
  font-size: 13px;
}
.thinking .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-dim);
  animation: thinking-bounce 1.4s infinite ease-in-out;
}
.thinking .dot:nth-child(1) {
  animation-delay: -0.32s;
}
.thinking .dot:nth-child(2) {
  animation-delay: -0.16s;
}
@keyframes thinking-bounce {
  0%, 80%, 100% {
    transform: scale(0.8);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}
.composer {
  padding: 0 20px 8px;
}
.box {
  max-width: 760px;
  margin: 0 auto;
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 24px;
  padding: 12px 14px 10px;
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.5);
}
.thumbs {
  margin-bottom: 8px;
}
.thumbs img {
  height: 56px;
  border-radius: 8px;
  margin-right: 6px;
}
textarea {
  width: 100%;
  resize: none;
  border: none;
  outline: none;
  padding: 4px 6px;
  font: inherit;
  font-size: 15px;
  line-height: 1.5;
  max-height: 180px;
  background: transparent;
}
.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
}
.left-tools,
.right-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chip {
  font-size: 13px;
  color: var(--brand);
  background: var(--brand-soft);
  border-radius: 999px;
  padding: 5px 12px;
}
.tool-selector {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: var(--brand-soft);
  color: var(--brand);
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
  user-select: none;
}
.tool-selector:hover {
  background: #d4e0ff;
}
.tool-selector .arrow {
  font-size: 10px;
  opacity: 0.7;
}
.kb-toggle {
  background: #f0f0f0;
  color: var(--text);
}
.kb-toggle.active {
  background: var(--brand-soft);
  color: var(--brand);
}
.speed-toggle {
  background: #f0f0f0;
  color: var(--text);
  cursor: pointer;
  min-width: 48px;
  justify-content: center;
}
.speed-toggle:hover {
  background: var(--brand-soft);
  color: var(--brand);
}
.toggle-indicator {
  font-size: 11px;
  font-weight: bold;
}
.skill-menu {
  position: absolute;
  bottom: 100%;
  left: 0;
  margin-bottom: 6px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  min-width: 220px;
  max-width: 320px;
  max-height: 280px;
  overflow-y: auto;
  z-index: 100;
}
.menu-item {
  padding: 10px 12px;
  cursor: pointer;
  font-size: 13px;
  border-bottom: 1px solid #f0f0f0;
  transition: background 0.1s;
}
.menu-item:last-child {
  border-bottom: none;
}
.menu-item:hover {
  background: var(--sidebar-hover);
}
.menu-item.active {
  background: var(--sidebar-hover);
}
.item-content {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.skill-checkbox {
  margin-top: 2px;
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--brand);
  flex-shrink: 0;
}
.item-text {
  flex: 1;
  min-width: 0;
}
.item-name {
  font-size: 13px;
  color: var(--text);
  font-weight: 500;
}
.clear-item {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  color: #86868b;
  font-size: 13px;
  background: transparent !important;
}
.clear-item:hover {
  color: #e64545;
  background: var(--sidebar-hover) !important;
}
.clear-item svg {
  flex-shrink: 0;
}
.menu-desc {
  display: block;
  font-size: 10px;
  color: var(--text-dim);
  margin-top: 2px;
}
.menu-empty {
  padding: 12px;
  text-align: center;
  font-size: 11px;
  color: var(--text-dim);
}
.attach {
  cursor: pointer;
  font-size: 17px;
  color: var(--text-dim);
  padding: 4px;
}
.send {
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 50%;
  background: var(--brand);
  color: #fff;
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.send:disabled {
  background: #c2ccf8;
  cursor: default;
}
/* 停止按钮：深色圆钮 + 白色方块（学 Claude Code 停止交互） */
.send.stop {
  background: #1f2937;
  transition: background 0.15s ease;
}
.send.stop:hover {
  background: #374151;
}
.stop-icon {
  width: 11px;
  height: 11px;
  border-radius: 2px;
  background: #fff;
}
.disclaimer {
  text-align: center;
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 4px;
  padding-bottom: 2px;
}
/* 引用出处芯片 */
.bubble :deep(.cite) {
  cursor: pointer;
  color: var(--brand);
  font-weight: 600;
  padding: 0 2px;
  user-select: none;
}
.bubble :deep(.cite:hover) {
  text-decoration: underline;
}
/* 引用出处弹窗 */
.cite-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.cite-modal {
  background: var(--bg, #fff);
  width: min(760px, 90vw);
  max-height: 80vh;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.25);
}
.cite-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border, #eee);
}
.cite-title {
  font-weight: 600;
  font-size: 14px;
}
.cite-close {
  cursor: pointer;
  color: var(--text-dim);
  font-size: 16px;
}
.cite-body {
  overflow: auto;
  padding: 16px;
}
.cite-body pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
  margin: 0;
}
.cite-loading {
  text-align: center;
  color: var(--text-dim);
  padding: 24px;
}

/* 代码高亮渐进过渡动画 */
.bubble pre code.highlighting {
  opacity: 0.7;
}

.bubble pre code.highlighted {
  opacity: 1;
}

/* 代码高亮内的 span 元素颜色过渡 */
.bubble pre code span {
  transition: color 0.25s ease, background-color 0.25s ease;
}

/* 代码块复制按钮 */
.bubble :deep(pre) {
  position: relative;
}

.bubble :deep(.code-copy-btn) {
  position: absolute; /* 改回 absolute，相对于 pre 定位 */
  top: 8px;
  right: 8px;
  padding: 4px 6px; /* 减小内边距 */
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 4px; /* 减小圆角 */
  cursor: pointer;
  opacity: 0.6; /* 默认半透明可见 */
  transition: all 0.2s;
  color: rgba(255, 255, 255, 0.8);
  z-index: 10; /* 确保在代码上方 */
  backdrop-filter: blur(8px); /* 背景模糊，避免遮挡代码时难看 */
  -webkit-backdrop-filter: blur(8px);
  line-height: 1; /* 保持一行高度 */
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.bubble :deep(pre:hover .code-copy-btn),
.bubble :deep(.code-copy-btn:hover) {
  opacity: 1; /* hover 时完全不透明 */
}

.bubble :deep(.code-copy-btn:hover) {
  background: rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 1);
}

.bubble :deep(.code-copy-btn.copied) {
  background: rgba(34, 197, 94, 0.2);
  border-color: rgba(34, 197, 94, 0.4);
  color: rgb(34, 197, 94);
}

.bubble :deep(.code-copy-btn svg) {
  display: block;
}
</style>
