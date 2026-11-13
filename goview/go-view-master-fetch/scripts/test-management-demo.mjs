import assert from 'node:assert/strict'
import { buildManagementDemo } from '../src/assets/dashboard/managementDemo.mjs'
import { managementDataset } from '../src/assets/dashboard/managementDatasets.mjs'
const demo = buildManagementDemo(2026)
assert.equal(demo.isDemo, true)
assert.equal(demo.annualRows.length, 3); assert.equal(demo.monthlyRows.length, 36)
assert.equal(demo.companies.length, 3); assert.equal(Object.keys(demo.sources).length, 5)
assert.ok(Math.abs(demo.carbon - demo.monthlyRows.reduce((sum, row) => sum + row.carbon, 0)) < 0.000001)
for (const row of demo.annualRows) {
  const months = demo.monthlyRows.filter(m => m.orgId === row.orgId)
  assert.equal(months.length, 12)
  assert.ok(Math.abs(row.carbon - months.reduce((sum, m) => sum + m.carbon, 0)) < 0.000001)
  row.energies.forEach((e, i) => {
    assert.ok(Math.abs(e.energy - months.reduce((sum, m) => sum + m.energies[i].energy, 0)) < 0.000001)
    assert.ok(e.energy > 0 && e.carbon > 0)
  })
}
assert.deepEqual(buildManagementDemo(2026), demo, 'Refresh must be deterministic')
assert.notEqual(buildManagementDemo(2025).carbon, demo.carbon)
const one = buildManagementDemo(2026, 'demo-jiliang')
assert.equal(one.annualRows.length, 1); assert.equal(one.monthlyRows.length, 12)
assert.equal(one.annualRows[0].orgName, '机辆分公司')
for (const role of ['rank', 'sources', 'trend', 'energyCompare', 'companyStructure', 'monthlyStructure']) {
  const data = managementDataset(role, demo)
  assert.ok(data.source.length > 0, role)
}
assert.ok(managementDataset('basis', demo).includes('演示数据'))
assert.ok(managementDataset('dataSource', demo).includes('非实际') || managementDataset('dataSource', demo).includes('模拟生成'))
console.log('Demo checks passed: 3 companies, 12 months, 5 sources, exact aggregates, filters, all 6 datasets and visible labels')
