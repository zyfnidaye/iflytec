import { defineStore } from 'pinia'
import {
  fetchTree,
  fetchFile,
  uploadFile,
  deleteWorkspaceFile,
  downloadWorkspaceFile,
  downloadWorkspaceSession,
} from '../api/client.js'

const ICON_MAP = {
  '.py': '🐍', '.js': '📜', '.ts': '📘', '.vue': '💚',
  '.html': '📄', '.css': '🎨', '.json': '📋', '.yaml': '📋', '.yml': '📋',
  '.md': '📝', '.txt': '📝', '.xml': '📰', '.csv': '📊',
  '.java': '☕', '.go': '🔵', '.rs': '🦀', '.sh': '💻',
}

function iconFor(name) {
  const ext = name.substring(name.lastIndexOf('.')).toLowerCase()
  return ICON_MAP[ext] || '📄'
}

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    files: [],        // 扁平列表 { name, path, icon }（兼容旧用法）
    sessions: [],     // [{ session, label, files: [{name, path, rel, icon, size}] }]
    treeLoaded: false,
    loading: false,
    preview: null,    // { name, path, icon, content } or null —— 点击文件树打开的模态预览
    livePreview: null, // { name, path, icon, content, done } or null —— agent 实时写文件的悬浮小窗
    status: '',
    uploading: false,
  }),

  actions: {
    /** 从后端加载文件列表，按会话分组 */
    async loadTree() {
      if (this.loading) return
      this.loading = true
      try {
        const data = await fetchTree()
        // 分组结构
        this.sessions = (data.sessions || []).map((g) => ({
          session: g.session,
          label: g.session === '_root' ? '未归类' : g.session,
          expanded: true,
          files: (g.files || []).map((f) => ({
            id: f.path,
            name: f.name,
            path: f.path,
            rel: f.rel,
            size: f.size,
            icon: iconFor(f.name),
            type: 'file',
          })),
        }))
        // 扁平列表（兼容）
        this.files = this.sessions.flatMap((g) => g.files)
        this.treeLoaded = true
      } catch (e) {
        this.status = '加载工作区失败: ' + e.message
      } finally {
        this.loading = false
      }
    },

    /** 下载单个文件 */
    downloadFile(file) {
      downloadWorkspaceFile(file.path)
    },

    /** 打包下载某个会话的全部文件 */
    downloadSession(session) {
      downloadWorkspaceSession(session)
    },

    /** 折叠/展开某个会话分组 */
    toggleSession(session) {
      const g = this.sessions.find((s) => s.session === session)
      if (g) g.expanded = !g.expanded
    },

    /** 打开文件预览 */
    async openPreview(file) {
      try {
        const data = await fetchFile(file.path)
        this.preview = {
          name: file.name,
          path: file.path,
          icon: file.icon,
          content: data.content,
        }
      } catch (e) {
        this.status = '读取文件失败: ' + e.message
      }
    },

    /** 实时预览：agent 写文件时后端推来内容，显示在悬浮小窗（不遮挡主界面） */
    showLivePreview(name, path, content) {
      this.livePreview = {
        name,
        path,
        icon: iconFor(name),
        content,
        done: false,
      }
    },

    /** 标记写入完成，悬浮小窗状态变为"已完成" */
    markLivePreviewDone() {
      if (this.livePreview) {
        this.livePreview.done = true
      }
    },

    closeLivePreview() {
      this.livePreview = null
    },

    closePreview() {
      this.preview = null
    },

    /** 上传文件到工作区 */
    async addFile(file) {
      this.uploading = true
      this.status = `添加中: ${file.name}...`
      try {
        await uploadFile(file)
        this.status = `已添加: ${file.name}`
        await this.loadTree()
      } catch (e) {
        this.status = '添加失败: ' + e.message
      } finally {
        this.uploading = false
      }
    },

    /** 删除工作区文件（兼容 RightDrawer 的 remove(id) 和 WorkspaceTree 的 removeFile(file)） */
    async remove(idOrFile) {
      // 兼容字符串 id 和对象 { path } 两种调用方式
      const id = typeof idOrFile === 'string' ? idOrFile : idOrFile?.path
      const file = this.files.find((f) => f.id === id || f.path === id)
      if (!file) {
        this.status = '文件不存在'
        return
      }
      this.status = `删除中: ${file.name}...`
      try {
        await deleteWorkspaceFile(file.path)
        this.files = this.files.filter((f) => f.path !== file.path)
        // 同步分组结构：从所属会话移除，会话空了则移除该组
        for (const g of this.sessions) {
          g.files = g.files.filter((f) => f.path !== file.path)
        }
        this.sessions = this.sessions.filter((g) => g.files.length > 0)
        if (this.preview?.path === file.path) {
          this.preview = null
        }
        this.status = `已删除: ${file.name}`
      } catch (e) {
        console.error('[workspace] delete error:', e)
        this.status = '删除失败: ' + e.message
      }
    },

    /** @deprecated 使用 remove(file) 代替 */
    async removeFile(file) {
      return this.remove(file)
    },
  },
})
