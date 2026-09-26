function pad(value) {
  return String(value).padStart(2, '0')
}

export function formatEnergyTime(value) {
  if (value == null || value === '') {
    return '-'
  }
  if (Array.isArray(value) && value.length >= 3) {
    const y = value[0]
    const m = value[1] == null ? 1 : value[1]
    const d = value[2] == null ? 1 : value[2]
    const h = value[3] == null ? 0 : value[3]
    const i = value[4] == null ? 0 : value[4]
    const s = value[5] == null ? 0 : value[5]
    return y + '-' + pad(m) + '-' + pad(d) + ' ' + pad(h) + ':' + pad(i) + ':' + pad(s)
  }
  if (typeof value === 'string') {
    const trimmed = value.replace('T', ' ').replace(/\.\d+/, '')
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(trimmed)) {
      return trimmed.slice(0, 19)
    }
  }
  return String(value)
}
