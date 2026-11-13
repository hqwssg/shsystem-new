export function applyTheme(color) {
  if (!/^#[0-9a-f]{6}$/i.test(color)) return
  const channels = [1, 3, 5].map(i => parseInt(color.slice(i, i + 2), 16))
  const mix = (target, amount) => '#' + channels.map(c => Math.round(c + (target - c) * amount).toString(16).padStart(2, '0')).join('')
  const style = document.documentElement.style
  style.setProperty('--el-color-primary', color)
  for (const n of [3, 5, 7, 8, 9]) style.setProperty(`--el-color-primary-light-${n}`, mix(255, n / 10))
  style.setProperty('--el-color-primary-dark-2', mix(0, 0.2))
}
