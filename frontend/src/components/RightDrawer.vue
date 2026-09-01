<script setup>
import { computed, ref, nextTick } from 'vue'
import { usePanelStore } from '../stores/panel.js'
import { useKnowledgeStore } from '../stores/knowledge.js'
import KbDocItem from './KbDocItem.vue'
import { useSkillsStore } from '../stores/skills.js'
import { useWorkspaceStore } from '../stores/workspace.js'
import { useSettingsStore } from '../stores/settings.js'

const panel = usePanelStore()
const kb = useKnowledgeStore()
const skills = useSkillsStore()
const workspace = useWorkspaceStore()
const settings = useSettingsStore()

const fileInput = ref(null)
const urlInput = ref('')
const crawlMode = ref(false)

// 粘贴文本入库
const showPasteModal = ref(false)
const pasteText = ref('')
const pasteName = ref('')
const pasteInput = ref(null)

function openPasteModal() {
  pasteText.value = ''
  pasteName.value = ''
  showPasteModal.value = true
  nextTick(() => pasteInput.value?.focus())
}

async function submitPaste() {
  const text = pasteText.value.trim()
  if (!text) return
  const res = await kb.pasteText(text, pasteName.value.trim() || null)
  if (res) {
    showPasteModal.value = false
    pasteText.value = ''
    pasteName.value = ''
  }
}

// 飞书文档抓取
const showFeishuModal = ref(false)
const feishuUrl = ref('')
const feishuLoading = ref(false)
const feishuInput = ref(null)

function openFeishuModal() {
  feishuUrl.value = ''
  showFeishuModal.value = true
  nextTick(() => feishuInput.value?.focus())
}

async function submitFeishu() {
  const url = feishuUrl.value.trim()
  if (!url) return
  feishuLoading.value = true
  const res = await kb.fetchFeishuDoc(url)
  feishuLoading.value = false
  if (res) {
    showFeishuModal.value = false
    feishuUrl.value = ''
  }
}

const isOpen = computed(() => panel.activePanel !== null)

const title = computed(() => {
  switch (panel.activePanel) {
    case 'knowledge': return '📚 知识库'
    case 'skills': return '🔧 技能库'
    case 'workspace': return '📁 工作区'
    case 'settings': return '⚙️ 背景设置'
    default: return ''
  }
})

const themes = [
  { id: 'liquid', name: '液态彩虹', emoji: '🌈' },
  { id: 'ocean', name: '海洋蓝', emoji: '🌊' },
  { id: 'sunset', name: '日落橙', emoji: '🌅' },
  { id: 'forest', name: '森林绿', emoji: '🌲' },
  { id: 'aurora', name: '极光紫', emoji: '✨' },
  { id: 'custom', name: '自定义', emoji: '🎨' },
]

const solidColors = [
  { id: 'iflytek-blue', name: '讯飞蓝', color: '#40A9FF' },
  { id: 'red', name: '中国红', color: '#E74C3C' },
  { id: 'orange', name: '活力橙', color: '#F39C12' },
  { id: 'yellow', name: '明黄色', color: '#F1C40F' },
  { id: 'green', name: '翠绿色', color: '#27AE60' },
  { id: 'cyan', name: '青色', color: '#16A085' },
  { id: 'blue', name: '天空蓝', color: '#3498DB' },
  { id: 'indigo', name: '靛青蓝', color: '#5B6DCD' },
  { id: 'purple', name: '紫罗兰', color: '#9B59B6' },
  { id: 'pink', name: '樱花粉', color: '#E91E63' },
  { id: 'brown', name: '咖啡棕', color: '#8B6F47' },
  { id: 'gray', name: '高级灰', color: '#7F8C8D' },
  { id: 'black', name: '经典黑', color: '#2C3E50' },
  { id: 'white', name: '纯白色', color: '#ECF0F1' },
  { id: 'teal', name: '水鸭青', color: '#1ABC9C' },
  { id: 'lime', name: '柠檬绿', color: '#8BC34A' },
]

function selectTheme(themeId) {
  if (themeId === 'custom') {
    fileInput.value.click()
  } else {
    settings.setBackgroundTheme(themeId)
  }
}

function selectSolidColor(colorId, colorValue) {
  settings.setSolidColor(colorId, colorValue)
  settings.setBackgroundTheme('solid')
}

function handleImageUpload(e) {
  const file = e.target.files?.[0]
  if (!file) return

  const reader = new FileReader()
  reader.onload = (event) => {
    settings.setCustomBackground(event.target.result)
    settings.setBackgroundTheme('custom')
  }
  reader.readAsDataURL(file)
  e.target.value = ''
}

