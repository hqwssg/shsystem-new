import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
const original = { requestDashboard: globalThis.__requestDashboard, setInterval: globalThis.setInterval, clearInterval: globalThis.clearInterval }
const pending = []
let intervals = 0, clears = 0
globalThis.__requestDashboard = (params, signal) => new Promise(resolve => pending.push({ params, signal, resolve }))
globalThis.setInterval = () => ++intervals
globalThis.clearInterval = () => { clears++ }
try {
  const source = readFileSync(new URL('../src/assets/dashboard/managementLive.ts', import.meta.url), 'utf8')
    .replace("import { reactive } from 'vue'", 'const reactive = value => value')
    .replace("'./managementDemo.mjs'", JSON.stringify(new URL('../src/assets/dashboard/managementDemo.mjs', import.meta.url).href))
    .replace("import { requestDashboard } from './dashboardRequest'", 'const requestDashboard = globalThis.__requestDashboard')
  const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
  const { managementLive: state, acquireManagement: acquire, refreshManagement: refresh } = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'))
  const release1 = acquire(), release2 = acquire()
  assert.equal(pending.length, 1); assert.equal(intervals, 1)
  assert.equal(pending[0].params.view, 'management')
  state.year = '2025'; state.companyId = '3030'
  const latest = refresh()
  assert.equal(pending[0].signal.aborted, true)
  assert.equal(state.data, null)
  const good = { year: 2025, coverage: [], companies: [], years: [2025], carbon: 0 }
  assert.deepEqual(pending[1].params, { view: 'management', year: '2025', companyId: '3030' })
  pending[1].resolve({ code: 200, data: good }); await latest
  pending[0].resolve({ code: 200, data: { ...good, year: 2024 } })
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(state.data.year, 2025); assert.equal(state.data.carbon, 0)
  const invalid = refresh()
  pending[2].resolve({ code: 200, data: { overall: {} } }); await invalid
  assert.equal(state.data, null); assert.ok(state.error.includes('加载失败'))
  release1(); assert.equal(clears, 0); release2(); assert.equal(clears, 1)
  const releaseDemo = acquire('demo')
  assert.equal(pending.length, 3, 'Demo mode must not query the business API')
  assert.equal(state.data.isDemo, true); assert.equal(state.data.monthlyRows.length, 36)
  state.companyId = 'demo-jiliang'; await refresh()
  assert.equal(state.data.annualRows.length, 1)
  state.dataMode = 'real'; state.companyId = ''; state.year = ''
  const realAgain = refresh()
  assert.equal(state.data, null, 'Switching to real must clear all demo values')
  pending[3].resolve({ code: 500 }); await realAgain
  assert.equal(state.data, null); assert.ok(state.error, 'Real mode failure must not fall back to demo')
  releaseDemo()
  console.log('Management live checks passed: one request/timer, abort, stale response, scope params, empty on failure, cleanup')
} finally {
  globalThis.__requestDashboard = original.requestDashboard
  globalThis.setInterval = original.setInterval
  globalThis.clearInterval = original.clearInterval
}
