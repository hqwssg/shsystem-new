import { reactive } from 'vue'
import { buildManagementDemo } from './managementDemo.mjs'
import { requestDashboard } from './dashboardRequest'

export const managementLive = reactive({ data: null as any, loading: false, error: '', year: '', companyId: '', energyType: 'electricity', energyUnit: '', dataMode: 'real' })
let users = 0
let timer: ReturnType<typeof setInterval> | undefined
let controller: AbortController | undefined
let generation = 0
let configured = false

export async function refreshManagement() {
  const current = ++generation
  controller?.abort()
  controller = new AbortController()
  managementLive.data = null
  managementLive.loading = true
  managementLive.error = ''
  if (managementLive.dataMode === 'demo') {
    const data = buildManagementDemo(managementLive.year, managementLive.companyId)
    managementLive.data = data
    managementLive.year = String(data.year)
    managementLive.loading = false
    return
  }
  const params: Record<string, string> = { view: 'management' }
  if (managementLive.year) params.year = managementLive.year
  if (managementLive.companyId) params.companyId = managementLive.companyId
  try {
    const body = await requestDashboard(params, controller.signal)
    if (body.code !== 200 || !body.data || !Array.isArray(body.data.coverage)
      || !Array.isArray(body.data.companies) || !Array.isArray(body.data.years)) throw new Error(body.msg || '管理版接口尚未就绪')
    if (current !== generation) return
    managementLive.data = body.data
    managementLive.year = String(body.data.year)
  } catch (error: any) {
    if (current === generation && error?.name !== 'AbortError') managementLive.error = '加载失败，请检查管理版接口和服务连接'
  } finally {
    if (current === generation) managementLive.loading = false
  }
}

export function acquireManagement(initialMode?: string) {
  const first = users++ === 0
  let changed = false
  if (!configured && ['demo', 'real'].includes(initialMode || '')) {
    configured = true
    changed = managementLive.dataMode !== initialMode
    managementLive.dataMode = initialMode!
    if (changed) { managementLive.companyId = ''; managementLive.year = '' }
  }
  if (first || changed) void refreshManagement()
  if (first) {
    timer = setInterval(() => { if (!managementLive.loading) void refreshManagement() }, 60000)
  }
  return () => {
    if (--users === 0) { clearInterval(timer); controller?.abort(); generation++; configured = false; managementLive.loading = false }
  }
}
