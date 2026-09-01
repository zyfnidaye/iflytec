// 后端 API 封装。/api 已由 vite 代理到后端。

// 上传链路图文件
export async function uploadFile(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/upload', { method: 'POST', body: form })
  if (!res.ok) throw new Error((await res.json()).detail || '上传失败')
  return res.json()
}

// 工作区文件树
export async function fetchTree() {
  const res = await fetch('/api/workspace/tree')
  return res.json()
}

// 读取工作区单个文件
export async function fetchFile(path) {
  const res = await fetch('/api/workspace/file?path=' + encodeURIComponent(path))
  if (!res.ok) throw new Error('读取失败')
  return res.json()
}

// 下载工作区单个文件（浏览器直接触发下载）
export function downloadWorkspaceFile(path) {
  const url = '/api/workspace/download?path=' + encodeURIComponent(path)
  triggerDownload(url)
}

// 打包下载某个会话的全部文件（zip）
export function downloadWorkspaceSession(session) {
  const url = '/api/workspace/download-session?session=' + encodeURIComponent(session)
  triggerDownload(url)
}

// 用隐藏 <a> 触发浏览器下载，避免 fetch 后手动处理 blob
function triggerDownload(url) {
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

// 删除工作区文件
export async function deleteWorkspaceFile(path) {
  const url = '/api/workspace/file?path=' + encodeURIComponent(path)
  console.log('[client] DELETE', url)
  const res = await fetch(url, { method: 'DELETE' })
  console.log('[client] DELETE response:', res.status, res.ok)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || '删除失败')
  }
  return res.json()
}

// ===== 知识库 =====

// 上传文档到知识库
export async function uploadKnowledge(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/knowledge/upload', { method: 'POST', body: form })
  if (!res.ok) throw new Error((await res.json()).detail || '上传失败')
  return res.json()
}

// 抓取网页 URL 存入知识库。crawl=true 时递归抓取多页文档站
export async function addKnowledgeUrl(url, crawl = false) {
  const res = await fetch('/api/knowledge/url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, crawl }),
  })
  if (!res.ok) throw new Error((await res.json()).detail || '抓取失败')
  return res.json()
}

// 粘贴文本入库（后端用 subagent 自动整理成 markdown 结构）
export async function pasteKnowledge(text, name = null) {
  const body = { text }
  if (name && name.trim()) body.name = name.trim()
  const res = await fetch('/api/knowledge/paste', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error((await res.json()).detail || '粘贴入库失败')
  return res.json()
}

// 抓取飞书文档（递归拉取主文档+子文档合并入库）
export async function fetchFeishuDoc(url) {
  const res = await fetch('/api/knowledge/feishu', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) throw new Error((await res.json()).detail || '抓取飞书文档失败')
  return res.json()
}

// 知识库文档列表
export async function fetchKnowledge() {
  const res = await fetch('/api/knowledge')
  if (!res.ok) throw new Error('获取知识库失败')
  return res.json()
}

// 单个文档（含解析正文）
export async function fetchKnowledgeDoc(id) {
  const res = await fetch('/api/knowledge/' + id)
  if (!res.ok) throw new Error('获取文档失败')
  return res.json()
}

// 编辑文档正文（保存后端会重建向量索引）
export async function updateKnowledgeDoc(id, text = null, name = null) {
  const body = {}
  if (text !== null) body.text = text
  if (name !== null) body.name = name

  const res = await fetch('/api/knowledge/' + id, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '保存失败')
  }
  return res.json()
}

// 用新文件替换已有文档内容（保持同一 doc_id，后端同步重建向量索引）
export async function replaceKnowledgeDoc(id, file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/knowledge/' + id + '/replace', { method: 'POST', body: form })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '更新失败')
  }
  return res.json()
}

// 删除文档
export async function deleteKnowledge(id) {
  const res = await fetch('/api/knowledge/' + id, { method: 'DELETE' })
  if (!res.ok) throw new Error('删除失败')
  return res.json()
}

// ===== 知识库文件夹 =====

// 列出所有文件夹（含文档数）
export async function fetchFolders() {
  const res = await fetch('/api/knowledge/folders')
  if (!res.ok) throw new Error('获取文件夹失败')
  return res.json()
}

// 创建空文件夹
export async function createFolder(name) {
  const res = await fetch('/api/knowledge/folders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  if (!res.ok) throw new Error((await res.json()).detail || '创建文件夹失败')
  return res.json()
}

// 重命名文件夹（后端同步更新其下所有文档）
export async function renameFolder(folderId, newName) {
  const res = await fetch('/api/knowledge/folders/' + folderId, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_name: newName }),
  })
  if (!res.ok) throw new Error((await res.json()).detail || '重命名失败')
  return res.json()
}

// 删除空文件夹（非空会被后端拒绝）
export async function deleteFolder(folderId) {
  const res = await fetch('/api/knowledge/folders/' + folderId, { method: 'DELETE' })
  if (!res.ok) throw new Error((await res.json()).detail || '删除文件夹失败')
  return res.json()
}

// 移动文档到文件夹（folder 传 null = 移回根目录；文件夹不存在时后端自动创建）
export async function moveDocToFolder(docId, folder) {
  const res = await fetch('/api/knowledge/' + docId + '/folder', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ folder }),
  })
  if (!res.ok) throw new Error((await res.json()).detail || '移动失败')
  return res.json()
}

