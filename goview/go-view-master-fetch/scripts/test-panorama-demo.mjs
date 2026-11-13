import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { buildPanoramaDemo } from '../src/assets/dashboard/panoramaDemo.mjs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const snapshot = JSON.parse(read('../src/assets/dashboard/panorama-demo.json'))
const route = JSON.parse(read('../src/packages/components/Charts/Maps/RailwayCarbonMap/data.json'))
const names = route.points.points.map(point => point.name)
assert.deepEqual(snapshot, buildPanoramaDemo(names), 'Initialization must be deterministic and idempotent')
assert.equal(snapshot.isDemo, true)
assert.equal(snapshot.rank.length, names.length)
const near = (a, b) => assert.ok(Math.abs(a - b) < 0.001, `${a} != ${b}`)
let all = 0
for (const name of names) {
  const bucket = snapshot.stations[name]
  assert.equal(bucket.line.source.length, 12)
  assert.deepEqual(bucket.surface.years, [2024, 2025, 2026])
  near(bucket.line.source.reduce((n, row) => n + row.actual, 0), bucket.kpi.yearTotal)
  near(bucket.surface.values[2].reduce((a, b) => a + b, 0), bucket.kpi.yearTotal)
  for (const pie of Object.values(bucket.pies)) near(pie.source.reduce((n, row) => n + row.value, 0), bucket.kpi.yearTotal)
  near(snapshot.mapEmissions[name].carbonEmission, bucket.kpi.yearTotal)
  const rank = snapshot.rank.find(row => row[0] === name)
  near(Number(rank[1]), bucket.kpi.yearTotal)
  all += bucket.kpi.yearTotal
}
near(all, snapshot.overall.kpi.yearTotal)
snapshot.overall.line.source.forEach((row, month) => near(row.actual, names.reduce((n, name) => n + snapshot.stations[name].line.source[month].actual, 0)))
for (const pie of Object.values(snapshot.overall.pies)) near(pie.source.reduce((n, row) => n + row.value, 0), snapshot.overall.kpi.yearTotal)
const control = read('../src/views/preview/components/PanoramaDataStatus/index.vue')
assert.match(control, /setPreviewStationScope\(store, 'overall'\)/)
assert.match(control, /option value="real"/)
assert.match(control, /option value="demo"/)
const map = read('../src/packages/components/Charts/Maps/RailwayCarbonMap/index.vue')
assert.match(map, /if \(!dashboardData.value.stations\[stationName\]\) return/)
const canonical = JSON.parse(read('../public/templates/shuohuang-carbon-dashboard.json'))
assert.equal(canonical.componentList.find(c => c.id === 'dash-map-001').option.lineDisplayMode, 'monitorGradient')
console.log('Panorama demo checks passed: 35 exact map names, 3 complete years, consistent totals/structure/ranking, deterministic initialization and mode controls.')
