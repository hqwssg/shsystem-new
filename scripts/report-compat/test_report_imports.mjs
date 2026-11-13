import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { reportRowChecks, mergeReportRows, parseReportWorkbook, readReportFile, numberValue } from '../../ruoyi-ui/src/views/carbon/report/steps/reportImport.js'
const require = createRequire(new URL('../../ruoyi-ui/package.json', import.meta.url))
const XLSX = require('xlsx')
const makeBook = rows => { const b = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(b, XLSX.utils.aoa_to_sheet(rows), '导入'); return b }
const dup = [{ name: '空压机', model: 'A' }, { name: '空压机', model: 'B' }, { name: '', model: 'C' }]
assert.equal(mergeReportRows(dup, dup, 'equipment', 'append').length, 6)
assert.equal(mergeReportRows(dup, dup, 'equipment', 'overwrite').length, 3)
assert.equal(reportRowChecks(dup, 'equipment')[2].errors.length, 0)
assert.ok(reportRowChecks([{ name: 'a', model: '长'.repeat(129) }], 'equipment')[0].errors.length)
assert.ok(reportRowChecks([{ name: 'a', quantity: '1.00001' }], 'equipment')[0].errors.length)

const b = makeBook([['名称', '型号'], ['电表', 'A'], ['', 'B']])
b.Sheets['导入']['!merges'] = [{ s: { r: 1, c: 0 }, e: { r: 2, c: 0 } }]
const eq = parseReportWorkbook(b, 'equipment').rows
assert.equal(eq.length, 2); assert.equal(eq[1].name, '电表'); assert.equal(eq[1].model, 'B')
assert.throws(() => parseReportWorkbook(makeBook([['名称', '数量', 'quantity'], ['a', 10, 20]]), 'equipment'), /重复表头/)
const formula = makeBook([['名称', '数量'], ['a', 3]])
formula.Sheets['导入'].B2.f = '1+2'
assert.equal(parseReportWorkbook(formula, 'equipment').rows[0].quantity, '3')
delete formula.Sheets['导入'].B2.v
assert.throws(() => parseReportWorkbook(formula, 'equipment'), /第2行.*公式没有计算结果/)
assert.throws(() => parseReportWorkbook(makeBook([['名称', '数量'], ['a', 'bad']]), 'workload'), /第2行.*数量/)
const parsed = parseReportWorkbook(makeBook([['名称', '数量', '单位'], ['里程', 100, 'km'], ['作业', 0, '次']]), 'workload')
assert.equal(parsed.rows.length, 1); assert.ok(parsed.notices[0].includes('第3行'))
const before = [{ name: '里程', quantity: '', unit: 'km' }]
const merged = mergeReportRows(before, parsed.rows, 'workload', 'append')
assert.equal(merged[0].quantity, '100'); assert.equal(before[0].quantity, '')
assert.throws(() => mergeReportRows(merged, [{ name: '里程', quantity: '200', unit: 'km' }], 'workload', 'append'), /不同数量/)
assert.throws(() => mergeReportRows(merged, [{ name: '里程', quantity: '100', unit: 'm' }], 'workload', 'append'), /单位/)
assert.equal(mergeReportRows(merged, [{ name: '里程', quantity: '1e2', unit: 'km' }], 'workload', 'append').length, 1)
assert.throws(() => mergeReportRows([{ name: 'x', quantity: '999999999999.999998', unit: '次' }], [{ name: 'x', quantity: '999999999999.999999', unit: '次' }], 'workload', 'append'), /不同数量/)
assert.throws(() => mergeReportRows([], [{ name: 'x', quantity: '1', unit: 'm' }, { name: 'x', quantity: '2', unit: 'm' }], 'workload', 'overwrite'), /不同数量/)
const heat = [{ id: 1, site: '站点', heatingAreaM2: '100', heatCoefficient: '', normalizedValue: 50 }]
const filled = mergeReportRows(heat, [{ site: '站点', heatingAreaM2: '', heatCoefficient: '0.8' }], 'heat', 'append')
assert.equal(filled[0].heatCoefficient, '0.8'); assert.equal(filled[0].normalizedValue, 50); assert.equal(heat[0].heatCoefficient, '')
assert.throws(() => mergeReportRows([...heat, { ...heat[0], id: 2 }], [{ site: '站点', heatCoefficient: '1' }], 'heat', 'overwrite'), /多条/)
const h = mergeReportRows(filled, [{ site: '新站点', heatingAreaM2: '10', heatCoefficient: '1', normalizedValue: 999 }], 'heat', 'append')
assert.equal(h[1].normalizedValue, null)

