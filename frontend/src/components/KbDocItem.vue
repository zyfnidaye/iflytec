<script setup>
// 知识库单个文档项：图标 + 名称/元数据 + 重命名 + 移动到文件夹 + 删除。
// 文件夹块和根目录复用同一个组件。
import { ref, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useKnowledgeStore } from '../stores/knowledge.js'

const props = defineProps({
  doc: { type: Object, required: true },
})

const kb = useKnowledgeStore()

// ===== 拖拽源 =====
const dragging = ref(false)
function onDragStart(e) {
  console.log('[KbDocItem] dragstart', props.doc.id)
  console.log('[KbDocItem] dataTransfer effectAllowed 支持:', e.dataTransfer !== undefined)
  dragging.value = true
  // 用 dataTransfer 携带文档 id + 当前所在文件夹（供 drop 端判断是否需要移动）
  e.dataTransfer.effectAllowed = 'move'
  const payload = JSON.stringify({
    id: props.doc.id,
    fromFolder: props.doc.folder || null,
  })
  e.dataTransfer.setData('application/x-kb-doc', payload)
  // 兼容性兜底：部分浏览器要求必须设 text/plain 才允许拖拽
  e.dataTransfer.setData('text/plain', payload)
  // 通知全局：正在拖拽（让文件夹高亮可放置）
  kb.dragDocId = props.doc.id
  console.log('[KbDocItem] kb.dragDocId 已设为', kb.dragDocId)
  console.log('[KbDocItem] 验证读回:', kb.dragDocId)
}
let lastDragEnd = 0
function onDragEnd() {
  dragging.value = false
  lastDragEnd = Date.now() // 记录拖拽结束时刻，用于抑制紧随其后的误触 click
  kb.dragDocId = null
}

// 文档图标
const extIcon = (d) => {
  if (d.source_type === 'url') return '🌐'
  const map = { '.pdf': '📕', '.docx': '📘', '.doc': '📘', '.txt': '📄', '.md': '📝' }
  const ext = d.name.substring(d.name.lastIndexOf('.')).toLowerCase()
  return map[ext] || '📄'
}

// 重命名
const editing = ref(false)
const editName = ref('')
const nameInput = ref(null)
function startRename() {
  editing.value = true
  editName.value = props.doc.name
  nextTick(() => { nameInput.value?.focus(); nameInput.value?.select() })
}
function cancelRename() { editing.value = false }
async function saveRename() {
  const n = editName.value.trim()
  if (!n) { editing.value = false; return }
  try { await kb.updateName(props.doc.id, n) } catch { /* store 提示 */ }
  editing.value = false
}

async function del() {
  await kb.remove(props.doc.id)
}

// 更新：用新文件替换当前文档内容（保持同一 doc_id）
const replaceInput = ref(null)
function triggerReplace() {
  replaceInput.value?.click()
}
async function onReplaceFile(e) {
  const file = e.target.files?.[0]
  e.target.value = '' // 允许再次选同名文件
  if (!file) return
  await kb.replaceDoc(props.doc.id, file)
}

// 打开预览：拖拽刚结束(300ms内)时抑制误触的 click
function onItemClick() {
  if (dragging.value || Date.now() - lastDragEnd < 300) return
  kb.openPreview(props.doc.id)
}

// 右键菜单：移动到文件夹
const showContextMenu = ref(false)
const menuX = ref(0)
const menuY = ref(0)

function onContextMenu(e) {
  e.preventDefault()
  console.log('[KbDocItem] 右键菜单触发', e.clientX, e.clientY)
  menuX.value = e.clientX
  menuY.value = e.clientY
  showContextMenu.value = true
  console.log('[KbDocItem] showContextMenu =', showContextMenu.value)
}

async function moveToFolder(folderName) {
  showContextMenu.value = false
  if (folderName === null) {
    // 移到根目录
    if (!props.doc.folder) return // 已经在根目录
    await kb.moveToFolder(props.doc.id, null)
  } else {
    // 移到指定文件夹
    if (props.doc.folder === folderName) return // 已经在这个文件夹
    await kb.moveToFolder(props.doc.id, folderName)
  }
}

function closeContextMenu() {
  showContextMenu.value = false
}

// 点击外部关闭菜单
onMounted(() => {
  document.addEventListener('click', closeContextMenu)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', closeContextMenu)
})
</script>

