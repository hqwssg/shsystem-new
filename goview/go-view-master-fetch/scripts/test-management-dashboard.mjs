import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { buildManagementDashboardStorage } from './generate-management-dashboard.mjs'
import { managementDataset as dataset, managementEnergyUnits } from '../src/assets/dashboard/managementDatasets.mjs'
const storage = buildManagementDashboardStorage()
assert.equal(new Set(storage.componentList.map(c => c.id)).size, storage.componentList.length)
for (const c of storage.componentList) {
  assert.ok(c.id.startsWith('management-'))
  assert.ok(c.attr.x >= 0 && c.attr.y >= 0 && c.attr.x + c.attr.w <= 1920 && c.attr.y + c.attr.h <= 1080)
  assert.notEqual(c.key, 'RailwayCarbonMap')
}
assert.equal(storage.componentList.filter(c => c.key === 'ManagementStatus').length, 1)
assert.equal(storage.componentList.find(c => c.id === 'management-controls').option.dataMode, 'demo')
assert.equal(storage.componentList.filter(c => c.key === 'TableScrollBoard').length, 0)
assert.ok(!storage.componentList.some(c => ['coverage', 'quality', 'issues', 'recent'].includes(c.option.managementRole)))
for (const role of ['energyCompare', 'companyStructure', 'monthlyStructure']) assert.ok(storage.componentList.some(c => c.option.managementRole === role))
assert.equal(dataset('carbon', null), '暂无数据')
assert.equal(dataset('carbon', { carbon: 0 }), '0')
const sample = { year: 2025, carbon: 8, annualRows: [{ orgName: '测试公司', carbon: 8, energies: [
  { subcategory: 'PE_PF', unitName: 'MWh', energy: 10, carbon: 5 }, { subcategory: 'FF_D', unitName: 't', energy: 2, carbon: 1 }, { subcategory: 'FF_G', unitName: 'L', energy: 3, carbon: 2 }
] }], monthlyRows: [{ period: '2025-01', carbon: 3, energies: [{ subcategory: 'PE_PF', carbon: 3 }] }, { period: '2025-01', carbon: 5, energies: [{ subcategory: 'FF_D', carbon: 5 }] }, { period: '2025-03', carbon: 0, energies: [{ subcategory: 'PH_HD', carbon: 0 }] }] }
assert.equal(dataset('fuel', sample), '2 t / 3 L')
assert.equal(dataset('electricity', sample), '10 MWh')
const trend = dataset('trend', sample).source
assert.equal(trend[0][1], 8); assert.equal(trend[1][1], null); assert.equal(trend[2][1], 0)
assert.deepEqual(dataset('rank', sample).source, [['测试公司', 8]])
assert.deepEqual(managementEnergyUnits(sample, 'fuel'), ['L', 't'])
assert.deepEqual(dataset('energyCompare', sample, { energyType: 'fuel', energyUnit: 't' }).source, [['测试公司', 2]])
assert.deepEqual(dataset('energyCompare', sample, { energyType: 'fuel', energyUnit: 'L' }).source, [['测试公司', 3]])
assert.deepEqual(dataset('companyStructure', sample).source, [['测试公司', 5, 3, null, null]])
const structure = dataset('monthlyStructure', sample).source
assert.deepEqual(structure[0], ['2025-01', 3, 5, null, null])
assert.deepEqual(structure[1], ['2025-02', null, null, null, null])
assert.deepEqual(structure[2], ['2025-03', null, null, 0, null])
assert.equal(dataset('energyCompareEmpty', sample, { energyType: 'heat' }), '暂无同单位能源消耗数据')
assert.ok(dataset('issues', { problems: ['<img src=x onerror=alert(1)>'] })[0][1].startsWith('&lt;'))
assert.equal(readFileSync(new URL('../public/templates/shuohuang-management-dashboard.json', import.meta.url), 'utf8'), JSON.stringify(storage, null, 2) + '\n')
console.log('Management template checks passed: layout, IDs, empty/zero, units, month gaps, escaping, reproducibility')
