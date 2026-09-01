<template>
  <div v-if="artifact" class="artifact-panel">
    <div class="artifact-header">
      <h3>{{ artifact.title }}</h3>
      <button class="close-btn" @click="$emit('close')" title="关闭预览">✕</button>
    </div>
    <div class="artifact-content">
      <div v-if="artifact.type === 'markdown'" class="markdown-preview" v-html="renderedMarkdown"></div>
      <pre v-else-if="artifact.type === 'code'" class="code-preview"><code>{{ artifact.content }}</code></pre>
      <div v-else-if="artifact.type === 'html'" v-html="artifact.content" class="html-preview"></div>
      <div v-else class="text-preview">{{ artifact.content }}</div>
    </div>
    <div class="artifact-footer">
      <span class="content-size">{{ contentSize }}</span>
      <button class="copy-btn" @click="copyContent" title="复制内容">📋 复制</button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps({
  artifact: Object, // { id, title, type, content }
})

defineEmits(['close'])

const renderedMarkdown = computed(() => {
  if (props.artifact?.type === 'markdown' && props.artifact.content) {
    try {
      return marked.parse(props.artifact.content)
    } catch (e) {
      console.error('[Artifact] Markdown render error:', e)
      return '<pre>' + props.artifact.content + '</pre>'
    }
  }
  return ''
})

const contentSize = computed(() => {
  const len = props.artifact?.content?.length || 0
  if (len < 1024) return `${len} 字符`
  return `${(len / 1024).toFixed(1)} KB`
})

function copyContent() {
  if (!props.artifact?.content) return
  navigator.clipboard.writeText(props.artifact.content).then(() => {
    alert('已复制到剪贴板')
  }).catch(err => {
    console.error('[Artifact] Copy failed:', err)
    alert('复制失败')
  })
}
</script>

<style scoped>
.artifact-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: white;
  border-left: 1px solid #e0e0e0;
}

.artifact-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #e0e0e0;
  background: #f8f9fa;
}

.artifact-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #333;
}

.close-btn {
  background: none;
  border: none;
  font-size: 20px;
  color: #666;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.2s;
}

.close-btn:hover {
  background: #e0e0e0;
}

.artifact-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.markdown-preview {
  line-height: 1.6;
  color: #333;
}

.markdown-preview :deep(h1) {
  font-size: 24px;
  margin-top: 0;
  margin-bottom: 16px;
  border-bottom: 1px solid #e0e0e0;
  padding-bottom: 8px;
}

.markdown-preview :deep(h2) {
  font-size: 20px;
  margin-top: 24px;
  margin-bottom: 12px;
}

.markdown-preview :deep(h3) {
  font-size: 16px;
  margin-top: 20px;
  margin-bottom: 10px;
}

.markdown-preview :deep(code) {
  background: #f5f5f5;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 14px;
}

.markdown-preview :deep(pre) {
  background: #f5f5f5;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
}

.markdown-preview :deep(pre code) {
  background: none;
  padding: 0;
}

.code-preview, .text-preview {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 14px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.html-preview {
  line-height: 1.6;
}

.artifact-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-top: 1px solid #e0e0e0;
  background: #f8f9fa;
}

.content-size {
  font-size: 13px;
  color: #666;
}

.copy-btn {
  padding: 6px 12px;
  font-size: 13px;
  background: white;
  border: 1px solid #d0d0d0;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.copy-btn:hover {
  background: #f0f0f0;
  border-color: #b0b0b0;
}
</style>
