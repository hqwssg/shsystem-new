import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { monitoringWarnings, mergeMonitoringRows } from '../../ruoyi-ui/src/views/carbon/report/steps/monitoringImport.js'
import { reportRowChecks, mergeReportRows } from '../../ruoyi-ui/src/views/carbon/report/steps/reportImport.js'
const load = (name, globals) => {
  const file = new URL('../../ruoyi-ui/src/views/carbon/report/steps/' + name, import.meta.url)
  const script = readFileSync(file, 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1]
    .replace(/^import .*$/gm, '').replace('export default', 'module.exports =')
  const context = { module: { exports: {} }, ...globals }
  vm.runInNewContext(script, context)
  return context.module.exports
}
const tick = () => new Promise(resolve => setImmediate(resolve))
const saves = [], imports = [], messages = []
const assets = load('AssetsStep.vue', { ExcelImportBox: {}, monitoringWarnings, mergeMonitoringRows, reportRowChecks,
  saveSection: async (...args) => { saves.push(structuredClone(args)) } })
const state = { ...assets.data(), draft: { task: { id: 9, version: 3 } }, $message: {
  error: text => messages.push(text), success: text => messages.push(text)
}, $emit: () => {} }
Object.entries(assets.methods).forEach(([key, value]) => { state[key] = value.bind(state) })
Object.entries(assets.computed).forEach(([key, value]) => { Object.defineProperty(state, key, { get: value.bind(state) }) })
const rows = [{ name: '电表', model: 'A' }, { name: '电表', model: 'A' }, { name: '', location: '2#进线' }]
const box = load('ExcelImportBox.vue', { readMonitoringFile: async () => ({ rows, mergedContinuationRows: 0 }),
  readReportFile: async () => ({ rows: [{ name: '同名设备', model: 'A' }], importedCount: 1 }), mergeReportRows,
  importExcel: async (...args) => { imports.push(args) } })
const picker = { ...box.data(), type: 'monitoring', draft: state.draft, file: { name: 'monitoring.xlsx' },
  $message: state.$message, $emit: (event, result) => { if (event === 'preview') state.previewMonitoring(result) } }
Object.entries(box.methods).forEach(([key, value]) => { picker[key] = value.bind(picker) })
state.monitoring = [{ name: '页面尚未保存的设备', model: 'B' }]
picker.submit(); await tick()
assert.equal(imports.length, 0, 'Monitoring import must not call the database-writing import API')
assert.equal(saves.length, 0)
assert.equal(state.monitoring.length, 4)
assert.equal(state.monitoring[0].name, '页面尚未保存的设备')
assert.ok(state.monitoringImportNote.includes('尚未保存'))
picker.mode = 'overwrite'; picker.file = { name: 'monitoring.xlsx' }; picker.submit(); await tick()
assert.equal(state.monitoring.length, 3)
state.save(); await tick()
assert.equal(saves.length, 1, 'Duplicate and blank names must not block saving')
assert.equal(saves[0][2].data.monitoring[2].location, '2#进线')
state.monitoring[0].measurementRange = '测'.repeat(65)
state.save(); await tick()
assert.equal(saves.length, 1, 'Storage overflow must be reported before sending a save')
assert.ok(messages.some(text => text.includes('第1行') && text.includes('量程')))
assert.equal(state.monitoring[0].measurementRange.length, 65, 'No silent truncation')
state.monitoring[0].measurementRange = '测'.repeat(64)
state.monitoring.splice(1, 1)
state.save(); await tick()
assert.equal(saves.length, 2)
assert.equal(saves[1][2].data.monitoring.length, 2)
picker.type = 'equipment'; picker.currentRows = []; picker.$emit = () => {}; picker.submit(); await tick()
assert.equal(imports.length, 0, 'Equipment import now also previews locally')

let finish
const slow = load('ExcelImportBox.vue', { readMonitoringFile: () => new Promise(resolve => { finish = resolve }) })
let lateEvents = 0
const canceled = { ...slow.data(), file: {}, draft: state.draft, type: 'monitoring', $emit: () => lateEvents++, $message: state.$message }
Object.entries(slow.methods).forEach(([key, value]) => { canceled[key] = value.bind(canceled) })
canceled.submit(); canceled.close(); finish({ rows }); await tick()
assert.equal(lateEvents, 0, 'Closing a pending import must not replace page edits later')
console.log('Monitoring UI checks passed: preview-only import, unsaved rows, append/overwrite, editable warnings/save, no truncation, delete, cancel and equipment preview.')
