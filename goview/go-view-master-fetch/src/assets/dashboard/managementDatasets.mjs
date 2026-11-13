// Shared by the live component bridge and the template's runnable checks.
const format = value => value == null ? '暂无数据' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
const safe = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]))
export const energyKinds = ['电力', '燃料', '热力', '其他']
const energyPrefix = { electricity: 'PE_', fuel: 'FF_', heat: 'PH_' }
const unitOf = energy => energy.unitName || energy.unitCode || '未填单位'
const typeOf = energy => {
  const code = String(energy.subcategory || '')
  return code.startsWith('PE_') ? '电力' : code.startsWith('FF_') ? '燃料' : code.startsWith('PH_') ? '热力' : '其他'
}
export function managementEnergyUnits(data, type = 'electricity') {
  return [...new Set((data?.annualRows || []).flatMap(row => row.energies || [])
    .filter(e => String(e.subcategory).startsWith(energyPrefix[type] || 'PE_') && e.energy != null).map(unitOf))].sort()
}
export function managementDataset(role, data, scope = {}) {
  const rows = data?.annualRows || []
  if (role === 'rankEmpty' || role === 'sourcesEmpty') return rows.length ? '' : '暂无可展示的年度数据'
  if (role === 'trendEmpty') return data?.monthlyRows?.length ? '' : '暂无月度核算数据'
  if (role === 'companyStructureEmpty') return rows.some(row => (row.energies || []).some(e => e.carbon != null)) ? '' : '暂无公司排放结构数据'
  if (role === 'monthlyStructureEmpty') return (data?.monthlyRows || []).some(row => (row.energies || []).some(e => e.carbon != null)) ? '' : '暂无月度能源排放数据'
  if (role === 'carbon') return format(data?.carbon)
  if (['electricity', 'fuel', 'heat'].includes(role)) {
    const prefix = { electricity: 'PE_', fuel: 'FF_', heat: 'PH_' }[role]
    const totals = new Map()
    for (const row of rows) for (const e of row.energies || []) {
      if (String(e.subcategory).startsWith(prefix) && e.energy != null) totals.set(e.unitName, (totals.get(e.unitName) || 0) + Number(e.energy))
    }
    return [...totals].map(([unit, value]) => `${format(value)} ${unit}`).join(' / ') || '暂无数据'
  }
  if (role === 'coverage') return data?.coveragePercent == null ? '暂无数据' : `${data.coveragePercent}%`
  if (role === 'units') return Object.entries(data?.units || {}).map(([unit, value]) => `${format(value)} ${unit}`).join('  /  ') || '暂无活动量数据'
  if (role === 'quality') return data ? `${data.problemTaskCount} 个待核对任务` : '暂无数据'
  if (role === 'basis') return data?.isDemo ? `演示数据 · ${data.year}年全年模拟数据，数量及因子仅用于可视化展示，非实际核算结果。` : data ? `${data.year}年 · 沿用原核算因子，年度与月度采用各自核算口径；缺失月份留空，不平均分摊。` : '正在连接正式核算数据…'
  if (role === 'dataSource') return data?.isDemo ? '演示数据｜三家公司、12个月、五类能源均为模拟生成，仅用于展示效果；未写入真实采集、核算或报告数据。' : '数据来源：正式核算任务快照  |  未归属任务、展示任务及质量异常任务不纳入数值统计  |  暂无数据不代表零排放'
  if (role === 'updated') return `核算数据更新：${data?.updatedAt || '暂无记录'}`
  if (['energyCompare', 'energyUnitLabel', 'energyCompareEmpty'].includes(role)) {
    const type = scope.energyType || 'electricity', units = managementEnergyUnits(data, type)
    const unit = units.includes(scope.energyUnit) ? scope.energyUnit : units[0]
    const totals = new Map()
    for (const row of rows) for (const energy of row.energies || []) {
      if (String(energy.subcategory).startsWith(energyPrefix[type] || 'PE_') && energy.energy != null && unitOf(energy) === unit)
        totals.set(row.orgName, (totals.get(row.orgName) || 0) + Number(energy.energy))
    }
    if (role === 'energyUnitLabel') return `能源：${{ electricity: '电力', fuel: '燃料', heat: '热力' }[type]} · 单位：${unit || '暂无数据'}${units.length > 1 ? '（其他单位未混加）' : ''}`
    if (role === 'energyCompareEmpty') return totals.size ? '' : '暂无同单位能源消耗数据'
    return { dimensions: ['公司', '消耗量'], source: [...totals].sort((a, b) => a[1] - b[1]) }
  }
  if (role === 'companyStructure' || role === 'monthlyStructure') {
    const monthly = role === 'monthlyStructure', groups = new Map()
    for (const row of monthly ? data?.monthlyRows || [] : rows) {
      const key = monthly ? row.period : row.orgName
      for (const energy of row.energies || []) if (energy.carbon != null) {
        if (!groups.has(key)) groups.set(key, {})
        const values = groups.get(key), type = typeOf(energy)
        values[type] = (values[type] ?? 0) + Number(energy.carbon)
      }
    }
    const keys = monthly ? Array.from({ length: 12 }, (_, m) => `${data?.year || new Date().getFullYear()}-${String(m + 1).padStart(2, '0')}`) : [...groups.keys()]
    return { dimensions: [monthly ? '月份' : '公司', ...energyKinds], source: keys.map(key => [key, ...energyKinds.map(kind => groups.get(key)?.[kind] ?? null)]) }
  }
  if (role === 'rank') {
    const totals = new Map()
    for (const row of rows) if (row.carbon != null) totals.set(row.orgName, (totals.get(row.orgName) || 0) + Number(row.carbon))
    return { dimensions: ['公司', '排放量'], source: [...totals].sort((a, b) => a[1] - b[1]).map(([name, value]) => [name, value]) }
  }
  if (role === 'sources') return { dimensions: ['name', 'value'], source: Object.entries(data?.sources || {}).map(([name, value]) => ({ name, value })) }
  if (role === 'trend') {
    const totals = new Map()
    for (const row of data?.monthlyRows || []) if (row.carbon != null) totals.set(row.period, (totals.get(row.period) || 0) + Number(row.carbon))
    return { dimensions: ['月份', '碳排放量'], source: Array.from({ length: 12 }, (_, m) => {
      const period = `${data?.year || new Date().getFullYear()}-${String(m + 1).padStart(2, '0')}`
      return [period, totals.has(period) ? totals.get(period) : null]
    }) }
  }
  if (role === 'issues') return (data?.problems || ['暂无数据']).map((item, i) => [String(i + 1), safe(item)])
  if (role === 'recent') return (data?.recent || []).map(row => row.map(safe))
  return ''
}
