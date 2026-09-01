import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useKnowledgeStore } from './knowledge.js'
import { useSkillsStore } from './skills.js'
import { useWorkspaceStore } from './workspace.js'

export const usePanelStore = defineStore('panel', () => {
  const activePanel = ref(null) // 'knowledge' | 'skills' | 'workspace' | 'settings' | null

  function openPanel(panelName) {
    activePanel.value = panelName

    // 打开面板时清空错误状态
    if (panelName === 'knowledge') {
      const kb = useKnowledgeStore()
      kb.status = ''
    } else if (panelName === 'skills') {
      const skills = useSkillsStore()
      skills.status = ''
    } else if (panelName === 'workspace') {
      const workspace = useWorkspaceStore()
      workspace.status = ''
    }
  }

  function closePanel() {
    activePanel.value = null
  }

  function togglePanel(panelName) {
    if (activePanel.value === panelName) {
      closePanel()
    } else {
      openPanel(panelName)
    }
  }

  return {
    activePanel,
    openPanel,
    closePanel,
    togglePanel,
  }
})
