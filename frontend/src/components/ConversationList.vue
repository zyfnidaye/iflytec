<script setup>
import { onMounted, computed, ref } from 'vue'
import { useChatStore } from '../stores/chat.js'

const chat = useChatStore()
const searchQuery = ref('')
const emit = defineEmits(['toggle-sidebar'])

onMounted(() => {
  chat.loadList()
})

// 过滤会话
const filteredConversations = computed(() => {
  if (!searchQuery.value.trim()) {
    return chat.conversations
  }
  const q = searchQuery.value.toLowerCase()
  return chat.conversations.filter(c =>
    c.title.toLowerCase().includes(q)
  )
})

// 按时间把会话分组：今天 / 30 天内 / 按年月
const groups = computed(() => {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000
  const day = 86400
  const buckets = new Map()
  const order = []

  function bucket(label) {
    if (!buckets.has(label)) {
      buckets.set(label, [])
      order.push(label)
    }
    return buckets.get(label)
  }

  for (const c of filteredConversations.value) {
    const t = c.updated_at
    let label
    if (t >= startOfToday) label = '今天'
    else if (t >= startOfToday - 30 * day) label = '30 天内'
    else {
      const d = new Date(t * 1000)
      label = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    }
    bucket(label).push(c)
  }
  return order.map((label) => ({ label, items: buckets.get(label) }))
})

function open(threadId) {
  chat.loadConversation(threadId)
}
async function remove(threadId, e) {
  e.stopPropagation()
  if (!confirm('删除这个会话？')) return
  await chat.removeConversation(threadId)
}
</script>

<template>
  <div class="convo-container">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <div class="search-box">
        <svg class="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/>
          <path d="m21 21-4.35-4.35"/>
        </svg>
        <input
          v-model="searchQuery"
          type="text"
          class="search-input"
          placeholder="搜索对话..."
        />
      </div>
      <button class="toggle-btn" @click="emit('toggle-sidebar')" title="隐藏侧边栏">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="18" height="18" rx="2"/>
          <path d="M9 3v18"/>
        </svg>
      </button>
    </div>

    <!-- 对话列表 -->
    <div class="convo-list">
      <div v-if="filteredConversations.length === 0" class="empty">
        {{ searchQuery ? '未找到匹配的对话' : '暂无历史对话' }}
      </div>
      <div v-for="g in groups" :key="g.label" class="group">
        <div class="group-label">{{ g.label }}</div>
        <div
          v-for="c in g.items"
          :key="c.thread_id"
          :class="['item', { active: c.thread_id === chat.threadId }]"
          @click="open(c.thread_id)"
        >
          <span class="title">{{ c.title }}</span>
          <button class="del" title="删除" @click="remove(c.thread_id, $event)">×</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.convo-container {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  flex: none;
}

.search-box {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 10px;
  color: var(--text-dim);
  pointer-events: none;
}

.search-input {
  width: 100%;
  padding: 6px 10px 6px 32px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: var(--text);
  font-size: 13px;
  outline: none;
  transition: all 0.2s;
}

.search-input:focus {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.2);
}

.search-input::placeholder {
  color: var(--text-dim);
}

.toggle-btn {
  padding: 6px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: var(--text);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  flex: none;
}

.toggle-btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

.convo-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 4px 10px;
}
.empty {
  color: var(--text-dim);
  font-size: 13px;
  padding: 12px;
  text-align: center;
}
.group {
  margin-bottom: 6px;
}
.group-label {
  font-size: 12px;
  color: var(--text-dim);
  padding: 10px 8px 4px;
}
.item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 10px;
  border-radius: 10px;
  cursor: pointer;
  margin-bottom: 1px;
  transition: all 0.2s;
}
.item:hover {
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}
.item.active {
  background: rgba(255, 255, 255, 0.25);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.3);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}
.title {
  flex: 1;
  font-size: 13.5px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.item.active .title {
  color: var(--brand);
  font-weight: 500;
}
.del {
  flex: none;
  border: none;
  background: transparent;
  color: #c4c8d0;
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
  opacity: 0;
  transition: opacity 0.15s;
}
.item:hover .del {
  opacity: 1;
}
.del:hover {
  color: #e64545;
}
</style>
