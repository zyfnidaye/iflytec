<script setup>
import { computed, ref } from 'vue'
import { useKnowledgeStore } from '../stores/knowledge.js'

const kb = useKnowledgeStore()
const copied = ref(false)
const editingName = ref(false)
const newName = ref('')

// 解析文档结构：始终返回全正文，不拆分 header/content（用户要求全正文展示）
const parsedDoc = computed(() => {
  if (!kb.preview?.text) return null
  return { header: null, content: kb.preview.text }
})

function lineCount(text) {
  return text ? text.split('\n').length : 0
}

async function copyContent() {
  if (!kb.preview?.text) return
  try {
    await navigator.clipboard.writeText(kb.preview.text)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = kb.preview.text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  }
}

function startRename() {
  newName.value = kb.preview.name
  editingName.value = true
}

function cancelRename() {
  editingName.value = false
  newName.value = ''
}

async function saveRename() {
  if (!newName.value.trim() || !kb.preview) return
  await kb.updateName(kb.preview.id, newName.value.trim())
  editingName.value = false
}

</script>

<template>
  <div v-if="kb.preview" class="mask" @click.self="kb.closePreview()">
    <div class="dialog">
      <div class="head">
        <span class="icon">📄</span>
        <div class="head-info">
          <!-- 重命名编辑态 -->
          <div v-if="editingName" class="name-edit">
            <input v-model="newName" class="name-input" @keyup.enter="saveRename" @keyup.esc="cancelRename" />
            <button class="name-btn save" @click="saveRename" title="保存">✓</button>
            <button class="name-btn cancel" @click="cancelRename" title="取消">✕</button>
          </div>
          <!-- 正常显示 -->
          <template v-else>
            <span class="title" :title="kb.preview.name">{{ kb.preview.name }}</span>
            <button v-if="!kb.editing" class="rename-btn" @click="startRename" title="重命名">✏️</button>
          </template>
          <span class="subtitle">{{ kb.preview.char_count }} 字 · {{ kb.preview.type || '文档' }}</span>
        </div>
        <template v-if="!kb.editing">
          <button class="head-btn" @click="copyContent" :class="{ copied }">
            {{ copied ? '✓ 已复制' : '📋 复制' }}
          </button>
          <button
            v-if="kb.preview.status !== 'failed'"
            class="head-btn"
            @click="kb.startEdit()"
          >✏️ 编辑</button>
        </template>
        <template v-else>
          <button class="head-btn save-btn" @click="kb.saveEdit()" :disabled="kb.saving">
            {{ kb.saving ? '⏳ 保存中…' : '💾 保存' }}
          </button>
          <button class="head-btn" @click="kb.cancelEdit()" :disabled="kb.saving">取消</button>
        </template>
        <button class="head-btn close-btn" @click="kb.closePreview()">✕</button>
      </div>

      <!-- 编辑态：整篇正文可编辑，保存后重建向量 -->
      <div v-if="kb.editing" class="body edit-body">
        <div class="edit-hint">编辑正文后保存，后端会自动重建该文档的向量索引。</div>
        <textarea v-model="kb.editText" class="edit-area" spellcheck="false"></textarea>
      </div>

      <!-- 失败状态 -->
      <div v-else-if="kb.preview.status === 'failed'" class="failed">
        解析失败：{{ kb.preview.error }}
      </div>

      <!-- 文档内容 -->
      <div v-else-if="parsedDoc" class="body">
        <div v-if="parsedDoc.header" class="section header-section">
          <div class="section-label">📋 摘要 / 目录</div>
          <pre class="section-text">{{ parsedDoc.header }}</pre>
        </div>
        <div v-if="parsedDoc.content" class="section content-section">
          <div class="section-label">
            正文
            <span class="line-badge">{{ lineCount(parsedDoc.content) }} 行</span>
          </div>
          <pre class="section-text">{{ parsedDoc.content }}</pre>
        </div>
      </div>

      <!-- 无分隔符的纯文本 -->
      <div v-else class="body">
        <div class="section content-section">
          <div class="section-label">
            正文
            <span class="line-badge">{{ lineCount(kb.preview.text) }} 行</span>
          </div>
          <pre class="section-text">{{ kb.preview.text || '（无正文）' }}</pre>
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
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  z-index: 2000;
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
.subtitle {
  font-size: 11px;
  color: #888;
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
.head-btn:hover { background: rgba(255, 255, 255, 0.12); }
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

/* ---- 正文区 ---- */
.body {
  flex: 1;
  overflow: auto;
  background: #1e1e1e;
}

/* VSCode 风格滚动条 */
.body::-webkit-scrollbar { width: 10px; height: 10px; }
.body::-webkit-scrollbar-track { background: transparent; }
.body::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 5px;
  min-height: 30px;
}
.body::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.25); }

.section { padding: 20px 24px; }

.section-label {
  font-size: 11px;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.line-badge {
  font-size: 10px;
  font-weight: 500;
  color: #6e7681;
  background: rgba(255, 255, 255, 0.06);
  padding: 2px 8px;
  border-radius: 8px;
}

/* 摘要区 */
.header-section {
  background: rgba(255, 200, 50, 0.06);
  border-bottom: 2px solid rgba(255, 200, 50, 0.2);
}

/* 正文区 */
.content-section {
  background: transparent;
}

.section-text {
  margin: 0;
  padding: 16px 20px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.65;
  color: #e6edf3;
}

/* ---- 编辑态 ---- */
.save-btn {
  background: rgba(64, 200, 128, 0.15);
  border-color: rgba(64, 200, 128, 0.3);
  color: #4ec990;
}
.save-btn:disabled { opacity: 0.6; cursor: default; }
.edit-body {
  display: flex;
  flex-direction: column;
  padding: 16px 24px 24px;
}
.edit-hint {
  font-size: 11px;
  color: #888;
  margin-bottom: 10px;
}
.edit-area {
  flex: 1;
  min-height: 50vh;
  resize: vertical;
  padding: 16px 20px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  color: #e6edf3;
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.65;
  outline: none;
}
.edit-area:focus { border-color: var(--brand, #4a7cff); }

.failed {
  margin: 24px;
  padding: 20px;
  background: rgba(255, 80, 80, 0.08);
  border: 1px solid rgba(255, 80, 80, 0.25);
  border-radius: 8px;
  color: #ff6b6b;
  font-size: 14px;
}

/* ---- 重命名 ---- */
.rename-btn {
  margin-left: 6px;
  padding: 2px 6px;
  border: none;
  background: transparent;
  color: #888;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  opacity: 0;
}
.head-info:hover .rename-btn {
  opacity: 1;
}
.rename-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ccc;
}

.name-edit {
  display: flex;
  align-items: center;
  gap: 6px;
}
.name-input {
  flex: 1;
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  color: #e6edf3;
  font-size: 13px;
  outline: none;
  font-family: inherit;
}
.name-input:focus {
  border-color: var(--brand, #4a7cff);
  background: rgba(255, 255, 255, 0.12);
}
.name-btn {
  padding: 4px 8px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.08);
  color: #ccc;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.name-btn:hover {
  background: rgba(255, 255, 255, 0.15);
}
.name-btn.save {
  color: #4ec990;
  border-color: rgba(64, 200, 128, 0.3);
  background: rgba(64, 200, 128, 0.1);
}
.name-btn.save:hover {
  background: rgba(64, 200, 128, 0.2);
}
.name-btn.cancel:hover {
  background: rgba(255, 80, 80, 0.15);
  color: #ff6b6b;
}
</style>
