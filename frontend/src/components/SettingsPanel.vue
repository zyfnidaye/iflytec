<script setup>
import { usePanelStore } from '../stores/panel.js'
import { useSettingsStore } from '../stores/settings.js'

const panel = usePanelStore()
const settings = useSettingsStore()

function toggleSettings() {
  panel.togglePanel('settings')
}
</script>

<template>
  <button class="settings-trigger" @click="toggleSettings" title="背景设置">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="3"/>
      <path d="M12 1v6m0 6v6M5.6 5.6l4.2 4.2m4.2 4.2l4.2 4.2M1 12h6m6 0h6M5.6 18.4l4.2-4.2m4.2-4.2l4.2-4.2"/>
    </svg>
  </button>
</template>

<style scoped>
.settings-trigger {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  background: #40A9FF;
  color: #fff;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(64, 169, 255, 0.3);
}

.settings-trigger:hover {
  background: #1890FF;
  transform: rotate(45deg);
  box-shadow: 0 4px 12px rgba(64, 169, 255, 0.4);
}
</style>
