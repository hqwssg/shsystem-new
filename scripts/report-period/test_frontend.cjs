// Run against actual Vue component scripts with isolated API doubles.
const fs = require('fs')
const vm = require('vm')
const assert = require('assert/strict')
const path = require('path')
const root = path.resolve(__dirname, '../..')
const utilities = fs.readFileSync(path.join(root, 'ruoyi-ui/src/utils/reportPeriod.js'), 'utf8').replace(/export /g, '')
const utilContext = { module: { exports: {} } }
vm.runInNewContext(utilities + '\nmodule.exports={reportPeriod,reportPeriodLabel,reportArtifactName,classifyReportPeriod}', utilContext)
const util = utilContext.module.exports
function component(file, api = {}) {
  const sfc = fs.readFileSync(path.join(root, 'ruoyi-ui/src/views/carbon/report', file), 'utf8')
  const source = sfc.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '').replace('export default', 'module.exports=')
  const context = { module: { exports: {} }, ...util, ...api, setInterval, clearInterval }
  vm.runInNewContext(source, context)
  return context.module.exports
}
function instance(def, draft) {
  const self = { draft, $emit() {}, $message: Object.assign(() => {}, { success() {}, warning() {}, error() {} }), $router: { push() {} } }
  Object.assign(self, def.data.call(self))
  for (const [key, fn] of Object.entries(def.methods)) self[key] = fn.bind(self)
  for (const [key, fn] of Object.entries(def.computed)) Object.defineProperty(self, key, { get: () => fn.call(self) })
  return self
}
async function main() {
  const task = { id: 9, version: 2, periodType: 'YEAR', reportYear: 2025, metadataJson: JSON.stringify({ _report_period: { version: 1, start: '2025-01-01', end: '2025-12-31' } }) }
  for (const count of [0, 1, 2]) {
    const options = Array.from({ length: count }, (_, i) => ({ taskId: i + 1, values: { total_emissions_tco2: 50 }, selectionHash: 'test' }))
    const def = component('steps/ReviewStep.vue', { listComparisonCandidates: () => Promise.resolve({ data: { yoy: { start: '2024-01-01', end: '2024-12-31', candidates: options } } }) })
    const self = instance(def, { task }); await self.loadComparisons()
    assert.equal(self.comparisonChoice.yoy, count === 1 ? '1' : 'NONE')
    assert.equal(self.comparisonDirty, count === 1)
  }
  const frozenTask = { ...task, priorYearJson: JSON.stringify({ total_emissions_tco2: 45, _comparison: { mode: 'TASK', taskId: 123 } }) }
  const frozen = instance(component('steps/ReviewStep.vue', { listComparisonCandidates: () => Promise.resolve({ data: { yoy: { candidates: [] } } }) }), { task: frozenTask })
  frozen.hydratePrior(); await frozen.loadComparisons()
  assert.equal(frozen.prior.total_emissions_tco2, 45)
  assert.equal(frozen.comparisonPayload('yoy').mode, 'KEEP')
  const failed = instance(component('steps/ReviewStep.vue', { listComparisonCandidates: () => Promise.reject(new Error('offline')) }), { task: frozenTask })
  failed.hydratePrior(); await failed.loadComparisons()
  assert.equal(failed.prior.total_emissions_tco2, 45); assert.equal(failed.comparisonError, true)
  await assert.rejects(failed.savePrior())

  let creates = 0, previews = 0
  const def = component('create.vue', { createTask: () => { creates++; return Promise.resolve({ data: { id: 1, version: 2 } }) }, prefillPreview: () => { previews++; throw Error('existing edits must survive retry') } })
  const self = instance(def)
  self.subjects = [{ deptId: 3030, deptName: '机辆分公司', configured: true }];self.form.deptId = 3030
  self.calcs = [{ id: 4178, templateName: '三个月模板', cycleStart: '2025-03-01', cycleEnd: '2025-05-31' }];self.form.calculationTemplateId = 4178
  assert.match(self.reportTitle, /三个月模板（2025-03-01至2025-05-31）/)
  const first = self.submit(); const duplicate = self.submit(); await Promise.all([first, duplicate])
  assert.equal(creates, 1);assert.equal(previews, 0)
  assert.equal(util.classifyReportPeriod('2024-02-01', '2024-02-29'), '完整自然月')
  assert.equal(util.classifyReportPeriod('2024-06-01', '2025-05-31'), '期间报告')
  console.log('Frontend: zero/one/multiple baselines, frozen adoption, failed load preservation, duplicate submission, task dates/title: PASS')
}
main().catch(e => { console.error(e); process.exitCode = 1 })
