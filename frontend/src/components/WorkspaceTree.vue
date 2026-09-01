<script setup>
import { onMounted } from 'vue'
import { usePanelStore } from '../stores/panel.js'
import { useWorkspaceStore } from '../stores/workspace.js'

const panel = usePanelStore()
const workspace = useWorkspaceStore()

onMounted(() => {
  workspace.loadTree()
})

function togglePanel() {
  panel.togglePanel('workspace')
  if (panel.activePanel === 'workspace' && !workspace.treeLoaded) {
    workspace.loadTree()
  }
}
</script>

<template>
  <div class="workspace-panel">
    <div class="panel-head" @click="togglePanel">
      <span class="expand-icon">{{ panel.activePanel === 'workspace' ? '▼' : '▶' }}</span>
      <span class="panel-title">📁 工作区</span>
      <span class="file-count">{{ workspace.files.length }}</span>
    </div>

    <!-- 展开时显示文件列表（按会话分组） -->
    <div v-if="panel.activePanel === 'workspace'" class="file-list">
      <div v-if="workspace.loading" class="status-text">加载中...</div>
      <div v-else-if="workspace.sessions.length === 0" class="status-text">（空）</div>

      <div v-for="group in workspace.sessions" :key="group.session" class="session-group">
        <div class="session-head">
          <span
            class="session-toggle"
            @click="workspace.toggleSession(group.session)"
          >{{ group.expanded ? '▼' : '▶' }}</span>
          <span class="session-label" :title="group.session">💬 {{ group.label }}</span>
          <span class="session-count">{{ group.files.length }}</span>
          <button
            class="zip-btn"
            title="打包下载该会话全部文件"
            @click.stop="workspace.downloadSession(group.session)"
          >⬇ zip</button>
        </div>

        <div v-if="group.expanded" class="session-files">
          <div
            v-for="file in group.files"
            :key="file.path"
            class="file-row"
            @click="workspace.openPreview(file)"
          >
            <span class="file-icon">{{ file.icon }}</span>
            <span class="file-name" :title="file.path">{{ file.rel }}</span>
            <button
              class="icon-btn"
              title="下载文件"
              @click.stop="workspace.downloadFile(file)"
            >⬇</button>
            <button
              class="icon-btn delete-btn"
              title="删除文件"
              @click.stop="workspace.removeFile(file)"
            >×</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 状态提示 -->
    <div v-if="workspace.status" class="status-bar">{{ workspace.status }}</div>
  </div>
</template>

<style scoped>
.workspace-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
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

.file-count {
  font-size: 11px;
  font-weight: 600;
  color: #1d1d1f;
  background: rgba(255, 255, 255, 0.3);
  padding: 4px 12px;
  border-radius: 12px;
}

.file-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 16px 12px;
}

.session-group {
  margin-bottom: 6px;
}

.session-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: default;
  user-select: none;
}
.session-head:hover {
  background: rgba(255, 255, 255, 0.12);
}
.session-toggle {
  font-size: 9px;
  color: #6b6b6f;
  cursor: pointer;
  width: 12px;
  flex: none;
}
.session-label {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  color: #48484a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-count {
  font-size: 10px;
  color: #86868b;
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 7px;
  border-radius: 8px;
  flex: none;
}
.zip-btn {
  border: none;
  background: rgba(74, 124, 255, 0.12);
  color: var(--brand, #4a7cff);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  cursor: pointer;
  flex: none;
  transition: background 0.15s;
}
.zip-btn:hover {
  background: rgba(74, 124, 255, 0.22);
}
.session-files {
  padding-left: 6px;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}

.file-row:hover {
  background: rgba(255, 255, 255, 0.2);
}

.file-icon {
  font-size: 16px;
  flex: none;
}

.file-name {
  flex: 1;
  font-size: 13px;
  color: #1d1d1f;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.icon-btn {
  opacity: 0.5;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: #86868b;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
}
.icon-btn:hover {
  opacity: 1;
  background: rgba(74, 124, 255, 0.18);
  color: var(--brand, #4a7cff);
}
.delete-btn:hover {
  opacity: 1;
  background: rgba(230, 69, 69, 0.2);
  color: #e64545;
}

.status-text {
  font-size: 12px;
  color: var(--text-dim);
  padding: 12px 16px;
}

.status-bar {
  font-size: 11px;
  color: var(--text-dim);
  padding: 8px 16px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}
</style>
