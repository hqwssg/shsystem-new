const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const compiler = require('./vue3/compiler.cjs')

const source = fs.readFileSync('ruoyi-ui/src/views/carbon/data-entry.vue', 'utf8')
const parsed = compiler.parseComponent(source)
assert.deepEqual(compiler.compile(parsed.template.content).errors, [])
const sandbox = { module: { exports: {} }, formatMeasurementUnit: value => value, hasAnyPermission: (list, wanted) => wanted.some(p => list.includes(p)) }
vm.runInNewContext(parsed.script.content.replace(/^import .*$/gm, '').replace('export default', 'module.exports ='), sandbox)
const component = sandbox.module.exports
const node = { nodeType: 'meter', meterReadingMethod: 0, collectionPointType: 'electric', collectionPointId: 7 }
const ctx = { selectedNode: node, ...component.methods }
assert.equal(component.computed.canEnterSelected.call(ctx), true, 'unlinked manual collection point remains editable')
assert.equal(component.computed.canBatchImportSelected.call(ctx), true)
const row = { node, periodStart: '2026-10-01', periodEnd: '2026-10-31', activityValue: 0 }
assert.equal(component.methods.importRowError.call(ctx, row), '', 'zero and no emission factor/model link are valid')
for (const activityValue of [-1, NaN, Infinity, null]) {
  assert.notEqual(component.methods.importRowError.call(ctx, { ...row, activityValue }), '')
}
assert.notEqual(component.methods.importRowError.call(ctx, { ...row, periodEnd: '2026-09-30' }), '')
assert.notEqual(component.methods.importRowError.call(ctx, { ...row, node: { ...node, meterReadingMethod: 1 } }), '')
ctx.selectedNode = { ...node, meterReadingMethod: 1 }
assert.equal(component.computed.canEnterSelected.call(ctx), false)
assert.equal(component.computed.canBatchImportSelected.call(ctx), false)
for (const permissions of [[], ['carbon:data:view']]) {
  assert.equal(component.computed.canEditData.call({ isAdmin: false, $store: { getters: { permissions } } }), false)
}
assert.equal(component.computed.canEditData.call({ isAdmin: false, $store: { getters: { permissions: ['carbon:data:edit'] } } }), true)
console.log('PASS: unlinked manual points, batch import, zero/negative readings, automatic points and edit permissions')
