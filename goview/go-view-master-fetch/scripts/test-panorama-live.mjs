import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = relative => readFileSync(new URL(relative, import.meta.url), 'utf8')
const request = read('../src/assets/dashboard/dashboardRequest.ts')
const live = read('../src/assets/dashboard/dashboardLiveData.ts')
const vite = read('../vite.config.ts')
const switcher = read('../src/views/preview/components/DashboardSwitcher/index.vue')
const wrapper = read('../src/views/preview/wrapper.vue')

assert.match(request, /from '@\/api\/axios'/)
assert.match(request, /baseURL:\s*''/)
assert.doesNotMatch(live, /\bfetch\s*\(/)
assert.match(live, /requestDashboard\(\{\}, signal\)/)
assert.match(vite, /['"]\/carbon-screen['"]/)
assert.match(vite, /VITE_CARBON_SCREEN_PATH/)
assert.match(vite, /replace\(\/\^\\\/carbon-screen\//)
assert.match(live, /dashboardLoadError/)
assert.match(switcher, /projectListApi/)
assert.match(switcher, /切换大屏/)
assert.match(switcher, /position:\s*fixed/)
assert.doesNotMatch(switcher, /onMounted\(loadProjects\)/)
assert.match(switcher, /if \(!loginCheck\(\)\)/)
const axios = read('../src/api/axios.ts')
assert.match(axios, /status === 401 && !isPreview\(\)/)
assert.match(switcher, /PreviewEnum\.CHART_PREVIEW_NAME/)
assert.match(wrapper, /<dashboard-switcher/)
assert.match(wrapper, /previewKey/)

const compatibleComponents = [
  ['../src/packages/components/Charts/Lines/LineCommon/index.vue', 'dash-line-001', "kind: 'line'"],
  ['../src/packages/components/Charts/Pies/PieCommon/index.vue', 'dash-pie-001', "kind: 'pie'"],
  ['../src/packages/components/Decorates/Three/ThreeCarbonSurface/index.vue', 'dash-3d-001', "kind: 'surface'"]
]

for (const [path, id, kind] of compatibleComponents) {
  const source = read(path)
  assert.match(source, /useStationScopeSync/)
  assert.ok(source.includes(id), `${path} must recognize the existing panorama component ID`)
  assert.ok(source.includes(kind), `${path} must apply the shared live-data bucket`)
}

console.log('Panorama live checks passed: authenticated request and existing-canvas component compatibility')
