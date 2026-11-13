import * as XLSX from 'xlsx'

const field = (key, label, max, aliases = []) => ({ key, label, max, aliases: [key, label, ...aliases] })
export const reportFields = {
  equipment: [field('name', '名称', 255), field('category', '类别', 64), field('quantity', '数量'), field('unit', '单位', 32),
    field('model', '型号', 128), field('energyType', '能源种类', 64, ['energy_type']), field('remark', '备注', 255)],
  workload: [field('name', '名称', 128), field('quantity', '数量'), field('unit', '单位', 32)],
  heat: [field('site', '站点', 255), field('heatingAreaM2', '供暖面积', null, ['heating_area_m2']),
    field('heatCoefficient', '耗热量系数', null, ['热力系数', 'heat_coefficient'])]
}
const str = value => value == null ? '' : String(value)
const norm = value => str(value).trim().toLowerCase()
const content = (row, fields) => fields.some(f => str(row[f.key]).trim())
const numeric = ['quantity', 'heatingAreaM2', 'heatCoefficient']
const decimalKey = value => {
  const [base, power = '0'] = str(value).trim().replace(/,/g, '').replace(/^[+-]/, '').toLowerCase().split('e')
  const [whole, fraction = ''] = base.split('.')
  let digits = (whole + fraction).replace(/^0+/, '')
  let exponent = Number(power) - fraction.length
  while (digits.endsWith('0')) { digits = digits.slice(0, -1); exponent++ }
  return digits ? digits + 'e' + exponent : '0'
}
export function numberValue(value, label) {
  const s = str(value).trim().replace(/,/g, '')
  if (!s) return null
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(s) || !Number.isFinite(Number(s))) throw new Error(label + '不是有效数字')
  if (s.startsWith('-') && decimalKey(s) !== '0') throw new Error(label + '不能为负数')
  return s
}

export function reportRowChecks(rows, type) {
  const fields = reportFields[type]
  return rows.map((row, i) => {
    const errors = [], messages = []
    if (!content(row, fields)) return { errors, messages }
    const key = type === 'heat' ? 'site' : 'name'
    if (!str(row[key]).trim()) (type === 'equipment' ? messages : errors).push((type === 'heat' ? '站点' : '名称') + '未填写，请核对')
    fields.forEach(f => {
      if (f.max && Array.from(str(row[f.key])).length > f.max) errors.push(f.label + '超过' + f.max + '字，保存前请缩短')
      if (numeric.includes(f.key)) {
        try {
          const value = numberValue(row[f.key], f.label)
          if (value != null && decimalKey(value) !== '0') {
            const [digits, power] = decimalKey(value).split('e')
            const scale = type === 'equipment' ? 4 : 6
            if (Number(power) < -scale || digits.length + Number(power) > 18 - scale) errors.push(f.label + '超出允许精度（小数最多' + scale + '位），请核对后保存')
          }
        } catch (e) { errors.push(e.message) }
      }
    })
    if (type === 'workload') {
      if (!str(row.quantity).trim() || Number(row.quantity) === 0) messages.push('无正数量，保存时忽略，不计算排放强度')
      if (rows.some((other, j) => j !== i && norm(other.name) === norm(row.name))) errors.push('指标名称重复，请合并或删除，不能重复计算工作量')
    } else if (type === 'equipment') {
      if (rows.some((other, j) => j !== i && fields.every(f => str(other[f.key]).trim() === str(row[f.key]).trim()))) messages.push('整行内容重复，请核对（仍可保存）')
    }
    return { errors, messages: [...messages, ...errors] }
  })
}

