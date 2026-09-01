<script setup>
// 可复用拖拽分隔条。orientation:
//   'col' —— 竖条，左右拖拽调宽度，emit delta.dx
//   'row' —— 横条，上下拖拽调高度，emit delta.dy
const props = defineProps({
  orientation: { type: String, default: 'col' },
})
const emit = defineEmits(['delta'])

function onPointerDown(e) {
  e.preventDefault()
  let lastX = e.clientX
  let lastY = e.clientY
  const prevUserSelect = document.body.style.userSelect
  const prevCursor = document.body.style.cursor
  document.body.style.userSelect = 'none'
  document.body.style.cursor = props.orientation === 'col' ? 'col-resize' : 'row-resize'

  const move = (ev) => {
    emit('delta', { dx: ev.clientX - lastX, dy: ev.clientY - lastY })
    lastX = ev.clientX
    lastY = ev.clientY
  }
  const up = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    document.body.style.userSelect = prevUserSelect
    document.body.style.cursor = prevCursor
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
}
</script>

<template>
  <div :class="['handle', orientation]" @pointerdown="onPointerDown"></div>
</template>

<style scoped>
.handle {
  flex: none;
  background: transparent;
  transition: background 0.15s;
  z-index: 5;
}
.handle:hover,
.handle:active {
  background: #2b5ce6;
}
.handle.col {
  width: 5px;
  cursor: col-resize;
  margin: 0 -2px;
}
.handle.row {
  height: 5px;
  cursor: row-resize;
  margin: -2px 0;
}
</style>
