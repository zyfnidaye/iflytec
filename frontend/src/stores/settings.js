import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useSettingsStore = defineStore('settings', () => {
  const backgroundTheme = ref(localStorage.getItem('bg-theme') || 'solid')
  const customBgImage = ref(localStorage.getItem('bg-custom-image') || '')
  const solidColorId = ref(localStorage.getItem('bg-solid-color-id') || 'iflytek-blue')
  const solidColorValue = ref(localStorage.getItem('bg-solid-color-value') || '#40A9FF')

  function setBackgroundTheme(theme) {
    backgroundTheme.value = theme
    localStorage.setItem('bg-theme', theme)
    applyBackground()
  }

  function setCustomBackground(imageUrl) {
    customBgImage.value = imageUrl
    localStorage.setItem('bg-custom-image', imageUrl)
    if (backgroundTheme.value === 'custom') {
      applyBackground()
    }
  }

  function setSolidColor(colorId, colorValue) {
    solidColorId.value = colorId
    solidColorValue.value = colorValue
    localStorage.setItem('bg-solid-color-id', colorId)
    localStorage.setItem('bg-solid-color-value', colorValue)
    applyBackground()
  }

  function applyBackground() {
    const body = document.body
    body.className = '' // 清除之前的类

    if (backgroundTheme.value === 'custom' && customBgImage.value) {
      body.style.background = `url(${customBgImage.value}) center/cover fixed`
      body.style.animation = 'none'
    } else if (backgroundTheme.value === 'solid') {
      body.style.background = solidColorValue.value
      body.style.backgroundSize = ''
      body.style.animation = 'none'
    } else {
      body.style.backgroundImage = ''
      body.classList.add(`bg-${backgroundTheme.value}`)

      // 应用对应的背景
      const themes = {
        liquid: `
          radial-gradient(circle at 20% 50%, rgba(120, 119, 198, 0.3), transparent 50%),
          radial-gradient(circle at 80% 80%, rgba(253, 185, 155, 0.3), transparent 50%),
          radial-gradient(circle at 40% 20%, rgba(142, 199, 251, 0.3), transparent 50%),
          radial-gradient(circle at 60% 90%, rgba(210, 145, 188, 0.3), transparent 50%),
          linear-gradient(135deg, #667eea 0%, #764ba2 25%, #f093fb 50%, #f5576c 75%, #feca57 100%)
        `,
        ocean: `
          radial-gradient(circle at 20% 50%, rgba(56, 189, 248, 0.3), transparent 50%),
          radial-gradient(circle at 80% 80%, rgba(14, 165, 233, 0.3), transparent 50%),
          radial-gradient(circle at 40% 20%, rgba(59, 130, 246, 0.3), transparent 50%),
          linear-gradient(135deg, #0ea5e9 0%, #2563eb 50%, #7c3aed 100%)
        `,
        sunset: `
          radial-gradient(circle at 20% 50%, rgba(251, 146, 60, 0.3), transparent 50%),
          radial-gradient(circle at 80% 80%, rgba(239, 68, 68, 0.3), transparent 50%),
          radial-gradient(circle at 40% 20%, rgba(236, 72, 153, 0.3), transparent 50%),
          linear-gradient(135deg, #f97316 0%, #ef4444 50%, #ec4899 100%)
        `,
        forest: `
          radial-gradient(circle at 20% 50%, rgba(34, 197, 94, 0.3), transparent 50%),
          radial-gradient(circle at 80% 80%, rgba(20, 184, 166, 0.3), transparent 50%),
          radial-gradient(circle at 40% 20%, rgba(16, 185, 129, 0.3), transparent 50%),
          linear-gradient(135deg, #10b981 0%, #14b8a6 50%, #06b6d4 100%)
        `,
        aurora: `
          radial-gradient(circle at 20% 50%, rgba(139, 92, 246, 0.3), transparent 50%),
          radial-gradient(circle at 80% 80%, rgba(59, 130, 246, 0.3), transparent 50%),
          radial-gradient(circle at 40% 20%, rgba(168, 85, 247, 0.3), transparent 50%),
          linear-gradient(135deg, #8b5cf6 0%, #3b82f6 50%, #06b6d4 100%)
        `,
      }

      body.style.background = themes[backgroundTheme.value] || themes.liquid
      body.style.backgroundSize = '200% 200%'
      body.style.animation = 'liquidGradient 15s ease infinite'
    }
  }

  // 初始化时应用背景
  applyBackground()

  return {
    backgroundTheme,
    customBgImage,
    solidColorId,
    solidColorValue,
    setBackgroundTheme,
    setCustomBackground,
    setSolidColor,
  }
})