async function handleKbFileUpload(e) {
  const file = e.target.files?.[0]
  if (!file) return
  await kb.upload(file)
  e.target.value = ''
}

async function handleSkillFileUpload(e) {
  const files = e.target.files
  if (!files || files.length === 0) return

  // 上传所有文件（文件夹模式会传递多个文件）
  await skills.upload(files)
  e.target.value = ''
}

async function handleWorkspaceFileUpload(e) {
  const file = e.target.files?.[0]
  if (!file) return
  await workspace.addFile(file)
  e.target.value = ''
}

async function addUrl() {
  if (!urlInput.value.trim()) return
  await kb.addUrl(urlInput.value.trim(), crawlMode.value)
  urlInput.value = ''
}

async function handleDeleteSkill(name) {
  await skills.remove(name)
}

async function handleDeleteFile(id) {
  await workspace.remove(id)
}

// ===== 文件夹相关 =====

// 文件夹展开/折叠状态（默认全部展开）
const folderExpanded = ref({})
function toggleFolder(name) {
  folderExpanded.value[name] = folderExpanded.value[name] === false ? true : false
}
// 判断是否展开（默认 true）
const isFolderExpanded = (name) => folderExpanded.value[name] !== false

// 新建文件夹对话框
const showCreateFolder = ref(false)
const newFolderName = ref('')
const createFolderInput = ref(null)
function openCreateFolder() {
  showCreateFolder.value = true
  newFolderName.value = ''
  nextTick(() => createFolderInput.value?.focus())
}
async function submitCreateFolder() {
  const name = newFolderName.value.trim()
  if (!name) { showCreateFolder.value = false; return }
  try {
    await kb.createFolder(name)
    showCreateFolder.value = false
    newFolderName.value = ''
    folderExpanded.value[name] = true
  } catch { /* 状态已在 store 里提示 */ }
}

// 文件夹重命名
const editingFolderId = ref(null)
const editingFolderName = ref('')
const folderNameInput = ref(null)
function startFolderRename(id, name) {
  editingFolderId.value = id
  editingFolderName.value = name
  nextTick(() => {
    const el = Array.isArray(folderNameInput.value) ? folderNameInput.value[0] : folderNameInput.value
    el?.focus(); el?.select()
  })
}
function cancelFolderRename() {
  editingFolderId.value = null
  editingFolderName.value = ''
}
async function saveFolderRename(id) {
  const name = editingFolderName.value.trim()
  if (!name) { cancelFolderRename(); return }
  try {
    await kb.renameFolder(id, name)
  } catch { /* store 已提示 */ }
  cancelFolderRename()
}

async function handleDeleteFolder(folder) {
  if (folder.doc_count > 0) {
    kb.status = `❌ 文件夹「${folder.name}」非空，请先移出其中文档`
    return
  }
  if (!confirm(`确定删除空文件夹「${folder.name}」？`)) return
  await kb.removeFolder(folder.id)
}

// ===== 拖拽放置目标 =====
// 悬停高亮的目标（文件夹名 或 '__root__' 表示根目录区）
const dragOverTarget = ref(null)

function _readDrag(e) {
  try {
    return JSON.parse(e.dataTransfer.getData('application/x-kb-doc'))
  } catch { return null }
}

function onFolderDragOver(e, folderName) {
  e.preventDefault()
  e.dataTransfer.dropEffect = 'move'
  dragOverTarget.value = folderName
}

function onRootDragOver(e) {
  e.preventDefault()
  e.dataTransfer.dropEffect = 'move'
  dragOverTarget.value = '__root__'
}
function onDragLeaveTarget(target) {
  if (dragOverTarget.value === target) dragOverTarget.value = null
}

async function onDropToFolder(e, folderName) {
  e.preventDefault()
  _dbgOverCount = 0
  _probeCount = 0
  dragOverTarget.value = null
  const data = _readDrag(e)
  console.log('[drop→folder]', folderName, 'data=', data)
  if (!data) return
  if (data.fromFolder === folderName) return // 原地不动
  // 拖入文件夹后自动展开
  folderExpanded.value[folderName] = true
  await kb.moveToFolder(data.id, folderName)
}
async function onDropToRoot(e) {
  e.preventDefault()
  dragOverTarget.value = null
  const data = _readDrag(e)
  if (!data) return
  if (!data.fromFolder) return // 本来就在根目录
  await kb.moveToFolder(data.id, null)
}
</script>