export function parseReportWorkbook(book, type) {
  const fields = reportFields[type]
  if (!fields) throw new Error('不支持的导入类型')
  const sheet = book.Sheets[book.SheetNames[0]]
  if (!sheet) throw new Error('Excel中没有工作表')
  const cells = XLSX.utils.sheet_to_json(sheet, { header: 1, raw: true, defval: '', blankrows: true })
  const mapping = (cells[0] || []).map(value => fields.find(f => f.aliases.some(a => norm(a) === norm(value))))
  const key = type === 'heat' ? 'site' : 'name'
  if (!mapping.some(f => f && f.key === key)) throw new Error('Excel缺少“' + (type === 'heat' ? '站点' : '名称') + '”表头')
  const keys = mapping.filter(Boolean).map(f => f.key)
  if (new Set(keys).size !== keys.length) throw new Error('Excel有重复表头（含同一字段的中英文列），请保留一列')
  const rows = [], notices = []
  for (let r = 1; r < cells.length; r++) {
    const row = Object.fromEntries(fields.map(f => [f.key, '']))
    mapping.forEach((f, c) => {
      if (!f) return
      let sourceRow = r
      if (type === 'equipment') {
        const merged = (sheet['!merges'] || []).find(m => m.s.c === c && m.e.c === c && m.s.r < r && m.e.r >= r)
        if (merged) sourceRow = merged.s.r
      }
      const cell = sheet[XLSX.utils.encode_cell({ r: sourceRow, c })]
      if (cell && cell.t === 'e') throw new Error('Excel第' + (r + 1) + '行“' + f.label + '”含错误值')
      if (cell && cell.f && cell.v == null) throw new Error('Excel第' + (r + 1) + '行“' + f.label + '”公式没有计算结果，请用Excel计算保存或粘贴为数值')
      row[f.key] = str(!numeric.includes(f.key) && cell && cell.w != null ? cell.w : (cells[sourceRow] || [])[c])
    })
    if (!content(row, fields)) continue
    row._excelRow = r + 1
    // Non-equipment rows must have a key; reject the file rather than silently lose populated rows.
    if (type !== 'equipment' && !str(row[key]).trim()) throw new Error('Excel第' + (r + 1) + '行缺少' + (type === 'heat' ? '站点' : '名称'))
    fields.filter(f => numeric.includes(f.key)).forEach(f => {
      const value = numberValue(row[f.key], 'Excel第' + (r + 1) + '行“' + f.label + '”')
      row[f.key] = value == null ? '' : value
    })
    if (type === 'workload' && (!row.quantity || decimalKey(row.quantity) === '0')) {
      notices.push('Excel第' + (r + 1) + '行无正数量，已忽略')
      continue
    }
    rows.push(row)
  }
  if (!rows.length) throw new Error('没有可导入的有效行' + (notices.length ? '；' + notices.join('；') : ''))
  return { rows, notices, importedCount: rows.length }
}

export function mergeReportRows(current, incoming, type, mode) {
  if (!['append', 'overwrite'].includes(mode)) throw new Error('导入方式不正确')
  if (type === 'equipment') return (mode === 'overwrite' ? incoming : [...current, ...incoming]).map(row => ({ ...row }))
  if (type === 'heat' && new Set(incoming.map(row => norm(row.site))).size !== incoming.length) throw new Error('Excel中站点重复，无法确定对应记录，请整理后重试')
  const rows = (type === 'workload' && mode === 'overwrite' ? [] : current).map(row => ({ ...row }))
  incoming.forEach(item => {
    const key = type === 'heat' ? 'site' : 'name'
    const matches = rows.filter(row => norm(row[key]) === norm(item[key]))
    if (matches.length > 1) throw new Error('“' + item[key] + '”匹配到多条记录，请在页面逐行核对后填写')
    if (!matches.length) {
      rows.push(type === 'heat' ? { site: item.site, heatingAreaM2: item.heatingAreaM2, heatCoefficient: item.heatCoefficient, normalizedValue: null, dataOrigin: 'IMPORT' } : { ...item })
      return
    }
    const existing = matches[0]
    if (type === 'heat') {
      // Each field is independent; imported blanks never clear existing fields or touch GJ.
      ;['heatingAreaM2', 'heatCoefficient'].forEach(f => {
        if (str(item[f]).trim() && (mode === 'overwrite' || !str(existing[f]).trim())) existing[f] = item[f]
      })
    } else {
      if (norm(existing.unit) && norm(item.unit) && norm(existing.unit) !== norm(item.unit)) throw new Error('“' + item.name + '”单位不一致，不能合并，请核对单位')
      if (!str(existing.quantity).trim() || Number(existing.quantity) === 0) {
        existing.quantity = item.quantity
        existing.unit = existing.unit || item.unit
      } else if (decimalKey(existing.quantity) !== decimalKey(item.quantity)) throw new Error('“' + item.name + '”已有不同数量，请选择覆盖或在页面核对修改，不自动累加')
    }
  })
  return rows
}

export async function readReportFile(file, type) {
  if (!/\.xlsx?$/i.test(file.name || '')) throw new Error('只支持xls或xlsx文件')
  let book
  try { book = XLSX.read(await file.arrayBuffer(), { type: 'array', cellFormula: true }) }
  catch (_) { throw new Error('无法读取Excel，请检查文件是否完整') }
  return parseReportWorkbook(book, type)
}