// Embedding 模型
export async function fetchEmbeddingModel() {
  const res = await fetch('/api/knowledge/embedding-model')
  if (!res.ok) throw new Error('获取模型信息失败')
  return res.json()
}

export async function switchEmbeddingModel(model) {
  const res = await fetch('/api/knowledge/embedding-model', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model }),
  })
  if (!res.ok) throw new Error('切换模型失败')
  return res.json()
}

// 会话列表
export async function fetchConversations() {
  const res = await fetch('/api/conversations')
  if (!res.ok) throw new Error('获取会话列表失败')
  return res.json()
}

// 某个会话的历史消息
export async function fetchConversationMessages(threadId) {
  const res = await fetch('/api/conversations/' + encodeURIComponent(threadId))
  if (!res.ok) throw new Error('获取会话历史失败')
  return res.json()
}

// 删除会话
export async function deleteConversation(threadId) {
  const res = await fetch('/api/conversations/' + encodeURIComponent(threadId), {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error('删除会话失败')
  return res.json()
}

// 流式对话。handlers: { onToken, onTool, onDone, onError }
export async function streamChat({ message, threadId, imageDataUrls = [], useKnowledge = true, forceRetrieval = false, useWeb = false, signal }, handlers) {
  console.log('[streamChat] Starting request...')
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({
      message,
      thread_id: threadId,
      image_data_urls: imageDataUrls,
      use_knowledge: useKnowledge,
      force_retrieval: forceRetrieval,
      use_web: useWeb,
    }),
  })
  console.log('[streamChat] Response status:', res.status, 'ok:', res.ok, 'body:', !!res.body)
  if (!res.ok || !res.body) {
    handlers.onError?.('请求失败: ' + res.status)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        console.log('[streamChat] Stream ended')
        break
      }

      // 立即解码，减少缓冲
      const chunk = decoder.decode(value, { stream: true })
      console.log('[streamChat] Received chunk:', chunk.length, 'bytes')
      buffer += chunk

      // SSE 事件以 \n\n 分隔，逐个处理
      let boundary
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const eventChunk = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)

        let event = 'message'
        let data = ''
        for (const line of eventChunk.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) data += line.slice(5).trim()
        }
        if (!data) continue

        console.log('[streamChat] Parsed event:', event, 'data length:', data.length)

        let payload
        try {
          payload = JSON.parse(data)
        } catch (e) {
          console.error('[streamChat] JSON parse error:', e, 'data:', data)
          continue
        }

        if (event === 'token') handlers.onToken?.(payload.text)
        else if (event === 'tool') handlers.onTool?.(payload)
        else if (event === 'tool_done') handlers.onToolDone?.(payload)
        else if (event === 'citations') handlers.onCitations?.(payload)
        // 子助手（subagent 工厂）内部工具事件：透传给前端，渲染为缩进的子条目
        else if (event === 'subagent_tool') handlers.onSubagentTool?.(payload)
        else if (event === 'subagent_tool_done') handlers.onSubagentToolDone?.(payload)
        else if (event === 'subagent_text') handlers.onSubagentText?.(payload)
        else if (event === 'file_written') handlers.onFileWritten?.(payload)
        else if (event === 'artifact_update') handlers.onArtifactUpdate?.(payload)
        else if (event === 'warning') handlers.onWarning?.(payload.message)
        else if (event === 'interrupted') handlers.onInterrupted?.()
        else if (event === 'done') handlers.onDone?.()
        else if (event === 'error') handlers.onError?.(payload.message)
        // 预留方案A：Extended Thinking 事件
        else if (event === 'thinking_start') handlers.onThinkingStart?.()
        else if (event === 'thinking') handlers.onThinking?.(payload.text)
        else if (event === 'thinking_end') handlers.onThinkingEnd?.()
      }
    }
  } catch (err) {
    // 用户主动中断（AbortController.abort()）：不是错误，交给 onInterrupted 处理
    if (err.name === 'AbortError') {
      console.log('[streamChat] Aborted by user')
      handlers.onInterrupted?.()
      return
    }
    console.error('[streamChat] Error:', err)
    handlers.onError?.('连接中断: ' + err.message)
  }
}

// ===== Skills =====

// 技能列表
export async function fetchSkills() {
  const res = await fetch('/api/skills')
  if (!res.ok) throw new Error('获取技能列表失败')
  return res.json()
}

// 获取技能内容
export async function fetchSkillContent(name) {
  const res = await fetch('/api/skills/' + encodeURIComponent(name))
  if (!res.ok) throw new Error('获取技能内容失败')
  return res.json()
}

// 上传技能（zip 或 SKILL.md 或文件夹）
export async function uploadSkill(fileOrFiles) {
  const form = new FormData()

  // 支持单个文件或 FileList
  if (fileOrFiles instanceof FileList || Array.isArray(fileOrFiles)) {
    // 多个文件（文件夹模式）
    for (const file of fileOrFiles) {
      form.append('files', file)
    }
  } else {
    // 单个文件
    form.append('files', fileOrFiles)
  }

  const res = await fetch('/api/skills/upload', { method: 'POST', body: form })
  if (!res.ok) throw new Error((await res.json()).detail || '上传失败')
  return res.json()
}

// 删除技能
export async function deleteSkill(name) {
  const res = await fetch('/api/skills/' + encodeURIComponent(name), { method: 'DELETE' })
  if (!res.ok) throw new Error('删除失败')
  return res.json()
}
