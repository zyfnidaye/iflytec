<script setup>
import { ref, onMounted } from 'vue'
import ChatPanel from './components/ChatPanel.vue'
import ConversationList from './components/ConversationList.vue'
import DragHandle from './components/DragHandle.vue'
import FileUpload from './components/FileUpload.vue'
import KnowledgePreview from './components/KnowledgePreview.vue'
import SkillPreview from './components/SkillPreview.vue'
import SkillsPanel from './components/SkillsPanel.vue'
import WorkspaceTree from './components/WorkspaceTree.vue'
import WorkspacePreview from './components/WorkspacePreview.vue'
import LiveFilePreview from './components/LiveFilePreview.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import RightDrawer from './components/RightDrawer.vue'
import IconBar from './components/IconBar.vue'
import SearchPanel from './components/SearchPanel.vue'
import { useChatStore } from './stores/chat.js'
import { useKnowledgeStore } from './stores/knowledge.js'

const chat = useChatStore()
const kb = useKnowledgeStore()
const wsRef = ref(null)

// 可拖拽尺寸（记到 localStorage，刷新保留）
const LS_W = 'code-agent:leftWidth'
const LS_H = 'code-agent:convoHeight'
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

function loadNum(key, def) {
  try {
    const v = parseFloat(localStorage.getItem(key))
    return Number.isFinite(v) ? v : def
  } catch {
    return def
  }
}
function saveNum(key, v) {
  try {
    localStorage.setItem(key, String(v))
  } catch {
    // 忽略
  }
}

const leftWidth = ref(loadNum(LS_W, 300)) // 左栏宽度 px
const panelsHeight = ref(loadNum(LS_H, '50%')) // 下方知识库+工作区高度，默认 50%
const sidebarCollapsed = ref(false) // 侧边栏是否折叠
const searchPanelVisible = ref(false) // 搜索面板是否显示

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  // 展开侧边栏时关闭搜索面板
  if (!sidebarCollapsed.value) {
    searchPanelVisible.value = false
  }
}

function toggleSearch() {
  searchPanelVisible.value = !searchPanelVisible.value
}

function resizeLeft({ dx }) {
  leftWidth.value = clamp(leftWidth.value + dx, 200, 560)
  saveNum(LS_W, leftWidth.value)
}
function resizePanels({ dy }) {
  // 拖拽条是下方面板的上边缘：往上拖(dy<0)面板变大，往下拖(dy>0)变小
  // 转换为数字处理
  const currentHeight = typeof panelsHeight.value === 'string'
    ? window.innerHeight * 0.5
    : panelsHeight.value
  const newHeight = clamp(currentHeight - dy, 120, 600)
  panelsHeight.value = newHeight
  saveNum(LS_H, newHeight)
}

// 刷新后加载会话列表并尝试恢复上次会话的历史
onMounted(async () => {
  // 先加载会话列表和知识库列表
  await Promise.all([
    chat.loadList(),
    kb.loadList()
  ])

  // 再尝试恢复当前会话内容（仅当 threadId 存在于列表中）
  const exists = chat.conversations.some(c => c.thread_id === chat.threadId)
  if (exists) {
    try {
      await chat.loadConversation(chat.threadId)
    } catch {
      // 加载失败则忽略
    }
  }
})
</script>

<template>
  <div class="layout">
    <!-- 图标栏（折叠时显示） -->
    <IconBar v-if="sidebarCollapsed" @toggle-sidebar="toggleSidebar" @toggle-search="toggleSearch" />

    <!-- 搜索面板 -->
    <SearchPanel v-if="sidebarCollapsed && searchPanelVisible" @close="toggleSearch" />

    <aside class="left" :class="{ collapsed: sidebarCollapsed }" :style="{ width: sidebarCollapsed ? '0' : leftWidth + 'px' }">
      <div class="brand">
        <div class="brand-left">
          <span class="brand-cn">科大讯飞</span>
          <span class="brand-en">iFLYTEK</span>
        </div>
        <div class="brand-right">
          <SettingsPanel />
        </div>
      </div>
      <button class="new-chat" @click="chat.newConversation()">
        <span class="plus">＋</span> 开启新对话
      </button>

      <div class="convo-region">
        <ConversationList @toggle-sidebar="toggleSidebar" />
      </div>

      <DragHandle orientation="row" @delta="resizePanels" />

      <div class="panels" :style="{ height: typeof panelsHeight === 'number' ? panelsHeight + 'px' : panelsHeight }">
        <FileUpload />
        <SkillsPanel />
        <div class="ws-region">
          <WorkspaceTree ref="wsRef" />
        </div>
      </div>
    </aside>

    <DragHandle v-if="!sidebarCollapsed" orientation="col" @delta="resizeLeft" />

    <main :style="{ marginLeft: sidebarCollapsed ? '56px' : '0' }">
      <div class="topbar">
        <div class="title">{{ chat.currentTitle || '新对话' }}</div>
        <span class="mode">⚡ 快速模式</span>
      </div>
      <ChatPanel />
    </main>
    <RightDrawer />
    <KnowledgePreview />
    <SkillPreview />
    <WorkspacePreview />
    <LiveFilePreview />
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.left {
  flex: none;
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: var(--blur);
  -webkit-backdrop-filter: var(--blur);
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--border);
  box-shadow:
    inset -1px 0 0 0 rgba(255, 255, 255, 0.5),
    4px 0 32px rgba(0, 0, 0, 0.08);
  position: relative;
  transition: width 0.3s ease, opacity 0.3s ease;
}

.left.collapsed {
  opacity: 0;
  overflow: hidden;
  pointer-events: none;
}

.left::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.1) 0%, transparent 100%);
  pointer-events: none;
}
.brand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px 10px;
  position: relative;
  z-index: 1;
}
.brand-left {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex: 1;
}
.brand-cn {
  font-size: 20px;
  font-weight: 700;
  color: #003087;
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.05));
  letter-spacing: 0.5px;
}
.brand-en {
  font-size: 14px;
  font-weight: 600;
  color: #0066CC;
  letter-spacing: 0.3px;
}
.brand-right {
  flex: none;
}
.new-chat {
  margin: 4px 14px 12px;
  padding: 10px 0;
  border: none;
  border-radius: 999px;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.15) 0%, rgba(118, 75, 162, 0.15) 100%);
  color: var(--brand);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow:
    0 2px 8px rgba(102, 126, 234, 0.15),
    inset 0 1px 0 rgba(255, 255, 255, 0.3);
  position: relative;
  z-index: 1;
}
.new-chat:hover {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.25) 0%, rgba(118, 75, 162, 0.25) 100%);
  transform: translateY(-2px);
  box-shadow:
    0 6px 16px rgba(102, 126, 234, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.4);
}
.new-chat:active {
  transform: translateY(0);
}
.plus {
  font-weight: 700;
}
.convo-region {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.panels {
  flex: none;
  min-height: 0;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: transparent;
}
.ws-region {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: var(--blur-strong);
  -webkit-backdrop-filter: var(--blur-strong);
  box-shadow:
    inset 1px 0 0 0 rgba(255, 255, 255, 0.3),
    -4px 0 32px rgba(0, 0, 0, 0.08);
  position: relative;
}
main::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.05) 0%, transparent 100%);
  pointer-events: none;
}
main > * {
  flex: 1;
  min-height: 0;
}
.topbar {
  flex: none !important;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 24px;
  border-bottom: 1px solid var(--border);
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
}
.title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.mode {
  font-size: 12px;
  color: var(--text-dim);
  background: rgba(255, 255, 255, 0.2);
  padding: 4px 10px;
  border-radius: 8px;
}
</style>
