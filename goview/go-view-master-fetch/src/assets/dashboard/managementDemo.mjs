// Presentation-only fixtures. Never submitted to collection/calculation/report APIs.
const companies = [
  { id: 'demo-suning', name: '肃宁分公司', base: [8600, 520, 4.5, 2.2, 1700] },
  { id: 'demo-yuanping', name: '原平分公司', base: [10400, 650, 6, 3.1, 2100] },
  { id: 'demo-jiliang', name: '机辆分公司', base: [14200, 780, 9, 0.065, 7400] }
]
const sources = [
  ['PE_PF', '购入电力', 'MWh', 0.53], ['FF_D', '柴油', 't', 3.15],
  ['FF_G', '汽油', 't', 3.04], ['FF_NG', '天然气', '万Nm³', 21.62], ['PH_HD', '购入热力', 'GJ', 0.11]
]
const seasons = [1.14, 1.08, 0.99, 0.95, 0.92, 1.04, 1.10, 1.12, 0.98, 0.94, 1.01, 1.17]
const round = value => Math.round(value * 10000) / 10000

export function buildManagementDemo(requestedYear, companyId = '') {
  const year = Number(requestedYear) || 2026
  const selected = companies.filter(c => !companyId || c.id === companyId)
  const monthlyRows = [], annualRows = [], totals = {}, units = {}
  for (const company of selected) {
    const annual = sources.map(([subcategory, subcategoryName, unitCode]) => ({ subcategory, subcategoryName, unitCode, unitName: unitCode, energy: 0, carbon: 0 }))
    for (let month = 1; month <= 12; month++) {
      const energies = sources.map(([subcategory, subcategoryName, unitCode, factor], i) => {
        const variation = i === 4 ? (month <= 3 || month >= 11 ? 1.6 : 0.45) : seasons[month - 1]
        const energy = round(company.base[i] * variation * (1 + (year - 2025) * 0.04) * (1 + 0.012 * Math.sin(month + i)))
        const carbon = round(energy * factor)
        annual[i].energy = round(annual[i].energy + energy)
        annual[i].carbon = round(annual[i].carbon + carbon)
        return { subcategory, subcategoryName, unitCode, unitName: unitCode, energy, carbon }
      })
      monthlyRows.push({ orgId: company.id, orgName: company.name, period: `${year}-${String(month).padStart(2, '0')}`, carbon: round(energies.reduce((sum, e) => sum + e.carbon, 0)), energies })
    }
    annualRows.push({ orgId: company.id, orgName: company.name, period: String(year), carbon: round(annual.reduce((sum, e) => sum + e.carbon, 0)), energies: annual })
    for (const energy of annual) {
      totals[energy.subcategoryName] = round((totals[energy.subcategoryName] || 0) + energy.carbon)
      units[energy.unitName] = round((units[energy.unitName] || 0) + energy.energy)
    }
  }
  return {
    isDemo: true, year, companyId: companyId || null, years: [2026, 2025, 2024],
    companies: companies.map(({ id, name }) => ({ id, name })),
    annualRows, monthlyRows, carbon: round(annualRows.reduce((sum, row) => sum + row.carbon, 0)),
    units, sources: totals, coverage: [], problems: [], recent: [], problemTaskCount: 0,
    updatedAt: '模拟生成，非实际核算', basis: '演示数据：数值及因子仅用于验证可视化效果，不代表实际企业排放。'
  }
}
