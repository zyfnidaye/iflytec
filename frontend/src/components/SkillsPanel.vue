<script setup>
import { onMounted } from 'vue'
import { useSkillsStore } from '../stores/skills.js'
import { usePanelStore } from '../stores/panel.js'
import '../styles/panels.css'

const skills = useSkillsStore()
const panel = usePanelStore()

onMounted(() => {
  skills.loadList()
})

function togglePanel() {
  panel.togglePanel('skills')
}
</script>

<template>
  <div class="skills-panel">
    <div class="panel-head" @click="togglePanel">
      <span class="expand-icon">{{ panel.activePanel === 'skills' ? '▼' : '▶' }}</span>
      <span class="panel-title">🔧 技能库</span>
      <span class="skill-count">{{ skills.skills.length }}</span>
    </div>
  </div>
</template>

<style scoped>
.skills-panel {
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
  cursor: pointer;
  user-select: none;
  transition: all 0.2s;
  border: 1px solid rgba(255, 255, 255, 0.3);
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

.skill-count {
  font-size: 11px;
  font-weight: 600;
  color: #1d1d1f;
  background: rgba(255, 255, 255, 0.3);
  padding: 4px 12px;
  border-radius: 12px;
  backdrop-filter: blur(10px);
}
</style>
