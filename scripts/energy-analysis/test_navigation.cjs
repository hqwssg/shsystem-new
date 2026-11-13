// Uses installed Vue 3 to exercise the real Options API component and reactive filters.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../..')
const Vue = require(path.join(root, 'ruoyi-ui/node_modules/vue'))
const compiler = require('../vue3/compiler.cjs')
const source = fs.readFileSync(path.join(root, 'ruoyi-ui/src/views/carbon/energyAnalysis.vue'), 'utf8')
const sfc = compiler.parseComponent(source)
const apiSource = fs.readFileSync(path.join(root, 'ruoyi-ui/src/api/carbon.js'), 'utf8')
assert.ok(apiSource.includes("'/monthly-analysis/options'"))
assert.ok(!apiSource.includes("'/api/monthly-analysis/"))
assert.deepEqual(compiler.compile(sfc.template.content).errors, [])
assert.ok(sfc.template.content.includes('@update:model-value="onModeChange"'), 'capture the reload intent before the deep filter watcher clears results')
const stored = new Map(), calls = []
let response
const api = { options: async () => options, query: async p => { calls.push(p); return response(p) }, compare: async p => { calls.push(p); return response(p) }, details: async p => { calls.push(p); return { content: [], totalElements: 0 } } }
const context = { module: { exports: {} }, monthlyAnalysisApi: api, sessionStorage: { getItem: key => stored.get(key), setItem: (key, value) => stored.set(key, value) } }
vm.runInNewContext(sfc.script.content.replace(/^import .*$/gm, '').replace('export default', 'module.exports ='), context)
const component = context.module.exports
const options = { companies: [{ id: 301, name: '甲', defaultTemplateId: 1, templates: [{ id: 1, name: '模板甲', nodes: [{ id: 10, name: '根' }, { id: 11, parentId: 10, name: '子点' }] }] }, { id: 302, name: '乙', defaultTemplateId: null, templates: [{ id: 2, name: '模板乙', nodes: [] }] }], energies: ['diesel'], categories: [], departments: [{ id: 1, name: '甲部' }], stations: [] }
const json = x => JSON.parse(JSON.stringify(x))
function instance(view = 'stats', id = 1) {
  const warnings = [], route = Vue.reactive({ path: '/carbon/energy-analysis', query: { analysisView: view } })
  const renderer = Vue.createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode() { return null }, nextSibling() { return null } })
  const rootApp = renderer.createApp({ ...component, created: [], mounted: [], beforeUnmount: [], render: () => null, methods: { ...component.methods, renderChart() {} } })
  Object.assign(rootApp.config.globalProperties, { $route: route, $store: { getters: { id } }, $message: { warning: m => warnings.push(m) } })
  const app = rootApp.mount({})
  app.options = json(options); app.ready = true; app.applyRoute(); app.selectCompany(301)
  return Object.assign(app, { warnings, route })
}
const result = value => ({ rows: [{ companyName: '甲', groupName: '柴油', energy: 'diesel', unit: 't', period: '2025-01', selectedEnergy: value, selectedCarbon: value }], periods: ['2025-01', '2025-02'], summary: { energies: [{ energy: 'diesel', unit: 't' }] }, notices: [] })
async function main() {
  const a = instance(); a.q.months = ['2025-01', '2025-12']; await Vue.nextTick()
  assert.equal(a.request().valueMode, 'ADOPTED'); assert.equal(a.request().selections[0].templateId, 1)
  a.selectCompany(302); assert.throws(() => a.request(), /统计模板/); a.q.selections[0].templateId = 2; assert.equal(a.request().selections[0].companyId, 302)
  a.q.companyIds = [301, 999]; a.syncSelections(); assert.deepEqual(json(a.q.companyIds), [301])
  a.route.query = { analysisView: 'period' }; await Vue.nextTick(); assert.equal(a.q.compareType, 'YOY')
  a.route.query = { analysisView: 'node' }; await Vue.nextTick(); a.q.selections[0].nodeId = 11; assert.equal(a.request().selections[0].nodeId, 11); assert.equal(a.nodeOptions(a.q.selections[0])[1].label.trim(), '子点')
  a.route.query = { analysisView: 'stats' }; await Vue.nextTick(); assert.equal(a.request().selections[0].nodeId, null)
  a.q.grain = 'QUARTER'; a.q.startYear = '2025'; a.q.endYear = '2026'; a.q.startQuarter = 2; a.q.endQuarter = 1; assert.deepEqual(json(a.periodRange()), ['2025-04', '2026-03'])
  a.q.grain = 'YEAR'; assert.deepEqual(json(a.periodRange()), ['2025-01', '2026-12'])
  a.q.grain = 'MONTH'; a.q.months = ['2025-01', '2025-02']; a.q.compareType = 'NONE'; await Vue.nextTick()
  let resolve; response = () => new Promise(done => { resolve = done }); const pending = a.runQuery(); a.q.valueMode = 'RAW'; await Vue.nextTick(); resolve(result(99)); await pending; assert.equal(a.result, null)
  response = async () => result(0); await a.runQuery(); assert.equal(a.result.rows[0].selectedEnergy, 0)
  a.q.valueMode = 'ADJUSTED'; await a.onModeChange(); assert.equal(calls.at(-1).valueMode, 'ADJUSTED'); assert.ok(a.result)
  const chart = a.chartData(); assert.deepEqual(json(chart.series[0].data), [0, null]); assert.equal(a.number(null), '—'); assert.equal(a.number(0), '0')
  a.q.energy = 'diesel'; await Vue.nextTick(); assert.equal(a.result, null)
  a.saveFilters(); const b = instance('stats', 2); assert.notEqual(a.cacheKey, b.cacheKey)
  const c = instance('org'); c.q.companyIds = [301, 302]; c.syncSelections(); c.q.selections[1].templateId = 2; await Vue.nextTick(); assert.equal(c.request().compareType, 'ORGANIZATION'); assert.equal(c.request().selections.length, 2)
  c.result = { previousStartMonth: '2024-01', previousEndMonth: '2024-12' }; c.detailPeriod = 'previous'; await c.loadDetails(); assert.equal(calls.at(-1).startMonth, '2024-01')
  console.log('PASS: Vue template, authorized options, independent templates, legacy links, node scope, natural periods, account cache, stale responses, zero/null chart gaps, comparison and baseline details')
}
main().catch(e => { console.error(e); process.exitCode = 1 })