<template>
  <div v-if="isOpen" class="drawer-overlay" :class="{ 'dnd-active': kb.dragDocId }" @click="panel.closePanel()">
    <div class="drawer" :class="{ 'dnd-active': kb.dragDocId }" @click.stop>
      <div class="drawer-header">
        <h3 class="drawer-title">{{ title }}</h3>
        <div class="header-actions">
          <!-- 知识库上传按钮 -->
          <button
            v-if="panel.activePanel === 'knowledge'"
            class="upload-btn"
            @click="$refs.kbFileInput.click()"
            title="上传文档"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
            </svg>
          </button>
          <!-- 飞书文档抓取按钮 -->
          <button
            v-if="panel.activePanel === 'knowledge'"
            class="upload-btn"
            @click="openFeishuModal()"
            title="抓取飞书文档"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>
            </svg>
          </button>
          <!-- 技能库上传按钮 -->
          <button
            v-if="panel.activePanel === 'skills'"
            class="upload-btn"
            @click="$refs.skillFileInput.click()"
            title="上传技能"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
            </svg>
          </button>
          <!-- 工作区上传按钮 -->
          <button
            v-if="panel.activePanel === 'workspace'"
            class="upload-btn"
            @click="$refs.workspaceFileInput.click()"
            title="添加文件"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
            </svg>
          </button>
          <button class="close-btn" @click="panel.closePanel()">✕</button>
        </div>
      </div>

      <input
        ref="kbFileInput"
        type="file"
        accept=".pdf,.docx,.doc,.txt,.md"
        @change="handleKbFileUpload"
        hidden
      />
      <input
        ref="skillFileInput"
        type="file"
        webkitdirectory
        directory
        multiple
        @change="handleSkillFileUpload"
        hidden
      />
      <input
        ref="workspaceFileInput"
        type="file"
        accept=".html,.css,.js,.json,.xml,.txt,.md"
        @change="handleWorkspaceFileUpload"
        hidden
      />

      <div class="drawer-content">
        <!-- 知识库内容 -->
        <div v-if="panel.activePanel === 'knowledge'" class="panel-body">
          <!-- 上传进度提示 -->
          <div v-if="kb.busy || kb.status" class="upload-status">
            <span v-if="kb.busy" class="loading-icon">⏳</span>
            <span class="status-text">{{ kb.status || '处理中...' }}</span>
            <button
              v-if="kb.status && !kb.busy"
              class="status-close-btn"
              @click="kb.status = ''"
              title="关闭"
            >✕</button>
          </div>

          <!-- URL 输入区 -->
          <div class="url-input-section">
            <input
              v-model="urlInput"
              type="text"
              class="url-input"
              placeholder="输入 URL 抓取网页内容..."
              @keyup.enter="addUrl"
            />
            <label class="crawl-toggle" title="开启整站爬取">
              <input type="checkbox" v-model="crawlMode" />
              <span>🕷️</span>
            </label>
            <button class="url-btn" @click="addUrl" :disabled="!urlInput.trim()" title="抓取">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
              </svg>
            </button>
          </div>

          <!-- 粘贴文本按钮 -->
          <button
            class="new-folder-btn"
            @click="openPasteModal"
            title="粘贴纯文本，subagent 自动整理成 markdown 结构入库"
            :disabled="kb.busy"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>
              <rect x="8" y="2" width="8" height="4" rx="1" ry="1"/>
            </svg>
            粘贴文本入库
          </button>

          <!-- 粘贴文本对话框 -->
          <div v-if="showPasteModal" class="modal-overlay" @click="showPasteModal = false">
            <div class="modal-box modal-box-wide" @click.stop>
              <div class="modal-title">粘贴文本入库</div>
              <div class="modal-hint">subagent 会自动把它整理成结构化 markdown。至少 20 字，最多 10 万字。</div>
              <input
                v-model="pasteName"
                class="modal-input"
                placeholder="文档名（留空则用首行/前30字自动命名）"
              />
              <textarea
                ref="pasteInput"
                v-model="pasteText"
                class="modal-textarea"
                placeholder="在此粘贴纯文本内容…"
                rows="12"
              ></textarea>
              <div class="modal-actions">
                <span class="modal-count">{{ pasteText.length }} 字</span>
                <button @click="showPasteModal = false" class="modal-btn-cancel" :disabled="kb.busy">取消</button>
                <button
                  @click="submitPaste"
                  :disabled="kb.busy || pasteText.trim().length < 20"
                  class="modal-btn-ok"
                >
                  {{ kb.busy ? '整理中…' : '入库' }}
                </button>
              </div>
            </div>
          </div>

          <!-- 飞书文档抓取弹窗 -->
          <div v-if="showFeishuModal" class="modal-overlay" @click="showFeishuModal = false">
            <div class="modal-box" @click.stop>
              <div class="modal-title">抓取飞书文档</div>
              <div class="modal-hint">输入飞书 wiki 链接，系统会递归拉取主文档及其子文档（一层）合并入库。</div>
              <input
                ref="feishuInput"
                v-model="feishuUrl"
                class="modal-input"
                placeholder="https://xxx.feishu.cn/wiki/xxxxx 或 node_token"
                @keyup.enter="submitFeishu"
              />
              <div class="modal-actions">
                <button @click="showFeishuModal = false" class="modal-btn-cancel" :disabled="feishuLoading">取消</button>
                <button
                  @click="submitFeishu"
                  :disabled="feishuLoading || !feishuUrl.trim()"
                  class="modal-btn-ok"
                >
                  {{ feishuLoading ? '抓取中…' : '开始抓取' }}
                </button>
              </div>
            </div>
          </div>

          <!-- 新建文件夹按钮 -->
          <button class="new-folder-btn" @click="openCreateFolder" title="新建文件夹">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
              <line x1="12" y1="11" x2="12" y2="17"/>
              <line x1="9" y1="14" x2="15" y2="14"/>
            </svg>
            新建文件夹
          </button>

          <!-- 新建文件夹对话框 -->
          <div v-if="showCreateFolder" class="modal-overlay" @click="showCreateFolder = false">
            <div class="modal-box" @click.stop>
              <div class="modal-title">新建文件夹</div>
              <input
                v-model="newFolderName"
                class="modal-input"
                placeholder="文件夹名称"
                @keyup.enter="submitCreateFolder"
                @keyup.esc="showCreateFolder = false"
                ref="createFolderInput"
              />
              <div class="modal-actions">
                <button @click="showCreateFolder = false" class="modal-btn-cancel">取消</button>
                <button @click="submitCreateFolder" :disabled="!newFolderName.trim()" class="modal-btn-ok">创建</button>
              </div>
            </div>
          </div>

          <!-- 文档列表：空态 + 文件夹块 + 根目录文档 -->
          <div v-if="kb.documents.length === 0 && kb.folders.length === 0" class="empty-state">
            <div class="empty-icon">📚</div>
            <div class="empty-text">暂无文档</div>
          </div>
          <div v-else class="doc-list" :class="{ 'dnd-active': kb.dragDocId }">
            <!-- 文件夹块（在上）——可作为拖拽放置目标 -->
            <div
              v-for="(item, idx) in kb.groupedDocs.folders"
              :key="item.folder.id"
              :data-folder-name="item.folder.name"
              class="folder-block"
              :class="{ 'drop-target': dragOverTarget === item.folder.name, 'dragging-active': kb.dragDocId }"
              @dragover="onFolderDragOver($event, item.folder.name)"
              @dragleave="onDragLeaveTarget(item.folder.name)"
              @drop.prevent="onDropToFolder($event, item.folder.name)"
            >
              <div class="folder-header" @click="toggleFolder(item.folder.name)">
                <span class="folder-icon">{{ isFolderExpanded(item.folder.name) ? '📂' : '📁' }}</span>
                <!-- 重命名模式 -->
                <input
                  v-if="editingFolderId === item.folder.id"
                  v-model="editingFolderName"
                  class="folder-name-input"
                  @keyup.enter="saveFolderRename(item.folder.id)"
                  @keyup.esc="cancelFolderRename"
                  @blur="saveFolderRename(item.folder.id)"
                  @click.stop
                  ref="folderNameInput"
                />
                <span v-else class="folder-name">{{ item.folder.name }}</span>
                <span class="folder-count">({{ item.docs.length }})</span>
                <div class="folder-actions">
                  <button
                    v-if="editingFolderId !== item.folder.id"
                    class="folder-btn"
                    @click.stop="startFolderRename(item.folder.id, item.folder.name)"
                    title="重命名文件夹"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                  </button>
                  <button class="folder-btn" @click.stop="handleDeleteFolder(item.folder)" title="删除文件夹">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                  </button>
                </div>
              </div>
              <!-- 文件夹内文档列表 -->
              <div v-show="isFolderExpanded(item.folder.name)" class="folder-docs">
                <KbDocItem v-for="d in item.docs" :key="d.id" :doc="d" />
              </div>
            </div>

            <!-- 根目录区（在下）——可作为放置目标，把文档从文件夹拖出到根 -->
            <div
              class="root-drop-zone"
              :class="{ 'drop-target': dragOverTarget === '__root__' }"
              @dragover="onRootDragOver"
              @dragleave="onDragLeaveTarget('__root__')"
              @drop="onDropToRoot"
            >
              <!-- 拖拽中且有文件夹时，显示移出提示 -->
              <div v-if="kb.dragDocId && kb.folders.length" class="root-drop-hint">
                拖到此处移出文件夹（放回根目录）
              </div>
              <KbDocItem v-for="d in kb.groupedDocs.root" :key="d.id" :doc="d" />
            </div>
          </div>
        </div>

        <!-- 技能库内容 -->
        <div v-if="panel.activePanel === 'skills'" class="panel-body">
          <!-- 上传进度提示 -->
          <div v-if="skills.uploading || skills.status" class="upload-status">
            <span v-if="skills.uploading" class="loading-icon">⏳</span>
            <span class="status-text">{{ skills.status || '上传中...' }}</span>
            <button
              v-if="skills.status && !skills.uploading"
              class="status-close-btn"
              @click="skills.status = ''"
              title="关闭"
            >✕</button>
          </div>

          <div v-if="skills.skills.length === 0" class="empty-state">
            <div class="empty-icon">🔧</div>
            <div class="empty-text">暂无技能</div>
          </div>
          <div v-else class="skill-list">
            <div
              v-for="skill in skills.skills"
              :key="skill.name"
              class="skill-item"
              @click="skills.openPreview(skill.name)"
            >
              <span class="skill-icon">🔧</span>
              <div class="skill-info">
                <div class="skill-name">{{ skill.name }}</div>
                <div class="skill-meta">{{ skill.description || '无描述' }}</div>
              </div>
              <button
                class="delete-btn"
                @click.stop="handleDeleteSkill(skill.name)"
                title="删除"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                </svg>
              </button>
            </div>
          </div>
        </div>

        <!-- 工作区内容 -->
        <div v-if="panel.activePanel === 'workspace'" class="panel-body">
          <!-- 状态提示 -->
          <div v-if="workspace.uploading || workspace.status" class="upload-status">
            <span v-if="workspace.uploading" class="loading-icon">⏳</span>
            <span class="status-text">{{ workspace.status || '处理中...' }}</span>
            <button
              v-if="workspace.status && !workspace.uploading"
              class="status-close-btn"
              @click="workspace.status = ''"
              title="关闭"
            >✕</button>
          </div>

          <div v-if="workspace.files.length === 0" class="empty-state">
            <div class="empty-icon">📁</div>
            <div class="empty-text">暂无文件</div>
          </div>
          <div v-else class="file-list">
            <div
              v-for="file in workspace.files"
              :key="file.id"
              class="file-item"
              @click="workspace.openPreview(file)"
            >
              <span class="file-icon">{{ file.icon }}</span>
              <div class="file-info">
                <div class="file-name">{{ file.name }}</div>
                <div class="file-meta">{{ file.type }}</div>
              </div>
              <button
                class="delete-btn"
                @click.stop="handleDeleteFile(file.id)"
                title="删除"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                </svg>
              </button>
            </div>
          </div>
        </div>

        <!-- 设置内容 -->
        <div v-if="panel.activePanel === 'settings'" class="panel-body">
          <!-- 渐变主题 -->
          <div class="settings-section">
            <h3 class="section-title">🌈 渐变主题</h3>
            <div class="theme-grid">
              <div
                v-for="theme in themes"
                :key="theme.id"
                class="theme-card"
                :class="{ active: settings.backgroundTheme === theme.id }"
                @click="selectTheme(theme.id)"
              >
                <span class="theme-emoji">{{ theme.emoji }}</span>
                <span class="theme-name">{{ theme.name }}</span>
                <span v-if="settings.backgroundTheme === theme.id" class="check-icon">✓</span>
              </div>
            </div>
          </div>

          <input
            ref="fileInput"
            type="file"
            accept="image/*"
            @change="handleImageUpload"
            hidden
          />

          <!-- 纯色背景 -->
          <div class="settings-section">
            <h3 class="section-title">🎨 纯色背景</h3>
            <div class="color-grid">
              <div
                v-for="color in solidColors"
                :key="color.id"
                class="color-card"
                :class="{ active: settings.backgroundTheme === 'solid' && settings.solidColorId === color.id }"
                :style="{ background: color.color }"
                @click="selectSolidColor(color.id, color.color)"
              >
                <div v-if="settings.backgroundTheme === 'solid' && settings.solidColorId === color.id" class="check-icon-color">✓</div>
                <div class="color-name">{{ color.name }}</div>
              </div>
            </div>
          </div>

          <div class="settings-tip">
            💡 选择渐变主题、纯色背景或上传图片来个性化界面
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.drawer-overlay {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex;
  justify-content: flex-end;
}

