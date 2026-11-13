const fs = require('fs')
const vm = require('vm')
const assert = require('assert')
const compiler = require('./vue3/compiler.cjs')
let source = fs.readFileSync('ruoyi-ui/src/utils/energyPreview.js', 'utf8')
const names = Array.from(source.matchAll(/export function (\w+)/g), match => match[1])
source = source.replace(/export function /g, 'function ') + '\nmodule.exports = {' + names.join(',') + '}'
const context = { module: { exports: {} } }
vm.runInNewContext(source, context)
const { buildKpiCards, decisionCopy } = context.module.exports
let cards = buildKpiCards({ kpis: [{ caseName: 'baseline', gridKwh: 0, wastedKwh: 0 }], auditSummary: { baselineGridKwh: 999, baselineWastedKwh: 888 } }, 'dispatch', {})
assert(cards.find(c => c.label === '电网购电').value.startsWith('0'))
assert(cards.find(c => c.label === '弃能').value.startsWith('0'))
cards = buildKpiCards({ decision: { action: 'optimize', gridImprovementKwh: 50 } }, 'timetable_optimization', { result: { optimization_decision: { action: 'no_feasible_solution' } } })
assert.strictEqual(cards.find(c => c.label === '购电改善').value, '未评价')
cards = buildKpiCards({}, 'dispatch', { result: { comparison: { energy_comparison_eligible: false } } })
assert.strictEqual(cards.find(c => c.label === '节能改善').value, '未评价')
assert(decisionCopy('no_feasible_solution', 'baseline_infeasible').description.includes('硬约束'))
const file = compiler.parseComponent(fs.readFileSync('ruoyi-ui/src/views/carbon/energy/run.vue', 'utf8'))
assert.deepStrictEqual(compiler.compile(file.template.content).errors, [])
const view = { module: { exports: {} }, StoragePlanningResults: {}, describeDecision: decisionCopy }
vm.runInNewContext(file.script.content.replace(/^import .*$/gm, '').replace('export default', 'module.exports ='), view)
const computed = view.module.exports.computed
assert.strictEqual(computed.simulationOnly.call({ previewExtra: { result: { algorithm_context: { ready_for_conclusions: false } } } }), true)
assert.strictEqual(computed.simulationOnly.call({ previewExtra: {} }), false)
Object.assign(view, {
  previewImageArtifacts: () => [], primaryReportArtifact: () => null, previewTableArtifacts: () => [],
  previewSummaryArtifact: () => ({ relativePath: 'summary.json' }),
  blobValidate: blob => blob.type !== 'application/json',
  downloadArtifact: async () => new Blob([JSON.stringify({ algorithm_context: { ready_for_conclusions: false } })], { type: 'application/json' }),
  parseJsonObject: JSON.parse, jointPreviewTable: () => null
})
const page = {
  run: { status: 'succeeded', runId: 'test', runType: 'dispatch' }, artifacts: [],
  clearPreviewUrls() {}, structuredTables() { return [] }, skippedTableNames() { return [] }
}
view.module.exports.methods.loadPreviews.call(page).then(() => {
  assert.strictEqual(page.previewExtra.result.algorithm_context.ready_for_conclusions, false)
  assert.strictEqual(computed.simulationOnly.call(page), true)
  console.log('PASS: real zero; unavailable comparison; diagnostics; JSON artifact MIME; simulation status; Vue template')
}).catch(error => { console.error(error); process.exitCode = 1 })
