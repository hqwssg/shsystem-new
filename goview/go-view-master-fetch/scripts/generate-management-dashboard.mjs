import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { CHART_META, makeComponent, makeTextOption, makeLineOption, makePieOption, makeBorderOption } from './dashboard-component-factory.mjs'
import { managementDataset, energyKinds } from '../src/assets/dashboard/managementDatasets.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const meta = (key, title, category, pack, frame, image) => ({ key, chartKey: `V${key}`, conKey: `VC${key}`, title, category, categoryName: category, package: pack, chartFrame: frame, image })
CHART_META.BarCrossrange = meta('BarCrossrange', '横向柱状图', 'Bars', 'Charts', 'echarts', 'bar_x.png')
CHART_META.ManagementStatus = meta('ManagementStatus', '能碳管理筛选与覆盖', 'Mores', 'Informations', 'common', 'table_scrollboard.png')
const palettes = ['#49d6c5', '#46a8fa', '#9a91fa', '#f4bc71', '#ee859c']

export function buildManagementDashboardStorage() {
  const components = []
  function add(key, id, x, y, w, h, option, role, z = 10) {
    components.push(makeComponent(key, { id: `management-${id}`, attr: { x, y, w, h, zIndex: z },
      option: { ...option, ...(role ? { managementRole: role } : {}) } }))
  }
  function text(id, x, y, w, h, value, size = 18, role, color = '#d7e9ff') {
    add('TextCommon', id, x, y, w, h, makeTextOption(value, size, { fontColor: color, letterSpacing: 0, textAlign: 'left', paddingX: 0, paddingY: 0 }), role)
  }
  function panel(id, x, y, w, h, title, subtitle = '') {
    add('Border02', `border-${id}`, x, y, w, h, { ...makeBorderOption(), backgroundColor: '#0c2036', colors: ['#234762', '#2c657a'] }, null, 1)
    text(`title-${id}`, x + 20, y + 12, w - 40, 30, title, 19)
    if (subtitle) text(`sub-${id}`, x + 20, y + 47, w - 40, 23, subtitle, 13, null, '#8faac6')
  }
  text('title', 40, 20, 1150, 55, '朔黄铁路 · 能碳数据可视化', 32)
  text('updated', 1250, 32, 630, 32, '最近核算：暂无记录', 15, 'updated', '#8faac6')
  add('ManagementStatus', 'controls', 40, 96, 1840, 52, { mode: 'controls', dataMode: 'demo' })
  text('basis', 40, 164, 1840, 40, '正在连接正式核算数据…', 14, 'basis', '#a4bdd6')
  const cards = [['carbon', '年度排放量 · tCO₂e'], ['electricity', '购入电力消耗'], ['fuel', '化石燃料消耗 · 按单位分别汇总'], ['heat', '购入热力消耗']]
  cards.forEach(([role, title], i) => {
    const x = 40 + 465 * i
    panel(`kpi-${role}`, x, 222, 445, 125, title)
    text(`kpi-${role}`, x + 20, 273, 405, 52, '暂无数据', role === 'carbon' ? 34 : 28, role, palettes[i])
  })
  panel('rank', 40, 371, 475, 317, '公司排放量排行', '年度汇总 · tCO₂e')
  const rank = makeLineOption(managementDataset('rank', null), [{ type: 'bar', encode: { x: '排放量', y: '公司' }, barMaxWidth: 24, itemStyle: { color: '#49d6c5', borderRadius: [0, 5, 5, 0] }, label: { show: true, position: 'right', color: '#dcefff' } }])
  rank.xAxis = { type: 'value', axisLabel: { color: '#8faac6' }, splitLine: { lineStyle: { color: '#1d3b55' } } }
  rank.yAxis = { type: 'category', axisLabel: { color: '#bcd4eb', width: 120, overflow: 'truncate' } }
  rank.legend = { show: false }; rank.grid = { left: 130, right: 70, top: 12, bottom: 30 }
  add('BarCrossrange', 'rank', 52, 446, 450, 225, rank, 'rank')
  panel('trend', 535, 371, 817, 317, '月度碳排放趋势', '来自月度任务；缺失月份留空；不拆分年度和跨月结果')
  const trend = makeLineOption(managementDataset('trend', null), [{ type: 'line', name: '碳排放量', encode: { x: '月份', y: '碳排放量' }, connectNulls: false, showSymbol: true, symbolSize: 6, lineStyle: { color: '#46a8fa', width: 3 }, itemStyle: { color: '#46a8fa' }, areaStyle: { color: '#173d5c' } }])
  trend.yAxis = { type: 'value', name: 'tCO₂e', nameTextStyle: { color: '#8faac6' }, axisLabel: { color: '#8faac6' }, splitLine: { lineStyle: { color: '#1d3b55' } } }
  trend.xAxis.axisLabel = { color: '#8faac6', rotate: 25 }
  trend.grid = { left: 70, right: 20, top: 28, bottom: 55 }; trend.legend = { show: false }
  add('LineCommon', 'trend', 550, 446, 785, 225, trend, 'trend')
  panel('sources', 1372, 371, 508, 317, '排放来源构成', '年度各能源排放量占比')
  const pie = makePieOption(managementDataset('sources', null))
  pie.legend = { show: true, orient: 'vertical', right: 0, top: 'middle', textStyle: { color: '#adc6e0' } }
  pie.series[0].center = ['34%', '50%']; pie.series[0].radius = ['48%', '70%']; pie.color = palettes
  pie.series[0].encode = { itemName: 'name', value: 'value' }
  pie.series[0].stillShowZeroSum = false; pie.series[0].showEmptyCircle = false
  add('PieCommon', 'sources', 1385, 448, 480, 222, pie, 'sources')
  text('rank-empty', 180, 535, 300, 30, '暂无可展示的年度数据', 16, 'rankEmpty', '#8faac6')
  text('trend-empty', 800, 530, 340, 30, '暂无月度核算数据', 16, 'trendEmpty', '#8faac6')
  text('sources-empty', 1500, 535, 340, 30, '暂无可展示的年度数据', 16, 'sourcesEmpty', '#8faac6')
  panel('energy-compare', 40, 712, 580, 326, '公司能源消耗对比')
  text('energy-unit', 60, 759, 540, 25, '能源：电力 · 单位：暂无数据', 14, 'energyUnitLabel', '#8faac6')
  const compare = makeLineOption(managementDataset('energyCompare', null), [{ type: 'bar', encode: { x: '消耗量', y: '公司' }, barMaxWidth: 24,
    itemStyle: { color: '#9a91fa', borderRadius: [0, 5, 5, 0] }, label: { show: true, position: 'right', color: '#dcefff' } }])
  compare.xAxis = { type: 'value', axisLabel: { color: '#8faac6' }, splitLine: { lineStyle: { color: '#1d3b55' } } }
  compare.yAxis = { type: 'category', axisLabel: { color: '#bcd4eb', width: 125, overflow: 'truncate' } }
  compare.legend = { show: false }; compare.grid = { left: 135, right: 65, top: 12, bottom: 30 }
  add('BarLine', 'energy-compare', 55, 794, 550, 225, compare, 'energyCompare')
  panel('company-structure', 640, 712, 600, 326, '公司排放来源对比', '同一公司各能源的排放贡献 · tCO₂e')
  const companyStructure = makeLineOption(managementDataset('companyStructure', null), energyKinds.map((kind, i) => ({
    name: kind, type: 'bar', stack: 'carbon', encode: { x: kind, y: '公司' }, barMaxWidth: 28, itemStyle: { color: palettes[i] }
  })))
  companyStructure.xAxis = { type: 'value', axisLabel: { color: '#8faac6' }, splitLine: { lineStyle: { color: '#1d3b55' } } }
  companyStructure.yAxis = { type: 'category', axisLabel: { color: '#bcd4eb', width: 110, overflow: 'truncate' } }
  companyStructure.legend = { show: true, top: 0, textStyle: { color: '#adc6e0' } }
  companyStructure.grid = { left: 120, right: 25, top: 42, bottom: 30 }
  add('BarLine', 'company-structure', 655, 794, 570, 225, companyStructure, 'companyStructure')
  panel('monthly-structure', 1260, 712, 620, 326, '月度能源排放构成', '各能源排放量变化 · tCO₂e')
  const monthlyStructure = makeLineOption(managementDataset('monthlyStructure', null), energyKinds.map((kind, i) => ({
    name: kind, type: 'line', stack: 'carbon', encode: { x: '月份', y: kind }, connectNulls: false, showSymbol: false,
    lineStyle: { color: palettes[i], width: 2 }, itemStyle: { color: palettes[i] }, areaStyle: { color: palettes[i], opacity: 0.2 }
  })))
  monthlyStructure.legend = { show: true, top: 0, textStyle: { color: '#adc6e0' } }
  monthlyStructure.xAxis.axisLabel = { color: '#8faac6', rotate: 30 }
  monthlyStructure.yAxis = { type: 'value', axisLabel: { color: '#8faac6' }, splitLine: { lineStyle: { color: '#1d3b55' } } }
  monthlyStructure.grid = { left: 55, right: 15, top: 42, bottom: 50 }
  add('LineCommon', 'monthly-structure', 1275, 794, 590, 225, monthlyStructure, 'monthlyStructure')
  text('energy-compare-empty', 230, 890, 340, 30, '暂无同单位能源消耗数据', 16, 'energyCompareEmpty', '#8faac6')
  text('company-structure-empty', 850, 890, 340, 30, '暂无公司排放结构数据', 16, 'companyStructureEmpty', '#8faac6')
  text('monthly-structure-empty', 1450, 890, 340, 30, '暂无月度能源排放数据', 16, 'monthlyStructureEmpty', '#8faac6')
  text('footer', 40, 1049, 1840, 23, '演示数据｜模拟生成，非实际核算结果', 13, 'dataSource', '#7492ae')
  return {
    editCanvasConfig: { projectName: '朔黄铁路能碳数据可视化大屏', width: 1920, height: 1080, background: '#071525', backgroundImage: null,
      selectColor: true, chartThemeColor: 'dark', chartThemeSetting: {}, vChartThemeName: 'vScreenVolcanoBlue', previewScaleType: 'fit', projectId: null,
      remarks: '能碳数据可视化版 · 演示/正式双模式 · 默认演示数据' },
    requestGlobalConfig: { requestInterval: 0, requestIntervalUnit: 'second', requestOriginUrl: '', requestDataPond: [], requestParams: { Body: { 'form-data': {}, 'x-www-form-urlencoded': {}, json: '', xml: '' }, Header: {}, Params: {} } },
    componentList: components
  }
}
export function writeManagementTemplate() {
  const path = resolve(root, 'public/templates/shuohuang-management-dashboard.json')
  mkdirSync(dirname(path), { recursive: true })
  const storage = buildManagementDashboardStorage()
  writeFileSync(path, JSON.stringify(storage, null, 2) + '\n')
  console.log(`Generated management template: ${storage.componentList.length} components`)
  return storage
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) writeManagementTemplate()
