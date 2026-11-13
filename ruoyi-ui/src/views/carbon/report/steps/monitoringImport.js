import * as XLSX from 'xlsx'

export const monitoringFields = [
  { key: 'name', label: '名称', max: 255, aliases: ['名称', 'name'] },
  { key: 'model', label: '型号', max: 128, aliases: ['型号', 'model'] },
  { key: 'accuracy', label: '精度', max: 64, aliases: ['精度', 'accuracy'] },
  { key: 'measurementRange', label: '量程', max: 64, aliases: ['量程', 'measurement_range', 'measurementRange'] },
  { key: 'location', label: '安装位置', max: 255, aliases: ['位置', '安装位置', 'location'] },
  { key: 'calibrationFrequency', label: '检定周期', max: 64, aliases: ['规定校准频次', '检定周期', 'calibration_frequency', 'calibrationFrequency'] }
]
const text = value => value == null ? '' : String(value)
const hasContent = row => monitoringFields.some(field => text(row[field.key]).trim())

export function monitoringWarnings(rows) {
  const groups = new Map()
  rows.forEach((row, index) => {
    if (!hasContent(row)) return
    const key = JSON.stringify(monitoringFields.map(field => text(row[field.key]).trim()))
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(index + 1)
  })
  return rows.map((row, index) => {
    const messages = [], errors = []
    if (hasContent(row) && !text(row.name).trim()) messages.push('名称未填写，请核对')
    const key = JSON.stringify(monitoringFields.map(field => text(row[field.key]).trim()))
    const matches = groups.get(key) || []
    if (matches.length > 1) messages.push('内容与第' + matches.filter(n => n !== index + 1).join('、') + '行相同，请核对')
    monitoringFields.forEach(field => {
      if (Array.from(text(row[field.key])).length > field.max) errors.push(field.label + '超过' + field.max + '字，保存前请缩短')
    })
    return { messages: [...messages, ...errors], errors }
  })
}

export function mergeMonitoringRows(current, incoming, mode) {
  if (!['append', 'overwrite'].includes(mode)) throw new Error('导入方式不正确')
  const rows = mode === 'overwrite' ? incoming : [...current, ...incoming]
  return rows.map(row => ({ ...row }))
}

export function parseMonitoringWorkbook(book) {
  const sheet = book.Sheets[book.SheetNames[0]]
  if (!sheet) throw new Error('Excel中没有工作表')
  const cells = XLSX.utils.sheet_to_json(sheet, { header: 1, raw: false, defval: '', blankrows: true })
  const mapping = (cells[0] || []).map(value => {
    const header = text(value).trim().toLowerCase()
    return monitoringFields.find(field => field.aliases.some(alias => alias.toLowerCase() === header))
  })
  const nameColumn = mapping.findIndex(field => field && field.key === 'name')
  if (nameColumn < 0) throw new Error('Excel缺少“名称”表头，请使用监测设备模板')
  const keys = mapping.filter(Boolean).map(field => field.key)
  if (new Set(keys).size !== keys.length) throw new Error('Excel中有重复表头，请核对列名')
  const rows = [], bySourceRow = new Map()
  let mergedContinuationRows = 0
  for (let r = 1; r < cells.length; r++) {
    const row = Object.fromEntries(monitoringFields.map(field => [field.key, '']))
    mapping.forEach((field, column) => { if (field) row[field.key] = text((cells[r] || [])[column]) })
    if (!hasContent(row)) continue
    // Only explicit vertical name merges establish a continuation. Blank names otherwise remain separate rows.
    const merge = (sheet['!merges'] || []).find(m => m.s.c === nameColumn && m.e.c === nameColumn && m.s.r < r && m.e.r >= r)
    const previous = merge && bySourceRow.get(merge.s.r)
    if (previous) {
      monitoringFields.forEach(field => {
        const value = row[field.key]
        if (value.trim()) previous[field.key] = previous[field.key] ? previous[field.key] + '\n' + value : value
      })
      mergedContinuationRows++
    } else {
      row._excelRow = r + 1
      rows.push(row)
      bySourceRow.set(r, row)
    }
  }
  if (!rows.length) throw new Error('Excel中没有可导入的监测设备信息')
  return { rows, mergedContinuationRows }
}

export async function readMonitoringFile(file) {
  if (!/\.xlsx?$/i.test(file.name || '')) throw new Error('只支持xls或xlsx文件')
  let book
  try { book = XLSX.read(await file.arrayBuffer(), { type: 'array' }) }
  catch (_) { throw new Error('无法读取Excel，请检查文件是否完整') }
  return parseMonitoringWorkbook(book)
}
