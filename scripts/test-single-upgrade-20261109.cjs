const assert = require('assert')
const fs = require('fs')
const vm = require('vm')
const compiler = require('./vue3/compiler.cjs')
function component(path) {
  const source = fs.readFileSync(path, 'utf8')
  const parsed = compiler.parseComponent(source)
  const compiled = compiler.compile(parsed.template.content)
  assert.deepStrictEqual(compiled.errors, [])
  const context = { module: { exports: {} }, scenarioName: value => value }
  vm.runInNewContext(parsed.script.content.replace(/^import .*$/gm, '').replace('export default', 'module.exports ='), context)
  return context.module.exports
}
const result = component('ruoyi-ui/src/views/carbon/singleTrain/run.vue')
const main = { controller_key: 'rhonn_nsmc', scenario_key: 's1', eligible: true, metrics: { storage_net_of_grid_import_energy_kWh: 2, simulation_dt_s: .0001, metric_schema_version: 'new' } }
const baseline = { controller_key: 'pi', controller_name: 'PI', scenario_key: 's1', eligible: true, metrics: { storage_net_of_grid_import_energy_kWh: 1, captured_energy_kWh: 100, simulation_dt_s: .0001, metric_schema_version: 'new' } }
const context = { selected: main, item: { run_type: 'comparison', cases: [main, baseline] }, number: n => String(n) }
assert(result.computed.comparison.call(context).includes('差值为 1 kWh'))
baseline.metrics.simulation_dt_s = .0002
assert(result.computed.comparison.call(context).includes('没有同口径'))
baseline.metrics.simulation_dt_s = .0001
delete main.metrics.storage_net_of_grid_import_energy_kWh
assert(result.computed.comparison.call(context).includes('历史案例'))
main.metrics.storage_net_of_grid_import_energy_kWh = 0
baseline.metrics.storage_net_of_grid_import_energy_kWh = 0
assert(result.computed.comparison.call(context).includes('差值为 0 kWh'))
const version = component('ruoyi-ui/src/views/carbon/singleTrain/VersionMaintenance.vue')
const parameters = { mass_kg: 100, provenance: { internal_number: 123 } }
const rows = version.methods.numericFields.call({ selected: { parameterMetadata: { train: [{ path: 'mass_kg', label: '列车质量', unit: 'kg', dataStatus: 'derived', provenance: '输入版本' }] } } }, parameters, 'train')
assert.strictEqual(rows.length, 1)
assert.strictEqual(rows[0].value, 100)
assert.strictEqual(rows[0].dataStatus, 'derived')
console.log('PASS: two Vue templates; net recovery, missing, zero, step compatibility, parameter provenance')

const create = component('ruoyi-ui/src/views/carbon/singleTrain/create.vue')
const eco = { viewActive: true, ready: true, loading: false, saving: false, presetVersion: 'v', versionId: 'v', isEco: true,
  eco: { ready: true, minKm: 0, maxKm: 594 }, ecoStart: 108, ecoEnd: 108.2, runtime: 40, terminalSpeed: 0,
  runType: 'eco_driving', keys: [], speed: 0, speedMin: 0, speedMax: 80, socPercent: 50, socMin: 10, socMax: 90 }
assert(create.computed.canSubmit.call(eco))
eco.ecoEnd = 108
assert(!create.computed.canSubmit.call(eco))
eco.ecoEnd = 108.2
eco.eco.ready = false
assert(!create.computed.canSubmit.call(eco))
context.isEco = true
context.item.cases = [{ controller_key: 'baseline', eligible: true, metrics: { section_net_energy_kwh: 10 } },
  { controller_key: 'optimized', eligible: true, metrics: { section_net_energy_kwh: 8 } }]
assert(result.computed.comparison.call(context).includes('减少 2 kWh'))
context.item.cases[1].eligible = false
assert(result.computed.comparison.call(context).includes('不生成节能结论'))
assert.strictEqual(result.methods.artifactName.call({ item: { cases: [] } }, { relative_path: '节能操纵对比.csv' }), '节能操纵对比.csv')
console.log('PASS: eco template; readiness, interval and zero-speed validation; comparison gates; named downloads')
