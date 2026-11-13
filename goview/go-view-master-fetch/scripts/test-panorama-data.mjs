import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const calls = []
globalThis.__panoramaRequest = (params, signal) => new Promise((resolve, reject) => calls.push({ params, signal, resolve, reject }))
globalThis.__panoramaDemo = JSON.parse(readFileSync(new URL('../src/assets/dashboard/panorama-demo.json', import.meta.url), 'utf8'))
try {
  const source = readFileSync(new URL('../src/assets/dashboard/dashboardLiveData.ts', import.meta.url), 'utf8')
    .replace("import { ref, shallowRef } from 'vue'", 'const ref = value => ({ value }); const shallowRef = ref')
    .replace("import { requestDashboard } from './dashboardRequest'", 'const requestDashboard = globalThis.__panoramaRequest')
    .replace("import demoSnapshot from './panorama-demo.json'", 'const demoSnapshot = globalThis.__panoramaDemo')
  const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
  const api = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'))
  const { ensureDashboardLive: load, dashboardData: data, dashboardStatus: status, dashboardLoadError: error } = api
  const body = () => ({ code: 200, data: { periodLabel: 'test', overall: api.emptyBucket(), stations: {}, rank: [] } })
  const first = load()
  assert.equal(load(), first, 'All panels share one pending request')
  assert.equal(calls.length, 1)
  calls[0].resolve({ code: 403 }); await first
  assert.equal(status.value, 'error'); assert.match(error.value, /权限/)
  assert.deepEqual(data.value.rank, [])
  const retry = load()
  const zero = body(); zero.data.stations.station = api.emptyBucket(); zero.data.rank = [['station', '0', '0']]
  calls[1].resolve(zero); await retry
  assert.equal(status.value, 'ready', 'Real zero with source records is valid')
  assert.equal(data.value.overall.kpi.yearTotal, 0)
  await load(); assert.equal(calls.length, 2, 'Successful snapshot is shared within its cache lifetime')
  const empty = load(true)
  assert.equal(status.value, 'loading'); assert.deepEqual(data.value.rank, [], 'Refresh immediately clears old rankings')
  calls[2].resolve(body()); await empty
  assert.equal(status.value, 'empty', 'No records is distinct from real zero')
  const old = load(true), latest = load(true)
  assert.equal(calls[3].signal.aborted, true)
  const good = body(); good.data.overall.kpi.yearTotal = 123
  calls[4].resolve(good); await latest
  calls[3].resolve(zero); await old
  assert.equal(data.value.overall.kpi.yearTotal, 123, 'Aborted/late response cannot replace the latest data')
  const failure = load(true)
  calls[5].reject({ response: { status: 401 } }); await failure
  assert.equal(status.value, 'error'); assert.match(error.value, /登录/)
  assert.deepEqual(data.value.rank, [])
  const wrongShape = load()
  calls[6].resolve({ code: 200, data: { annualRows: [], coverage: [] } }); await wrongShape
  assert.equal(status.value, 'error', 'Management payload cannot be mistaken for panorama data')
  const beforeDemo = calls.length
  await api.setDashboardMode('demo')
  assert.equal(calls.length, beforeDemo, 'Demo mode must never request business data')
  assert.equal(data.value.rank.length, 35)
  assert.match(data.value.periodLabel, /演示数据/)
  assert.equal(status.value, 'ready')
  data.value.rank.pop()
  await load(true)
  assert.equal(data.value.rank.length, 35, 'Refresh clones the immutable demo snapshot')
  const inFlight = api.setDashboardMode('real')
  assert.deepEqual(data.value.rank, [], 'Formal mode clears demo immediately')
  const last = calls.at(-1)
  await api.setDashboardMode('demo')
  assert.equal(last.signal.aborted, true)
  last.resolve(good); await inFlight
  assert.equal(data.value.rank.length, 35, 'Late formal response cannot replace demo')
  const denied = api.setDashboardMode('real')
  calls.at(-1).reject({ response: { status: 403 } }); await denied
  assert.equal(status.value, 'error')
  assert.deepEqual(data.value.rank, [], 'Formal failure must not fall back to demo')
  assert.throws(() => api.setDashboardMode('other'), /Invalid/)
  console.log('Panorama data checks passed: shared authenticated snapshot, error/retry, real zero vs missing, refresh clearing, stale response and wrong payload.')
} finally { delete globalThis.__panoramaRequest; delete globalThis.__panoramaDemo }