/* 拖拽进行时禁用抽屉外层/容器的 backdrop-filter：
   Chromium 下祖先的 backdrop-filter 合成层会拦截 HTML5 拖放的
   dragover/drop 命中，导致文件夹放置目标收不到事件、文档拖不进去。
   .doc-list 里只清了内部元素，这两层祖先才是最强的模糊源，必须一起清。 */
.drawer-overlay.dnd-active,
.drawer.dnd-active {
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

.drawer {
  width: 480px;
  max-width: 90vw;
  background: rgba(255, 255, 255, 0.2);
  backdrop-filter: blur(40px);
  -webkit-backdrop-filter: blur(40px);
  border-left: 1px solid rgba(255, 255, 255, 0.3);
  box-shadow: -4px 0 32px rgba(0, 0, 0, 0.15);
  display: flex;
  flex-direction: column;
  animation: slideIn 0.3s ease;
}

@keyframes slideIn {
  from {
    transform: translateX(100%);
  }
  to {
    transform: translateX(0);
  }
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  flex: none;
}

.drawer-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #1d1d1f;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.upload-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: #40A9FF;
  color: #fff;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}

.upload-btn:hover {
  background: #1890FF;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(64, 169, 255, 0.3);
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: rgba(0, 0, 0, 0.05);
  color: #1d1d1f;
  border-radius: 8px;
  font-size: 20px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-btn:hover {
  background: rgba(0, 0, 0, 0.1);
}

.drawer-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
}

.panel-body {
  min-height: 100%;
}

.upload-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: rgba(64, 169, 255, 0.1);
  border: 1px solid rgba(64, 169, 255, 0.3);
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 13px;
  color: #1d1d1f;
}

