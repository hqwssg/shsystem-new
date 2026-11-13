import assert from 'node:assert/strict'
import { readFile, mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { planPanoramaRepair, repairProject } from './repair-panorama.mjs'

const canonical = JSON.parse(await readFile(new URL('../../goview/go-view-master-fetch/public/templates/shuohuang-carbon-dashboard.json', import.meta.url), 'utf8'))
const old = structuredClone(canonical)
old.editCanvasConfig.projectId = '123'
const pie = old.componentList.find(item => item.id === 'dash-pie-001')
pie.attr.x = 777; pie.option.series[0].radius = ['10%', '20%']
pie.option.dataset = { dimensions: ['name', 'value'], source: [{ name: 'existing', value: 42 }] }
pie.request.requestDataType = 0
old.componentList.push({ id: 'custom', key: 'TextCommon', option: { dataset: 'custom text' }, attr: { x: 99 } })
const snapshot = JSON.stringify(old), plan = planPanoramaRepair(old, canonical)
const mapOld = structuredClone(old)
const oldMap = mapOld.componentList.find(item => item.id === 'dash-map-001')
oldMap.option.lineDisplayMode = 'flow'
oldMap.option.lineWidth = 2
const mapPlan = planPanoramaRepair(mapOld, canonical, false, true)
assert.deepEqual(mapPlan.changes, ['dash-map-001'])
assert.equal(mapPlan.output.componentList.find(item => item.id === oldMap.id).option.lineDisplayMode, 'monitorGradient')
assert.equal(mapPlan.output.componentList.find(item => item.id === oldMap.id).option.lineWidth, 8)
assert.deepEqual(mapPlan.output.componentList.filter(item => item.id !== oldMap.id), mapOld.componentList.filter(item => item.id !== oldMap.id))
assert.deepEqual(mapPlan.output.componentList.find(item => item.id === oldMap.id).option.dataset, oldMap.option.dataset)
assert.deepEqual(planPanoramaRepair(mapPlan.output, canonical, false, true).changes, [])
assert.equal(JSON.stringify(old), snapshot)
const fixed = plan.output.componentList.find(item => item.id === pie.id)
assert.equal(fixed.attr.x, 777)
assert.deepEqual(fixed.option.dataset, pie.option.dataset)
assert.deepEqual(fixed.option.series, canonical.componentList.find(item => item.id === pie.id).option.series)
assert.equal(fixed.request.requestDataType, 1)
assert.deepEqual(plan.output.componentList.at(-1), old.componentList.at(-1))
assert.deepEqual(planPanoramaRepair(plan.output, canonical).changes, [])
assert.notEqual(planPanoramaRepair(old, canonical, true).output.componentList.find(item => item.id === pie.id).attr.x, 777)
assert.throws(() => planPanoramaRepair({ componentList: [] }, canonical), /supported panorama/)
const backupDir = await mkdtemp(join(tmpdir(), 'panorama-repair-test-'))
let stored = snapshot, writes = 0
const request = async (url, config = {}) => {
  if (config.method === 'POST') { writes++; stored = config.body.get('content') }
  return { ok: true, status: 200, json: async () => ({ code: 200, data: { id: '123', state: 1, content: stored } }) }
}
const options = { base: 'http://example.invalid/api/goview', id: '123', canonical, headers: { Authorization: 'Bearer synthetic-test-token' }, backupDir }
assert.equal((await repairProject(options, request)).mode, 'READ_ONLY'); assert.equal(writes, 0)
const applied = await repairProject({ ...options, apply: true }, request)
assert.equal(applied.mode, 'APPLIED_AND_VERIFIED'); assert.equal(writes, 1)
assert.equal(JSON.parse(await readFile(applied.backup, 'utf8')).content, snapshot)
assert.deepEqual(JSON.parse(stored), plan.output)
let reads = 0
await assert.rejects(() => repairProject({ ...options, apply: true }, async () => ({ ok: true, json: async () => ({ code: 200,
  data: { content: ++reads === 1 ? snapshot : JSON.stringify(canonical) } }) })), /changed during inspection/)
await assert.rejects(() => repairProject({ ...options, apply: true, headers: {} }, request), /credentials/)
console.log('Panorama repair checks passed: dry-run, exact target signature, style/bindings, preserved data/layout/custom components, optional layout, idempotence, backup/save verification and concurrent-edit rejection. Mock requests only.')
