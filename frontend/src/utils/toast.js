/**
 * 显示成功提示（自动消失）
 */
export function showSuccess(message, duration = 2000) {
  const toast = document.createElement('div')
  toast.className = 'toast toast-success'
  toast.textContent = message
  document.body.appendChild(toast)

  // 触发动画
  setTimeout(() => toast.classList.add('show'), 10)

  // 自动移除
  setTimeout(() => {
    toast.classList.remove('show')
    setTimeout(() => document.body.removeChild(toast), 300)
  }, duration)
}

/**
 * 显示错误提示（需要手动关闭）
 */
export function showError(message) {
  alert('❌ ' + message)
}
