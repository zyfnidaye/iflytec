<script setup>
import { computed, ref } from 'vue'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'
import { useWorkspaceStore } from '../stores/workspace.js'

const workspace = useWorkspaceStore()
const copied = ref(false)

// 从文件扩展名推断语言
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

const highlighted = computed(() => {
  if (!workspace.preview?.content) return { lines: [], html: '' }
  const content = workspace.preview.content
  const lang = detectLang(workspace.preview.name)

  let html
  if (lang && hljs.getLanguage(lang)) {
    html = hljs.highlight(content, { language: lang }).value
  } else {
    html = hljs.highlightAuto(content).value
  }

  // 按行拆分用于行号
  const lines = html.split('\n')
  return { lines, html }
})

function lineCount() {
  return highlighted.value.lines.length
}

async function copyContent() {
  if (!workspace.preview?.content) return
  try {
    await navigator.clipboard.writeText(workspace.preview.content)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch {
    // fallback
    const ta = document.createElement('textarea')
    ta.value = workspace.preview.content
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  }
}
</script>

<template>
  <div v-if="workspace.preview" class="mask" @click.self="workspace.closePreview()">
    <div class="dialog">
      <!-- 头部：文件信息 + 操作按钮 -->
      <div class="head">
        <span class="icon">{{ workspace.preview.icon }}</span>
        <div class="head-info">
          <span class="title">{{ workspace.preview.name }}</span>
          <span class="path" :title="workspace.preview.path">{{ workspace.preview.path }}</span>
        </div>
        <span class="line-count">{{ lineCount() }} 行</span>
        <button class="head-btn" @click="copyContent" :class="{ copied }">
          {{ copied ? '✓ 已复制' : '📋 复制' }}
        </button>
        <button class="head-btn" @click="workspace.downloadFile(workspace.preview)">
          ⬇ 下载
        </button>
        <button class="head-btn close-btn" @click="workspace.closePreview()">✕</button>
      </div>

      <!-- 代码区：行号 + 高亮 -->
      <div class="body">
        <div class="code-wrapper">
          <table class="code-table">
            <tbody>
              <tr v-for="(line, i) in highlighted.lines" :key="i" class="code-row">
                <td class="line-num" :data-line="i + 1"></td>
                <td class="line-code" v-html="line || '&nbsp;'"></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.dialog {
  width: 100%;
  max-width: 960px;
  max-height: 85vh;
  background: #1e1e1e;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

/* ---- 头部 ---- */
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #252526;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  flex: none;
}

.icon { font-size: 20px; flex: none; }

.head-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.title {
  font-size: 14px;
  font-weight: 600;
  color: #cccccc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.path {
  font-size: 11px;
  color: #888;
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.line-count {
  font-size: 11px;
  color: #888;
  background: rgba(255, 255, 255, 0.06);
  padding: 3px 10px;
  border-radius: 10px;
  white-space: nowrap;
}

.head-btn {
  padding: 5px 14px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.06);
  color: #cccccc;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.head-btn:hover {
  background: rgba(255, 255, 255, 0.12);
}
.head-btn.copied {
  background: rgba(64, 200, 128, 0.15);
  border-color: rgba(64, 200, 128, 0.3);
  color: #4ec990;
}

.close-btn {
  font-size: 16px;
  padding: 5px 10px;
  border: none;
  background: transparent;
}
.close-btn:hover {
  background: rgba(255, 80, 80, 0.2);
  color: #ff6b6b;
}

/* ---- 代码区 ---- */
.body {
  flex: 1;
  overflow: auto;
  background: #1e1e1e;
}

/* 自定义滚动条 — VSCode 风格 */
.body::-webkit-scrollbar { width: 10px; height: 10px; }
.body::-webkit-scrollbar-track { background: transparent; }
.body::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 5px;
  min-height: 30px;
}
.body::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.25); }
.body::-webkit-scrollbar-corner { background: transparent; }

.code-wrapper {
  min-width: max-content;
}

.code-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: auto;
}

.code-row {
  transition: background 0.05s;
}
.code-row:hover {
  background: rgba(255, 255, 255, 0.03);
}

/* 行号 */
.line-num {
  position: relative;
  width: 1px;
  padding: 0 24px 0 20px;
  text-align: right;
  vertical-align: top;
  user-select: none;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
}
.line-num::before {
  content: attr(data-line);
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.65;
  color: #6e7681;
}

/* 代码 */
.line-code {
  padding: 0 20px;
  vertical-align: top;
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.65;
  color: #e6edf3;
  white-space: pre;
}

/* highlight.js 主题覆盖 — 适配深色背景 */
.line-code :deep(.hljs-keyword)   { color: #ff7b72; }
.line-code :deep(.hljs-string)    { color: #a5d6ff; }
.line-code :deep(.hljs-number)    { color: #79c0ff; }
.line-code :deep(.hljs-comment)   { color: #6e7681; font-style: italic; }
.line-code :deep(.hljs-function)  { color: #d2a8ff; }
.line-code :deep(.hljs-title)     { color: #d2a8ff; }
.line-code :deep(.hljs-built_in)  { color: #ffa657; }
.line-code :deep(.hljs-type)      { color: #ffa657; }
.line-code :deep(.hljs-attr)      { color: #79c0ff; }
.line-code :deep(.hljs-params)    { color: #e6edf3; }
.line-code :deep(.hljs-literal)   { color: #79c0ff; }
.line-code :deep(.hljs-meta)      { color: #6e7681; }
.line-code :deep(.hljs-section)   { color: #d2a8ff; }
.line-code :deep(.hljs-selector-class) { color: #ffa657; }
.line-code :deep(.hljs-decorator) { color: #ffa657; }
</style>
