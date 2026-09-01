<script setup>
import { ref, computed } from 'vue'
import { useChatStore } from '../stores/chat.js'

const chat = useChatStore()
const searchQuery = ref('')

const emit = defineEmits(['close'])

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

// 按时间分组
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
  emit('close')
}

async function remove(threadId, e) {
  e.stopPropagation()
  if (!confirm('删除这个会话？')) return
  await chat.removeConversation(threadId)
}
</script>

<template>
  <div class="search-panel">
    <div class="search-header">
      <div class="search-box">
        <svg class="search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/>
          <path d="m21 21-4.35-4.35"/>
        </svg>
        <input
          v-model="searchQuery"
          type="text"
          class="search-input"
          placeholder="搜索对话..."
          autofocus
        />
      </div>
      <button class="close-btn" @click="emit('close')" title="关闭">
        ✕
      </button>
    </div>

    <div class="search-results">
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
.search-panel {
  position: fixed;
  left: 56px;
  top: 0;
  bottom: 0;
  width: 320px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-right: 1px solid rgba(255, 255, 255, 0.3);
  display: flex;
  flex-direction: column;
  z-index: 99;
  box-shadow: 2px 0 24px rgba(0, 0, 0, 0.1);
}

.search-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.1);
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
  left: 12px;
  color: #999;
  pointer-events: none;
}

.search-input {
  width: 100%;
  padding: 10px 12px 10px 40px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 10px;
  color: #1d1d1f;
  font-size: 14px;
  outline: none;
  transition: all 0.2s;
}

.search-input:focus {
  background: #fff;
  border-color: rgba(64, 169, 255, 0.5);
  box-shadow: 0 0 0 3px rgba(64, 169, 255, 0.1);
}

.search-input::placeholder {
  color: #999;
}

.close-btn {
  padding: 8px;
  background: rgba(0, 0, 0, 0.05);
  border: none;
  border-radius: 8px;
  color: #666;
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
  transition: all 0.2s;
  flex: none;
}

.close-btn:hover {
  background: rgba(0, 0, 0, 0.1);
  color: #333;
}

.search-results {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
}

.empty {
  color: #999;
  font-size: 13px;
  padding: 24px 12px;
  text-align: center;
}

.group {
  margin-bottom: 8px;
}

.group-label {
  font-size: 12px;
  color: #999;
  padding: 10px 8px 4px;
  font-weight: 500;
}

.item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  margin-bottom: 2px;
  transition: all 0.15s;
  background: rgba(255, 255, 255, 0.5);
}

.item:hover {
  background: rgba(64, 169, 255, 0.1);
}

.item.active {
  background: rgba(64, 169, 255, 0.15);
}

.title {
  flex: 1;
  font-size: 13px;
  color: #1d1d1f;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.del {
  flex: none;
  width: 20px;
  height: 20px;
  border-radius: 6px;
  border: none;
  background: rgba(0, 0, 0, 0.05);
  color: #999;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: all 0.15s;
}

.item:hover .del {
  opacity: 1;
}

.del:hover {
  background: rgba(231, 76, 60, 0.1);
  color: #E74C3C;
}
</style>
