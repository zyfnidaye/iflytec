import { defineStore } from 'pinia'
import {
  uploadKnowledge,
  addKnowledgeUrl,
  pasteKnowledge,
  fetchFeishuDoc,
  fetchKnowledge,
  fetchKnowledgeDoc,
  updateKnowledgeDoc,
  replaceKnowledgeDoc,
  deleteKnowledge,
  fetchFolders,
  createFolder,
  renameFolder,
  deleteFolder,
  moveDocToFolder,
} from '../api/client.js'

export const useKnowledgeStore = defineStore('knowledge', {
  state: () => ({
    documents: [], // { id, name, source_type, ext, size, status, char_count, error, folder, created_at }
    folders: [], // { id, name, doc_count, created_at }
    dragDocId: null, // 正在拖拽的文档 id（供文件夹高亮可放置态）
    busy: false, // 上传/抓取进行中
    status: '', // 顶部状态提示
    preview: null, // { name, text, ... } 当前预览的文档
    editing: false, // 预览弹窗是否处于编辑态
    editText: '',   // 编辑中的正文草稿
    saving: false,  // 保存+重建向量进行中
    pollTimer: null, // 轮询定时器
  }),
  getters: {
    // 是否有正在处理的文档
    hasIndexing(state) {
      return state.documents.some(d => d.status === 'indexing')
    },
    // 文档按文件夹分组：返回 { folders: [{folder, docs}], root: [...] }
    // folders 来自 folders 表（保证空文件夹也显示），docs 按 folder 名匹配填入。
    groupedDocs(state) {
      const map = {}
      // 先用 folders 表建占位（空文件夹也要出现）
      state.folders.forEach(f => {
        map[f.name] = { folder: f, docs: [] }
      })
      const root = []
      state.documents.forEach(d => {
        if (d.folder && map[d.folder]) {
          map[d.folder].docs.push(d)
        } else {
          // 无 folder 或 folder 已不存在（孤儿）→ 放根目录
          root.push(d)
        }
      })
      // 文件夹块按 folders 表顺序（创建时间倒序）输出
      const folders = state.folders.map(f => map[f.name])
      return { folders, root }
    },
    // 所有文件夹名（供移动下拉选择器用）
    folderNames(state) {
      return state.folders.map(f => f.name)
    },
  },
  actions: {
    async loadList() {
      try {
        const data = await fetchKnowledge()
        this.documents = data.documents || []
        console.log('[Knowledge] loadList:', this.documents.length, 'docs, hasIndexing:', this.hasIndexing)
        // 同步拉取文件夹列表（含空文件夹）
        await this.loadFolders()
        // 如果有 indexing 文档，启动轮询
        this._startPollingIfNeeded()
      } catch {
        // 静默
      }
    },
    async loadFolders() {
      try {
        this.folders = await fetchFolders()
      } catch {
        // 静默失败，不阻塞文档列表
      }
    },
    async createFolder(name) {
      this.status = ''
      try {
        await createFolder(name)
        await this.loadFolders()
        this.status = `✅ 已创建文件夹：${name}`
      } catch (e) {
        this.status = '❌ ' + e.message
        throw e
      }
    },
    async renameFolder(folderId, newName) {
      this.status = ''
      try {
        await renameFolder(folderId, newName)
        await this.loadList() // 文档的 folder 字段也会变，整体刷新
        this.status = `✅ 文件夹已重命名为：${newName}`
      } catch (e) {
        this.status = '❌ ' + e.message
        throw e
      }
    },
    async removeFolder(folderId) {
      this.status = ''
      try {
        await deleteFolder(folderId)
        await this.loadFolders()
        this.status = '✅ 文件夹已删除'
      } catch (e) {
        this.status = '❌ ' + e.message
        throw e
      }
    },
    async moveToFolder(docId, folder) {
      this.status = ''
      try {
        await moveDocToFolder(docId, folder)
        await this.loadList()
        this.status = folder ? `✅ 已移动到：${folder}` : '✅ 已移出到根目录'
      } catch (e) {
        this.status = '❌ ' + e.message
        throw e
      }
    },
    _startPollingIfNeeded() {
      // 没有 indexing 文档时，停止轮询
      if (!this.hasIndexing) {
        if (this.pollTimer) {
          console.log('[Knowledge] Stopping poll timer (no indexing docs)')
          clearInterval(this.pollTimer)
          this.pollTimer = null
        }
        return
      }

      // 有 indexing 文档且还没有定时器，启动轮询
      if (!this.pollTimer) {
        console.log('[Knowledge] Starting poll timer (has indexing docs)')
        this.pollTimer = setInterval(async () => {
          console.log('[Knowledge] Poll tick...')
          await this.loadList()
        }, 5000)
      }
    },
    async upload(file) {
      this.busy = true
      this.status = `解析中：${file.name}…`
      try {
        const res = await uploadKnowledge(file)
        if (res.status === 'ready') {
          this.status = `✅ 已加入：${res.name}（${res.char_count} 字）${res.note ? ' · ' + res.note : ''}`
        } else if (res.status === 'indexing') {
          this.status = `⏳ 正在处理：${res.name}（${res.char_count} 字），后台生成摘要中...`
        } else {
          this.status = `❌ ${res.name} 解析失败：${res.error}`
        }
      } catch (e) {
        this.status = '❌ ' + e.message
      } finally {
        this.busy = false
        await this.loadList()
      }
    },
    async addUrl(url, crawl = false) {
      if (!url.trim()) return
      this.busy = true
      this.status = crawl ? `爬取整站中：${url}…（可能耗时）` : `抓取中：${url}…`
      try {
        const res = await addKnowledgeUrl(url.trim(), crawl)
        if (res.status === 'ready') {
          const pages = res.pages ? `，共 ${res.pages} 页` : ''
          this.status = `✅ 已抓取：${res.name}（${res.char_count} 字${pages}）`
        } else if (res.status === 'indexing') {
          const pages = res.pages ? `，共 ${res.pages} 页` : ''
          this.status = `⏳ 正在处理：${res.name}（${res.char_count} 字${pages}），后台生成摘要中...`
        } else {
          this.status = `❌ 抓取失败：${res.error}`
        }
      } catch (e) {
        this.status = '❌ ' + e.message
      } finally {
        this.busy = false
        await this.loadList()
      }
    },
    async pasteText(text, name = null) {
      if (!text || !text.trim()) return null
      this.busy = true
      this.status = '⏳ 整理中：subagent 正在结构化文本…'
      try {
        const res = await pasteKnowledge(text, name)
        if (res.note && res.note.includes('复用')) {
          this.status = `♻️ ${res.note}（${res.name}）`
        } else if (res.status === 'ready') {
          this.status = `✅ 已入库：${res.name}（${res.char_count} 字）`
        } else if (res.status === 'indexing') {
          this.status = `⏳ 正在处理：${res.name}（${res.char_count} 字）…`
        } else {
          this.status = `❌ 入库失败：${res.error || '未知错误'}`
        }
        return res
      } catch (e) {
        this.status = '❌ ' + e.message
        return null
      } finally {
        this.busy = false
        await this.loadList()
      }
    },
    async fetchFeishuDoc(url) {
      if (!url || !url.trim()) return null
      this.busy = true
      this.status = '⏳ 抓取中：正在拉取飞书文档及子文档…'
      try {
        const res = await fetchFeishuDoc(url)
        if (res.status === 'ready') {
          this.status = `✅ 已入库：${res.name}（${res.char_count} 字）`
        } else if (res.status === 'indexing') {
          this.status = `⏳ 正在处理：${res.name}（${res.char_count} 字）…`
        } else {
          this.status = `❌ 抓取失败：${res.error || '未知错误'}`
        }
        return res
      } catch (e) {
        this.status = '❌ ' + e.message
        return null
      } finally {
        this.busy = false
        await this.loadList()
      }
    },
    async replaceDoc(id, file) {
      this.busy = true
      this.status = `更新中：${file.name}…`
      try {
        const res = await replaceKnowledgeDoc(id, file)
        if (res.unchanged) {
          this.status = `内容未变化，无需更新`
        } else {
          this.status = `✅ 已更新（${res.char_count} 字）`
          if (this.preview && this.preview.id === id) this.preview = null
        }
      } catch (e) {
        this.status = '❌ 更新失败: ' + e.message
      } finally {
        this.busy = false
        await this.loadList()
      }
    },
    async remove(id) {
      this.status = ''
      try {
        await deleteKnowledge(id)
        if (this.preview && this.preview.id === id) this.preview = null
        await this.loadList()
        this.status = '✅ 删除成功'
      } catch (e) {
        this.status = '❌ 删除失败: ' + e.message
      }
    },
    async openPreview(id) {
      try {
        this.preview = await fetchKnowledgeDoc(id)
      } catch (e) {
        this.status = '❌ ' + e.message
      }
    },
    closePreview() {
      this.preview = null
      this.editing = false
      this.editText = ''
    },
    startEdit() {
      if (!this.preview) return
      this.editText = this.preview.text || ''
      this.editing = true
    },
    cancelEdit() {
      this.editing = false
      this.editText = ''
    },
    async saveEdit() {
      if (!this.preview || this.saving) return
      this.saving = true
      this.status = '⏳ 保存并重建向量索引中…'
      try {
        const res = await updateKnowledgeDoc(this.preview.id, this.editText)
        // 本地同步预览内容与字数，无需重新拉取
        this.preview = { ...this.preview, text: this.editText, char_count: res.char_count }
        this.editing = false
        this.editText = ''
        this.status = `✅ 已保存并更新向量库（${res.char_count} 字）`
        await this.loadList()
      } catch (e) {
        this.status = '❌ 保存失败: ' + e.message
      } finally {
        this.saving = false
      }
    },
    async updateName(docId, newName) {
      if (this.saving) return
      this.saving = true
      this.status = '⏳ 更新文档名称…'
      try {
        await updateKnowledgeDoc(docId, null, newName)
        // 如果当前有预览且是同一文档，同步更新预览
        if (this.preview && this.preview.id === docId) {
          this.preview = { ...this.preview, name: newName }
        }
        this.status = `✅ 文档名称已更新`
        await this.loadList()
      } catch (e) {
        this.status = '❌ 更新失败: ' + e.message
      } finally {
        this.saving = false
      }
    },
  },
})
