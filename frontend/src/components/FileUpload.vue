<script setup>
import { useKnowledgeStore } from '../stores/knowledge.js'
import { usePanelStore } from '../stores/panel.js'
import { onMounted } from 'vue'
import '../styles/panels.css'

const kb = useKnowledgeStore()
const panel = usePanelStore()

onMounted(() => {
  kb.loadList()
})

function togglePanel() {
  panel.togglePanel('knowledge')
}
</script>

<template>
  <div class="kb">
    <div class="panel-head">
      <span class="expand-icon" @click="togglePanel">{{ panel.activePanel === 'knowledge' ? '▼' : '▶' }}</span>
      <span class="panel-title" @click="togglePanel">📚 知识库</span>
      <span class="doc-count" @click="togglePanel">{{ kb.documents.length }}</span>
    </div>
  </div>
</template>

<style scoped>
.kb {
  display: flex;
  flex-direction: column;
  max-height: 100%;
  overflow: hidden;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.2);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  flex: none;
  border-radius: 14px;
  margin: 12px;
  user-select: none;
  border: 1px solid rgba(255, 255, 255, 0.3);
  cursor: pointer;
  transition: all 0.2s;
}

.panel-head:hover {
  background: rgba(255, 255, 255, 0.25);
}

.expand-icon {
  font-size: 10px;
  color: #1d1d1f;
  transition: transform 0.2s;
  width: 12px;
  font-weight: bold;
}

.panel-title {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: #1d1d1f;
}

.doc-count {
  font-size: 11px;
  font-weight: 600;
  color: #1d1d1f;
  background: rgba(255, 255, 255, 0.3);
  padding: 4px 12px;
  border-radius: 12px;
  backdrop-filter: blur(10px);
}
</style>