.loading-icon {
  font-size: 16px;
  animation: spin 2s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.status-text {
  flex: 1;
}

.status-text.error {
  color: #E74C3C;
}

.status-close-btn {
  background: none;
  border: none;
  color: #666;
  font-size: 16px;
  cursor: pointer;
  padding: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  transition: all 0.2s ease;
}

.status-close-btn:hover {
  background: rgba(0, 0, 0, 0.05);
  color: #333;
}

.url-input-section {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.url-input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.5);
  font-size: 13px;
  outline: none;
  transition: all 0.2s;
}

.url-input:focus {
  border-color: #40A9FF;
  background: rgba(255, 255, 255, 0.8);
}

.url-input::placeholder {
  color: #86868b;
}

.crawl-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid rgba(0, 0, 0, 0.1);
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
  flex: none;
}

.crawl-toggle:hover {
  background: rgba(255, 255, 255, 0.8);
}

.crawl-toggle input[type="checkbox"] {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.crawl-toggle input[type="checkbox"]:checked + span {
  filter: grayscale(0);
}

.crawl-toggle span {
  font-size: 18px;
  filter: grayscale(1);
  opacity: 0.5;
  transition: all 0.2s;
}

.crawl-toggle:has(input:checked) {
  background: rgba(64, 169, 255, 0.1);
  border-color: #40A9FF;
}

.crawl-toggle:has(input:checked) span {
  opacity: 1;
}

.url-btn {
  width: 36px;
  height: 36px;
  border: none;
  background: #40A9FF;
  color: #fff;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}

.url-btn:hover:not(:disabled) {
  background: #1890FF;
}

.url-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.empty-state {
  text-align: center;
  padding: 40px 24px;
}

.empty-icon {
  font-size: 48px;
  opacity: 0.3;
  margin-bottom: 12px;
}

.empty-text {
  font-size: 13px;
  color: #86868b;
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
/* 拖拽进行时禁用内部所有 backdrop-filter：
   Chromium 下祖先/兄弟的 backdrop-filter 合成层会干扰 HTML5 拖放的
   dragenter/dragover 命中，导致放置目标（文件夹）收不到事件、无法高亮。
   拖拽期间临时去掉模糊，松手后（dnd-active 移除）自动恢复。 */
.doc-list.dnd-active .doc-item,
.doc-list.dnd-active .folder-block,
.doc-list.dnd-active .folder-header {
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

/* ===== 文件夹块 ===== */
.new-folder-btn {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 12px; margin-bottom: 10px;
  background: rgba(255,255,255,0.35); border: 1px dashed rgba(148,163,184,0.5);
  border-radius: 10px; cursor: pointer; font-size: 13px; color: #475569;
  transition: all 0.2s; width: 100%;
}
.new-folder-btn:hover { background: rgba(59,130,246,0.08); border-color: #3b82f6; color: #3b82f6; }

.folder-block {
  border: 1px solid rgba(148,163,184,0.25);
  border-radius: 12px; overflow: hidden;
  background: rgba(255,255,255,0.15);
  transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
}
/* 拖拽进行中：文件夹块整体作为放置目标，加粗边界更好命中 */
.folder-block.dragging-active {
  border-style: dashed;
  border-color: rgba(59,130,246,0.4);
}
/* 拖拽时让文件夹头部不拦截 dragover，但保留 folder-docs 的交互（内部文档仍可拖） */
.folder-block.dragging-active .folder-header {
  pointer-events: none;
}
/* 拖拽悬停高亮：可放置态 */
.folder-block.drop-target {
  border-color: #3b82f6;
  border-style: dashed;
  background: rgba(59,130,246,0.15);
  box-shadow: 0 0 0 2px rgba(59,130,246,0.25);
}
/* 根目录放置区 */
.root-drop-zone {
  display: flex; flex-direction: column; gap: 8px;
  border-radius: 12px; transition: all 0.15s;
  min-height: 8px; /* 空根目录时也留一点可放置面积 */
}
.root-drop-zone.drop-target {
  background: rgba(59,130,246,0.08);
  box-shadow: 0 0 0 2px rgba(59,130,246,0.15) inset;
  padding: 6px;
}
.root-drop-hint {
  padding: 10px; text-align: center; font-size: 12.5px; color: #3b82f6;
  border: 1px dashed rgba(59,130,246,0.5); border-radius: 10px;
  background: rgba(59,130,246,0.04);
}
.folder-header {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; cursor: pointer; user-select: none;
  background: rgba(255,255,255,0.25); transition: background 0.2s;
}
.folder-header:hover { background: rgba(255,255,255,0.4); }
.folder-icon { font-size: 18px; flex: none; }
.folder-name { font-size: 14px; font-weight: 600; color: #1d1d1f; flex: 1; min-width: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.folder-name-input {
  flex: 1; font-size: 14px; font-weight: 600; padding: 3px 8px;
  border: 2px solid #007aff; border-radius: 6px; outline: none; background: rgba(255,255,255,0.95);
}
.folder-count { font-size: 12px; color: #94a3b8; flex: none; }
.folder-actions { display: flex; gap: 2px; opacity: 0; transition: opacity 0.2s; }
.folder-header:hover .folder-actions { opacity: 1; }
.folder-btn {
  border: none; background: transparent; color: #86868b; cursor: pointer;
  padding: 4px; border-radius: 6px; display: flex; align-items: center;
}
.folder-btn:hover { background: rgba(59,130,246,0.12); color: #3b82f6; }
.folder-docs {
  display: flex; flex-direction: column; gap: 6px;
  padding: 8px; padding-left: 16px;
}

/* ===== 新建文件夹对话框 ===== */
.modal-overlay {
  position: fixed; inset: 0; z-index: 100;
  background: rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center;
}
.modal-box {
  background: #fff; border-radius: 14px; padding: 20px; min-width: 300px;
  box-shadow: 0 12px 40px rgba(0,0,0,0.2);
}
.modal-title { font-size: 15px; font-weight: 600; color: #1d1d1f; margin-bottom: 14px; }
.modal-input {
  width: 100%; padding: 9px 12px; font-size: 14px; box-sizing: border-box;
  border: 1px solid #e2e8f0; border-radius: 8px; outline: none; margin-bottom: 16px;
}
.modal-input:focus { border-color: #3b82f6; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; }
.modal-btn-cancel, .modal-btn-ok {
  padding: 7px 16px; border-radius: 8px; font-size: 13px; cursor: pointer; border: none;
}
.modal-btn-cancel { background: #f1f5f9; color: #475569; }
.modal-btn-cancel:disabled { background: #f8fafc; color: #94a3b8; cursor: default; }
.modal-btn-ok { background: #3b82f6; color: #fff; }
.modal-btn-ok:disabled { background: #cbd5e1; cursor: default; }
.modal-box-wide { min-width: 480px; max-width: 640px; width: 90vw; }
.modal-hint {
  font-size: 12px; color: #64748b; margin-bottom: 12px; line-height: 1.5;
}
.modal-textarea {
  width: 100%; padding: 10px 12px; font-size: 13px; box-sizing: border-box;
  border: 1px solid #e2e8f0; border-radius: 8px; outline: none; margin-bottom: 12px;
  font-family: inherit; resize: vertical; line-height: 1.5;
  min-height: 200px; max-height: 400px;
}
.modal-textarea:focus { border-color: #3b82f6; }
.modal-count {
  flex: 1; font-size: 11px; color: #94a3b8; align-self: center;
}

.doc-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.3);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.doc-item:hover {
  background: rgba(255, 255, 255, 0.4);
  transform: translateX(-2px);
}

.doc-icon {
  font-size: 24px;
  flex: none;
}

.doc-info {
  flex: 1;
  min-width: 0;
}

.doc-name {
  font-size: 14px;
  color: #1d1d1f;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.doc-meta {
  font-size: 12px;
  color: #86868b;
}

.doc-meta.indexing {
  color: #c9a76e;
}

.doc-meta.failed {
  color: #c88a8a;
}

.doc-name-input {
  font-size: 14px;
  color: #1d1d1f;
  font-weight: 600;
  padding: 4px 8px;
  border: 2px solid #007aff;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.95);
  outline: none;
  margin-bottom: 4px;
  width: 100%;
}

.rename-btn {
  flex: none;
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: #86868b;
  cursor: pointer;
  border-radius: 8px;
  opacity: 0;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.doc-item:hover .rename-btn {
  opacity: 1;
}

.rename-btn:hover {
  background: rgba(0, 122, 255, 0.1);
  color: #007aff;
}

.delete-btn {
  flex: none;
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: #86868b;
  cursor: pointer;
  border-radius: 8px;
  opacity: 0;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.doc-item:hover .delete-btn {
  opacity: 1;
}

.skill-item:hover .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  background: rgba(255, 0, 0, 0.1);
  color: #e64545;
}

.skill-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.skill-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.3);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.skill-item:hover {
  background: rgba(255, 255, 255, 0.4);
  transform: translateX(-2px);
}

.skill-icon {
  font-size: 24px;
  flex: none;
}

.skill-info {
  flex: 1;
  min-width: 0;
}

.skill-name {
  font-size: 14px;
  color: #1d1d1f;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.skill-meta {
  font-size: 12px;
  color: #86868b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.3);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.file-item:hover {
  background: rgba(255, 255, 255, 0.4);
  transform: translateX(-2px);
}

.file-item:hover .delete-btn {
  opacity: 1;
}

.file-icon {
  font-size: 24px;
  flex: none;
}

.file-info {
  flex: 1;
  min-width: 0;
}

.file-name {
  font-size: 14px;
  color: #1d1d1f;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.file-meta {
  font-size: 12px;
  color: #86868b;
}

.settings-section {
  margin-bottom: 32px;
}

.section-title {
  margin: 0 0 16px 0;
  font-size: 16px;
  font-weight: 600;
  color: #1d1d1f;
}

.theme-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.theme-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.25);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}

.theme-card:hover {
  background: rgba(255, 255, 255, 0.35);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15);
}

.theme-card.active {
  background: rgba(255, 255, 255, 0.4);
  border-color: rgba(255, 255, 255, 0.5);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
}

.theme-emoji {
  font-size: 32px;
}

.theme-name {
  font-size: 13px;
  font-weight: 600;
  color: #1d1d1f;
}

.check-icon {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 24px;
  height: 24px;
  background: rgba(0, 122, 255, 0.9);
  color: #fff;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: bold;
}

.color-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.color-card {
  aspect-ratio: 1;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding: 8px;
  position: relative;
  border: 2px solid transparent;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.color-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
}

.color-card.active {
  border-color: rgba(255, 255, 255, 0.8);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.check-icon-color {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 24px;
  height: 24px;
  background: rgba(255, 255, 255, 0.9);
  color: #1d1d1f;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: bold;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.color-name {
  font-size: 11px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}

.settings-tip {
  padding: 16px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 12px;
  font-size: 13px;
  color: #1d1d1f;
  text-align: center;
  margin-top: 8px;
}
</style>
