import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchSkills, uploadSkill as apiUploadSkill, deleteSkill as apiDeleteSkill, fetchSkillContent } from '../api/client.js'

export const useSkillsStore = defineStore('skills', () => {
  const skills = ref([])
  const uploading = ref(false)
  const error = ref('')
  const status = ref('')
  const preview = ref(null) // 当前预览的技能

  async function loadList() {
    try {
      const data = await fetchSkills()
      skills.value = data.skills || []
    } catch (e) {
      status.value = '❌ 加载技能列表失败: ' + e.message
    }
  }

  async function upload(file) {
    uploading.value = true
    status.value = ''
    try {
      await apiUploadSkill(file)
      await loadList()
      status.value = '✅ 上传成功'
    } catch (e) {
      status.value = '❌ 上传失败: ' + e.message
    } finally {
      uploading.value = false
    }
  }

  async function remove(name) {
    status.value = ''
    try {
      await apiDeleteSkill(name)
      await loadList()
      status.value = '✅ 删除成功'
    } catch (e) {
      status.value = '❌ 删除失败: ' + e.message
    }
  }

  async function openPreview(name) {
    try {
      const skill = skills.value.find(s => s.name === name)
      if (!skill) return

      const data = await fetchSkillContent(name)
      preview.value = {
        name: skill.name,
        description: skill.description,
        content: data.content || '',
      }
    } catch (e) {
      error.value = '加载技能内容失败: ' + e.message
    }
  }

  function closePreview() {
    preview.value = null
  }

  return {
    skills,
    uploading,
    error,
    status,
    preview,
    loadList,
    upload,
    remove,
    openPreview,
    closePreview,
  }
})