<template>
  <div
    class="doc-item"
    :class="{ dragging, 'dnd-active': kb.dragDocId }"
    draggable="true"
    @dragstart="onDragStart"
    @dragend="onDragEnd"
    @click="onItemClick"
    @contextmenu="onContextMenu"
  >
    <span class="drag-handle" title="拖拽移动">⠿</span>
    <span class="doc-icon">{{ extIcon(doc) }}</span>
    <div class="doc-info">
      <input
        v-if="editing"
        v-model="editName"
        class="doc-name-input"
        @keyup.enter="saveRename"
        @keyup.esc="cancelRename"
        @blur="saveRename"
        @click.stop
        ref="nameInput"
      />
      <div v-else class="doc-name">{{ doc.name }}</div>
      <div
        class="doc-meta"
        :class="{ indexing: doc.status === 'indexing', failed: doc.status === 'failed' }"
      >
        {{ doc.char_count }} 字
        <template v-if="doc.status === 'indexing'">• 索引中...</template>
        <template v-if="doc.status === 'failed'">• 索引失败</template>
      </div>
    </div>

    <!-- 更新：仅文件类型文档，重传新版本覆盖同一 doc_id -->
    <button
      v-if="!editing && doc.source_type === 'file'"
      class="rename-btn"
      @click.stop="triggerReplace"
      title="更新（上传新版本替换）"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 2v6h-6"/>
        <path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
        <path d="M3 22v-6h6"/>
        <path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
      </svg>
    </button>
    <input
      ref="replaceInput"
      type="file"
      style="display: none"
      accept=".pdf,.docx,.doc,.txt,.md"
      @change="onReplaceFile"
    />

    <!-- 重命名 -->
    <button v-if="!editing" class="rename-btn" @click.stop="startRename" title="重命名">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
      </svg>
    </button>

    <!-- 删除 -->
    <button class="delete-btn" @click.stop="del" title="删除">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
      </svg>
    </button>
  </div>

  <!-- 右键菜单：独立渲染层，避免被父级裁剪 -->
  <Teleport to="body" v-if="showContextMenu">
    <div
      class="context-menu"
      :style="{ left: menuX + 'px', top: menuY + 'px' }"
      @click.stop
    >
      <div class="context-menu-header">移动到</div>
      <div
        v-if="doc.folder"
        class="context-menu-item"
        @click="moveToFolder(null)"
      >
        📂 根目录
      </div>
      <div
        v-for="folder in kb.folders"
        :key="folder.id"
        class="context-menu-item"
        :class="{ disabled: doc.folder === folder.name }"
        @click="moveToFolder(folder.name)"
      >
        📁 {{ folder.name }}
        <span v-if="doc.folder === folder.name" class="current-badge">当前</span>
      </div>
      <div v-if="kb.folders.length === 0" class="context-menu-empty">
        暂无文件夹
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* doc-item 基础样式（从 RightDrawer 迁来，scoped 不跨组件，需在此重定义） */
.doc-item {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.3);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 12px; cursor: pointer; transition: all 0.2s;
}
.doc-item:hover { background: rgba(255, 255, 255, 0.4); transform: translateX(-2px); }
/* 拖拽中：半透明 */
.doc-item.dragging { opacity: 0.4; }
/* 拖拽进行时禁用 backdrop-filter：规避 Chromium 下它干扰拖放命中的问题 */
.doc-item.dnd-active { backdrop-filter: none !important; -webkit-backdrop-filter: none !important; }
/* 拖拽手柄：hover 时显现 */
.drag-handle {
  flex: none; color: #cbd5e1; cursor: grab; font-size: 15px;
  opacity: 0; transition: opacity 0.2s; user-select: none;
}
.doc-item:hover .drag-handle { opacity: 1; }
.drag-handle:active { cursor: grabbing; }
.doc-icon { font-size: 22px; flex: none; }
.doc-info { flex: 1; min-width: 0; }
.doc-name {
  font-size: 14px; color: #1d1d1f; font-weight: 600;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px;
}
.doc-meta { font-size: 12px; color: #86868b; }
.doc-meta.indexing { color: #c9a76e; }
.doc-meta.failed { color: #c88a8a; }
.doc-name-input {
  font-size: 14px; color: #1d1d1f; font-weight: 600; padding: 4px 8px;
  border: 2px solid #007aff; border-radius: 6px; background: rgba(255,255,255,0.95);
  outline: none; margin-bottom: 4px; width: 100%;
}
/* 操作按钮：hover 时才显现，避免拥挤 */
.rename-btn, .delete-btn { opacity: 0; }
.doc-item:hover .rename-btn,
.doc-item:hover .delete-btn { opacity: 1; }
.rename-btn, .delete-btn {
  background: none; border: none; cursor: pointer; padding: 4px;
  color: #94a3b8; border-radius: 6px; display: flex; align-items: center; flex: none;
}
.rename-btn:hover { color: #3b82f6; background: rgba(59,130,246,0.1); }
.delete-btn:hover { color: #ef4444; background: rgba(239,68,68,0.1); }

/* 右键菜单 */
.context-menu {
  position: fixed;
  z-index: 9999;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
  padding: 8px;
  min-width: 180px;
  animation: menuFadeIn 0.15s ease-out;
}
@keyframes menuFadeIn {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}
.context-menu-header {
  font-size: 11px;
  color: #86868b;
  padding: 6px 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.context-menu-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  margin: 2px 0;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  color: #1d1d1f;
  transition: all 0.15s;
}
.context-menu-item:hover {
  background: rgba(0, 122, 255, 0.1);
  color: #007aff;
}
.context-menu-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.context-menu-item.disabled:hover {
  background: transparent;
  color: #1d1d1f;
}
.current-badge {
  font-size: 11px;
  color: #86868b;
  background: rgba(0, 0, 0, 0.05);
  padding: 2px 8px;
  border-radius: 4px;
}
.context-menu-empty {
  padding: 12px;
  text-align: center;
  color: #86868b;
  font-size: 13px;
}
</style>
