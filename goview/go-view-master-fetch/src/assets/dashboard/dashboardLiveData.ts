import { ref, shallowRef } from 'vue'
import { requestDashboard } from './dashboardRequest'
import demoSnapshot from './panorama-demo.json'

export interface DashboardPie {
  dimensions: string[]
  source: Array<{ name: string; value: number }>
}

export interface DashboardBucket {
  kpi: {
    yearTotal: number
    monthTotal: number
    yoyPercent: number
    pointCount: number
    intensity: number
  }
  line: {
    dimensions: string[]
    source: Array<{ month: string; actual: number | null; forecast: null }>
  }
  surface: {
    timeType: string
    years: number[]
    times: string[]
    values: number[][]
    unit: string
  }
  pies: {
    source: DashboardPie
    type: DashboardPie
    segment: DashboardPie
  }
}

export interface DashboardLive {
  periodLabel: string
  overall: DashboardBucket
  stations: Record<string, DashboardBucket>
  mapEmissions: Record<string, { carbonEmission: number; carbonIntensity: number }>
  rank: string[][]
}

const MONTH_LABELS = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']

export const periodLabel = ref('')
export const dashboardLoadError = ref('')
export const dashboardMode = ref<'real' | 'demo'>('real')

export const dashboardStatus = ref<'idle' | 'loading' | 'ready' | 'empty' | 'error'>('idle')
export const dashboardData = shallowRef<DashboardLive>(emptyLive())
let pending: Promise<DashboardLive> | null = null
let generation = 0
let loadedAt = 0
let controller: AbortController | undefined

export function currentDashboard(): DashboardLive {
  return dashboardData.value
}

export function setDashboardMode(mode: 'real' | 'demo'): Promise<DashboardLive> {
  if (!['real', 'demo'].includes(mode)) throw new Error('Invalid panorama data mode')
  dashboardMode.value = mode
  return ensureDashboardLive(true)
}

export function emptyBucket(): DashboardBucket {
  return {
    kpi: { yearTotal: 0, monthTotal: 0, yoyPercent: 0, pointCount: 0, intensity: 0 },
    line: { dimensions: ['month', 'actual', 'forecast'], source: [] },
    surface: { timeType: 'month', years: [], times: [...MONTH_LABELS], values: [], unit: 'tCO2e' },
    pies: {
      source: emptyPie(),
      type: emptyPie(),
      segment: emptyPie()
    }
  }
}

export function emptyLive(): DashboardLive {
  return {
    periodLabel: '统计周期：',
    overall: emptyBucket(),
    stations: {},
    mapEmissions: {},
    rank: []
  }
}

export function ensureDashboardLive(force = false): Promise<DashboardLive> {
  if (!force && pending) return pending
  if (!force && ['ready', 'empty'].includes(dashboardStatus.value) && Date.now() - loadedAt < 60000)
    return Promise.resolve(dashboardData.value)
  const version = ++generation
  controller?.abort()
  controller = new AbortController()
  dashboardStatus.value = 'loading'
  dashboardLoadError.value = ''
  dashboardData.value = emptyLive()
  if (dashboardMode.value === 'demo') {
    pending = null
    dashboardData.value = JSON.parse(JSON.stringify(demoSnapshot)) as DashboardLive
    dashboardStatus.value = 'ready'
    periodLabel.value = dashboardData.value.periodLabel
    loadedAt = Date.now()
    return Promise.resolve(dashboardData.value)
  }
  const request = load(version, controller.signal)
  pending = request
  void request.then(() => { if (version === generation) pending = null })
  return request
}

async function load(version: number, signal: AbortSignal): Promise<DashboardLive> {
  try {
    const body = await requestDashboard({}, signal)
    if (body?.code !== 200 || !body.data?.overall?.kpi || !body.data.stations || !Array.isArray(body.data.rank)) {
      const requestError: any = new Error('screen')
      requestError.response = { status: Number(body?.code || 0), data: body }
      throw requestError
    }
    if (version !== generation) return dashboardData.value
    dashboardData.value = normalize(body.data)
    const data = dashboardData.value
    const hasRecords = data.rank.length > 0 || Object.keys(data.stations).length > 0
      || data.overall.kpi.pointCount > 0 || data.overall.kpi.yearTotal !== 0
      || data.overall.line.source.some(row => row.actual != null)
      || Object.values(data.overall.pies).some(pie => pie.source.length > 0)
    dashboardStatus.value = hasRecords ? 'ready' : 'empty'
    loadedAt = Date.now()
  } catch (error: any) {
    if (version !== generation) return dashboardData.value
    dashboardData.value = emptyLive()
    dashboardStatus.value = 'error'
    const status = Number(error?.response?.status || error?.response?.data?.code || 0)
    dashboardLoadError.value = status === 401
      ? '登录状态已失效，请重新登录'
      : status === 403
        ? '当前账号没有大屏数据查看权限'
        : '大屏数据接口连接失败或返回格式不正确'
  }
  if (version === generation) periodLabel.value = dashboardData.value.periodLabel
  return dashboardData.value
}

function normalize(data: any): DashboardLive {
  const live = emptyLive()
  live.periodLabel = typeof data?.periodLabel === 'string' ? data.periodLabel : live.periodLabel
  live.overall = normalizeBucket(data?.overall)
  const stations = data?.stations && typeof data.stations === 'object' ? data.stations : {}
  for (const name of Object.keys(stations)) live.stations[name] = normalizeBucket(stations[name])
  const emissions = data?.mapEmissions && typeof data.mapEmissions === 'object' ? data.mapEmissions : {}
  for (const name of Object.keys(emissions)) {
    live.mapEmissions[name] = {
      carbonEmission: numberOrZero(emissions[name]?.carbonEmission),
      carbonIntensity: 0
    }
  }
  if (Array.isArray(data?.rank)) {
    live.rank = data.rank.map((row: unknown) => (Array.isArray(row) ? row.map(cell => String(cell ?? '')) : []))
  }
  return live
}

function normalizeBucket(raw: any): DashboardBucket {
  const bucket = emptyBucket()
  if (!raw || typeof raw !== 'object') return bucket
  bucket.kpi.yearTotal = numberOrZero(raw.kpi?.yearTotal)
  bucket.kpi.monthTotal = numberOrZero(raw.kpi?.monthTotal)
  bucket.kpi.yoyPercent = numberOrZero(raw.kpi?.yoyPercent)
  bucket.kpi.pointCount = numberOrZero(raw.kpi?.pointCount)
  bucket.kpi.intensity = 0
  if (Array.isArray(raw.line?.source)) bucket.line.source = raw.line.source
  if (Array.isArray(raw.surface?.years)) bucket.surface.years = raw.surface.years
  if (Array.isArray(raw.surface?.times) && raw.surface.times.length) bucket.surface.times = raw.surface.times
  if (Array.isArray(raw.surface?.values)) bucket.surface.values = raw.surface.values
  bucket.pies.source = normalizePie(raw.pies?.source)
  bucket.pies.type = normalizePie(raw.pies?.type)
  bucket.pies.segment = normalizePie(raw.pies?.segment)
  return bucket
}

function normalizePie(raw: any): DashboardPie {
  const pie = emptyPie()
  if (Array.isArray(raw?.source)) pie.source = raw.source
  return pie
}

function emptyPie(): DashboardPie {
  return { dimensions: ['name', 'value'], source: [] }
}

function numberOrZero(value: unknown): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}