const load = (name, globals) => {
  const script = readFileSync(new URL('../../ruoyi-ui/src/views/carbon/report/steps/' + name + '.vue', import.meta.url), 'utf8')
    .match(/<script>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '').replace('export default', 'module.exports =')
  const context = { module: { exports: {} }, ...globals }; vm.runInNewContext(script, context); return context.module.exports
}
const tick = () => new Promise(resolve => setImmediate(resolve))
for (const type of ['equipment', 'workload', 'heat']) {
  let preview, writes = 0
  const incoming = type === 'equipment' ? dup : type === 'workload' ? parsed.rows : [{ site: '站点', heatCoefficient: '0.8' }]
  const component = load('ExcelImportBox', { mergeReportRows, readReportFile: async () => ({ rows: incoming, importedCount: incoming.length }),
    importExcel: () => writes++ })
  const state = { ...component.data(), type, file: {}, mode: 'append', currentRows: type === 'heat' ? heat : [], draft: { task: { id: 9, version: 2 } },
    $message: { success: () => {}, error: error => { throw Error(error) } }, $emit: (_, data) => { preview = data } }
  Object.entries(component.methods).forEach(([key, method]) => { state[key] = method.bind(state) })
  state.submit(); await tick()
  assert.equal(writes, 0); assert.ok(preview.rows.length)
}
const saves = []
const component = load('ActivityStep', { reportRowChecks, numberValue, reportPeriod: () => null, reportPeriodLabel: () => '', ExcelImportBox: {},
  saveSection: async (...args) => saves.push(structuredClone(args)) })
const state = { ...component.data(), draft: { task: { id: 9, version: 2 }, heat },
  $message: { success: () => {}, error: e => { throw Error(e) } }, $emit: () => {} }
Object.entries(component.methods).forEach(([key, method]) => { state[key] = method.bind(state) })
Object.entries(component.computed).forEach(([key, method]) => Object.defineProperty(state, key, { get: method.bind(state) }))
state.previewWorkload({ rows: merged, importedCount: 1, notices: parsed.notices })
state.saveWorkload(); await tick()
assert.equal(saves[0][2].data.workload[0].quantity, '100', 'Save sends the imported rows, not the stale pre-import draft')
state.hydrateHeat(heat)
state.previewHeat({ rows: filled, importedCount: 1 })
component.watch['draft.heat'].call(state, [{ ...heat[0], heatCoefficient: '9' }])
assert.equal(state.heat[0].heatCoefficient, '0.8', 'A draft refresh must not discard unsaved heat edits')
state.saveHeat(); await tick()
assert.equal(saves[1][2].data.heat[0].heatCoefficient, '0.8')
assert.equal(saves[1][2].data.heat[0].normalizedValue, undefined)
state.workload[0].quantity = '1,000'
state.saveWorkload(); await tick()
assert.equal(saves[2][2].data.workload[0].quantity, '1000', 'A manually typed thousands separator must not drop the workload')
assert.throws(() => mergeReportRows(heat, [{ site: 'x' }, { site: 'x' }], 'heat', 'overwrite'), /站点重复/)
const formatted = makeBook([['名称', '型号'], ['设备', 1]])
formatted.Sheets['导入'].B2.w = '0001'
assert.equal(parseReportWorkbook(formatted, 'equipment').rows[0].model, '0001')
await assert.rejects(() => readReportFile({ name: 'broken.xlsx', arrayBuffer: async () => new Uint8Array([0, 1, 2]) }, 'equipment'))
console.log('Report import checks passed: local previews/no writes, duplicate equipment, merged names, workload fill/conflicts/precision, heat identity/GJ, headers/formulas/row errors and correct saved payloads.')
