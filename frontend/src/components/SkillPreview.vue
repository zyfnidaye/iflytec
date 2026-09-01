<script setup>
import { computed, ref } from 'vue'
import { useSkillsStore } from '../stores/skills.js'

const skills = useSkillsStore()
const copied = ref(false)

// 解析 YAML frontmatter 和正文
const parsedSkill = computed(() => {
  if (!skills.preview?.content) return null
  const text = skills.preview.content
  const yamlMatch = text.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/)
  if (!yamlMatch) {
    return { frontmatter: null, content: text }
  }
  return { frontmatter: yamlMatch[1].trim(), content: yamlMatch[2].trim() }
})

function lineCount(text) {
  return text ? text.split('\n').length : 0
}

async function copyContent() {
  if (!skills.preview?.content) return
  try {
    await navigator.clipboard.writeText(skills.preview.content)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = skills.preview.content
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  }
}
</script>

<template>
  <div v-if="skills.preview" class="mask" @click.self="skills.closePreview()">
    <div class="dialog">
      <div class="head">
        <span class="icon">🔧</span>
        <div class="head-info">
          <span class="title">{{ skills.preview.name }}</span>
          <span class="subtitle">{{ skills.preview.description || '技能' }}</span>
        </div>
        <button class="head-btn" @click="copyContent" :class="{ copied }">
          {{ copied ? '✓ 已复制' : '📋 复制' }}
        </button>
        <button class="head-btn close-btn" @click="skills.closePreview()">✕</button>
      </div>

      <div v-if="parsedSkill" class="body">
        <!-- Frontmatter 区 -->
        <div v-if="parsedSkill.frontmatter" class="section frontmatter-section">
          <div class="section-label">
            📋 元数据
            <span class="line-badge">{{ lineCount(parsedSkill.frontmatter) }} 行</span>
          </div>
          <pre class="section-text yaml">{{ parsedSkill.frontmatter }}</pre>
        </div>

        <!-- 正文区 -->
        <div v-if="parsedSkill.content" class="section content-section">
          <div class="section-label">
            📝 技能指令
            <span class="line-badge">{{ lineCount(parsedSkill.content) }} 行</span>
          </div>
          <pre class="section-text md">{{ parsedSkill.content }}</pre>
        </div>
      </div>

      <div v-else class="body">
        <div class="section content-section">
          <div class="section-label">
            全文
            <span class="line-badge">{{ lineCount(skills.preview.content) }} 行</span>
          </div>
          <pre class="section-text">{{ skills.preview.content || '（无内容）' }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  z-index: 2000;
}
.dialog {
  width: 100%;
  max-width: 960px;
  max-height: 85vh;
  background: #1e1e1e;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

/* ---- 头部 ---- */
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #252526;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  flex: none;
}
.icon { font-size: 20px; flex: none; }
.head-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.title {
  font-size: 14px;
  font-weight: 600;
  color: #cccccc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.subtitle {
  font-size: 11px;
  color: #888;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.head-btn {
  padding: 5px 14px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.06);
  color: #cccccc;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.head-btn:hover { background: rgba(255, 255, 255, 0.12); }
.head-btn.copied {
  background: rgba(64, 200, 128, 0.15);
  border-color: rgba(64, 200, 128, 0.3);
  color: #4ec990;
}
.close-btn {
  font-size: 16px;
  padding: 5px 10px;
  border: none;
  background: transparent;
}
.close-btn:hover {
  background: rgba(255, 80, 80, 0.2);
  color: #ff6b6b;
}

/* ---- 正文区 ---- */
.body {
  flex: 1;
  overflow: auto;
  background: #1e1e1e;
}

/* VSCode 风格滚动条 */
.body::-webkit-scrollbar { width: 10px; height: 10px; }
.body::-webkit-scrollbar-track { background: transparent; }
.body::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 5px;
  min-height: 30px;
}
.body::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.25); }

.section { padding: 20px 24px; }

.section-label {
  font-size: 11px;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.line-badge {
  font-size: 10px;
  font-weight: 500;
  color: #6e7681;
  background: rgba(255, 255, 255, 0.06);
  padding: 2px 8px;
  border-radius: 8px;
}

/* 元数据区（YAML） */
.frontmatter-section {
  background: rgba(74, 144, 226, 0.06);
  border-bottom: 2px solid rgba(74, 144, 226, 0.2);
}

/* 正文区 */
.content-section {
  background: transparent;
}

.section-text {
  margin: 0;
  padding: 16px 20px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.65;
  color: #e6edf3;
}
</style>
