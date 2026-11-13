// Synthetic presentation data only; never submitted to business APIs.
import { buildManagementDemo } from './managementDemo.mjs'

const round = value => Math.round(value * 10000) / 10000
const sum = values => round(values.reduce((total, value) => total + value, 0))
const pie = rows => ({ dimensions: ['name', 'value'], source: rows })

export function buildPanoramaDemo(stationNames, year = 2026) {
  if (!stationNames.length || new Set(stationNames).size !== stationNames.length) throw new Error('Unique station names required')
  const years = [year - 2, year - 1, year]
  const models = years.map(value => buildManagementDemo(value))
  const companies = models[0].companies
  const weights = stationNames.map((_, index) => 1 + (index % 7) * 0.13)
  const groupWeights = companies.map((_, group) => sum(weights.filter((_, index) => index % companies.length === group)))
  const stations = {}, mapEmissions = {}
  const allMonths = years.map(() => Array(12).fill(0))
  const sources = new Map()
  for (let index = 0; index < stationNames.length; index++) {
    const group = index % companies.length
    const share = weights[index] / groupWeights[group] * 0.1
    const rows = models.map(model => model.monthlyRows.filter(row => row.orgId === companies[group].id))
    const months = rows.map(list => list.map(row => round(row.carbon * share)))
    months.forEach((list, y) => list.forEach((value, m) => { allMonths[y][m] += value }))
    const currentSources = models[2].annualRows.find(row => row.orgId === companies[group].id).energies
      .map(item => ({ name: item.subcategoryName, value: round(item.carbon * share) }))
    const total = sum(months[2]), previous = sum(months[1])
    currentSources[0].value = round(total - sum(currentSources.slice(1).map(item => item.value)))
    currentSources.forEach(item => sources.set(item.name, (sources.get(item.name) || 0) + item.value))
    const bucket = makeBucket(years, months, total, previous, currentSources)
    bucket.kpi.intensity = round(7.5 + (index % 9) * 0.65)
    stations[stationNames[index]] = bucket
    mapEmissions[stationNames[index]] = { carbonEmission: total, carbonIntensity: bucket.kpi.intensity }
  }
  const total = sum(allMonths[2]), previous = sum(allMonths[1])
  const overall = makeBucket(years, allMonths.map(list => list.map(round)), total, previous,
    [...sources].map(([name, value]) => ({ name, value: round(value) })))
  overall.kpi.pointCount = stationNames.length
  const rank = stationNames.slice().sort((a, b) => stations[b].kpi.yearTotal - stations[a].kpi.yearTotal)
    .map(name => [name, String(stations[name].kpi.yearTotal), String(stations[name].kpi.intensity)])
  return { schemaVersion: 1, isDemo: true, description: '演示数据：模拟生成，非实际核算；不写入业务数据库。',
    periodLabel: `演示数据 · 统计周期：${year}年1月—${year}年12月`, overall, stations, mapEmissions, rank }
}

function makeBucket(years, months, total, previous, sourceRows) {
  const typeRows = [
    { name: '间接排放', value: sum(sourceRows.filter(row => ['购入电力', '购入热力'].includes(row.name)).map(row => row.value)) },
    { name: '直接排放', value: sum(sourceRows.filter(row => !['购入电力', '购入热力'].includes(row.name)).map(row => row.value)) }
  ]
  const production = round(total * 0.86)
  return {
    kpi: { yearTotal: total, monthTotal: months[2][11], yoyPercent: previous ? round((total - previous) / previous * 100) : 0, pointCount: 0, intensity: 0 },
    line: { dimensions: ['month', 'actual', 'forecast'], source: months[2].map((actual, index) => ({
      month: `${years[2]}-${String(index + 1).padStart(2, '0')}`, actual, forecast: null })) },
    surface: { timeType: 'month', years, times: Array.from({ length: 12 }, (_, i) => `${i + 1}月`), values: months, unit: 'tCO2e' },
    pies: { source: pie(sourceRows), type: pie(typeRows), segment: pie([
      { name: '生产用能', value: production }, { name: '非生产用能', value: round(total - production) }]) }
  }
}
