<script setup>
import { usePanelStore } from '../stores/panel.js'
import { useChatStore } from '../stores/chat.js'

const panel = usePanelStore()
const chat = useChatStore()

const emit = defineEmits(['toggle-sidebar', 'toggle-search'])

const buttons = [
  {
    icon: '📚',
    label: '知识库',
    action: () => panel.togglePanel('knowledge')
  },
  {
    icon: '🔧',
    label: '技能库',
    action: () => panel.togglePanel('skills')
  },
  {
    icon: '📁',
    label: '工作区',
    action: () => panel.togglePanel('workspace')
  },
  {
    icon: '⚙️',
    label: '设置',
    action: () => panel.togglePanel('settings')
  },
]
</script>

<template>
  <div class="icon-bar">
    <!-- 展开侧边栏按钮 -->
    <button class="icon-btn" @click="emit('toggle-sidebar')" title="展开侧边栏">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <path d="M9 3v18"/>
      </svg>
    </button>

    <!-- 搜索按钮 -->
    <button class="icon-btn" @click="emit('toggle-search')" title="搜索对话">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/>
        <path d="m21 21-4.35-4.35"/>
      </svg>
    </button>

    <!-- 新建对话按钮 -->
    <button class="icon-btn" @click="chat.newConversation()" title="新建对话">
      <span class="icon-text">＋</span>
    </button>

    <div class="divider"></div>

    <!-- 功能按钮 -->
    <button
      v-for="btn in buttons"
      :key="btn.label"
      class="icon-btn"
      :class="{ active: panel.activePanel === btn.label.replace('库', '').replace('设置', 'settings').replace('知识', 'knowledge').replace('技能', 'skills').replace('工作区', 'workspace') }"
      @click="btn.action"
      :title="btn.label"
    >
      <span class="icon-text">{{ btn.icon }}</span>
    </button>
  </div>
</template>

<style scoped>
.icon-bar {
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  width: 56px;
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-right: 1px solid rgba(255, 255, 255, 0.2);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 0;
  gap: 8px;
  z-index: 100;
  box-shadow: 2px 0 12px rgba(0, 0, 0, 0.05);
}

.icon-btn {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: var(--text);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  font-size: 20px;
  flex: none;
}

.icon-btn:hover {
  background: rgba(255, 255, 255, 0.2);
  transform: scale(1.05);
}

.icon-btn.active {
  background: rgba(64, 169, 255, 0.2);
  border-color: rgba(64, 169, 255, 0.4);
}

.icon-text {
  font-size: 18px;
}

.divider {
  width: 32px;
  height: 1px;
  background: rgba(255, 255, 255, 0.2);
  margin: 4px 0;
  flex: none;
}
</style>
