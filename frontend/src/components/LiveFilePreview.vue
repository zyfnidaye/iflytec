<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'
import { useWorkspaceStore } from '../stores/workspace.js'

const workspace = useWorkspaceStore()

const LANG_MAP = {
  '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
  '.vue': 'xml', '.html': 'xml', '.css': 'css',
  '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml',
  '.md': 'markdown', '.xml': 'xml', '.csv': 'plaintext',
  '.java': 'java', '.go': 'go', '.rs': 'rust', '.sh': 'bash',
  '.sql': 'sql', '.c': 'c', '.cpp': 'cpp', '.h': 'c',
}

function detectLang(name) {
  if (!name) return ''
  const ext = name.substring(name.lastIndexOf('.')).toLowerCase()
  return LANG_MAP[ext] || ''
}

const highlightedHtml = computed(() => {
  const pv = workspace.livePreview
  if (!pv?.content) return ''
  const lang = detectLang(pv.name)
  try {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(pv.content, { language: lang }).value
    }
    return hljs.highlightAuto(pv.content).value
  } catch {
    return pv.content
  }
})

const bodyRef = ref(null)
// 内容增长时自动滚到底部，跟着 agent 写入实时往下走
watch(() => workspace.livePreview?.content, async () => {
  await nextTick()
  const el = bodyRef.value
  if (el) el.scrollTop = el.scrollHeight
})

// ---- 拖动 ----
const pos = ref({ x: null, y: null }) // null 时用默认的右下角
const dragging = ref(false)
let startX = 0, startY = 0, originX = 0, originY = 0

function onDragStart(e) {
  dragging.value = true
  const rect = e.currentTarget.closest('.live-window').getBoundingClientRect()
  originX = rect.left
  originY = rect.top
  startX = e.clientX
  startY = e.clientY
  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup', onDragEnd)
}
function onDragMove(e) {
  if (!dragging.value) return
  pos.value = {
    x: originX + (e.clientX - startX),
    y: originY + (e.clientY - startY),
  }
}
function onDragEnd() {
  dragging.value = false
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragEnd)
}

const windowStyle = computed(() => {
  if (pos.value.x === null) return {} // 用 CSS 默认定位（右下角）
  return { left: pos.value.x + 'px', top: pos.value.y + 'px', right: 'auto', bottom: 'auto' }
})

const minimized = ref(false)

const lineCount = computed(() => {
  const c = workspace.livePreview?.content
  return c ? c.split('\n').length : 0
})

async function copyContent() {
  const c = workspace.livePreview?.content
  if (!c) return
  try { await navigator.clipboard.writeText(c) } catch { /* ignore */ }
}
</script>

<template>
  <div
    v-if="workspace.livePreview"
    class="live-window"
    :class="{ minimized }"
    :style="windowStyle"
  >
    <!-- 标题栏：可拖动 -->
    <div class="lw-head" @mousedown="onDragStart">
      <span class="lw-icon">{{ workspace.livePreview.icon }}</span>
      <span class="lw-title" :title="workspace.livePreview.path">{{ workspace.livePreview.name }}</span>
    <span class="lw-live" :class="{ done: workspace.livePreview.done }">
      <span class="lw-dot"></span>
      {{ workspace.livePreview.done ? '已完成' : '写入中' }}
    </span>
      <div class="lw-actions" @mousedown.stop>
        <button class="lw-btn" @click="copyContent" title="复制">📋</button>
        <button class="lw-btn" @click="minimized = !minimized" :title="minimized ? '展开' : '收起'">
          {{ minimized ? '▢' : '—' }}
        </button>
        <button class="lw-btn" @click="workspace.closeLivePreview()" title="关闭">✕</button>
      </div>
    </div>
    <!-- 内容 -->
    <div v-show="!minimized" class="lw-body" ref="bodyRef">
      <pre class="lw-code"><code v-html="highlightedHtml"></code></pre>
    </div>
    <div v-show="!minimized" class="lw-foot">
      <span class="lw-path">{{ workspace.livePreview.path }}</span>
      <span class="lw-lines">{{ lineCount }} 行</span>
    </div>
  </div>
</template>

<style scoped>
.live-window {
  position: fixed;
  right: 24px;
  bottom: 24px;
  width: 420px;
  max-width: calc(100vw - 48px);
  height: 480px;
  display: flex;
  flex-direction: column;
  background: #1e1e2e;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
  z-index: 9999;
  overflow: hidden;
  font-size: 13px;
}
.live-window.minimized {
  height: auto;
}

/* 标题栏 */
.lw-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: #2a2a3c;
  cursor: move;
  user-select: none;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.lw-icon { flex: none; font-size: 14px; }
.lw-title {
  flex: 1;
  color: #e6edf3;
  font-weight: 600;
  font-family: 'Consolas', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lw-live {
  flex: none;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #4ade80;
}
.lw-live.done {
  color: #9ca3af;
}
.lw-live.done .lw-dot {
  background: #9ca3af;
  animation: none;
}
.lw-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4ade80;
  animation: lw-pulse 1s ease-in-out infinite;
}
@keyframes lw-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.lw-actions { display: flex; gap: 2px; }
.lw-btn {
  background: none;
  border: none;
  color: #9ca3af;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1;
}
.lw-btn:hover { background: rgba(255, 255, 255, 0.1); color: #fff; }

/* 内容 */
.lw-body {
  flex: 1;
  overflow: auto;
  padding: 12px 14px;
  background: #1e1e2e;
}
.lw-code {
  margin: 0;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12.5px;
  line-height: 1.6;
  color: #e6edf3;
  white-space: pre-wrap;
  word-break: break-word;
}
.lw-body::-webkit-scrollbar { width: 10px; }
.lw-body::-webkit-scrollbar-thumb { background: #555; border-radius: 5px; }
.lw-body::-webkit-scrollbar-track { background: #2a2a3c; }

/* 底栏 */
.lw-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  background: #2a2a3c;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 11px;
  color: #9ca3af;
}
.lw-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: 'Consolas', monospace;
}
.lw-lines { flex: none; margin-left: 8px; }
</style>
