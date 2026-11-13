import { watch, nextTick } from 'vue'
import { isPreview } from '@/utils'
import { getPreviewStationScope, getScopeGeneration } from '@/assets/dashboard/stationScopeController'
import {
  currentDashboard,
  dashboardData,
  emptyBucket,
  ensureDashboardLive,
  type DashboardBucket,
  type DashboardLive
} from '@/assets/dashboard/dashboardLiveData'

export type ScopePanelKind = 'kpi' | 'line' | 'surface' | 'pie'

export type KpiScopeField = 'yearTotal' | 'monthTotal' | 'yoyPercent' | 'pointCount' | 'intensity'

export interface UseStationScopeSyncOptions<T> {
  chartEditStore: {
    requestGlobalConfig: {
      requestParams: { Params: Record<string, unknown> }
    }
  }
  kind: ScopePanelKind
  kpiField?: KpiScopeField
  apply: (payload: T) => void
  replayEntrance?: () => void
  getStructureType?: () => string
}

function bucketFor(data: DashboardLive, scope: ReturnType<typeof getPreviewStationScope>): DashboardBucket {
  if (scope.dataScope === 'station') {
    return data.stations[scope.stationName] ?? emptyBucket()
  }
  return data.overall
}

function resolvePayload(
  data: DashboardLive,
  kind: ScopePanelKind,
  scope: ReturnType<typeof getPreviewStationScope>,
  kpiField: KpiScopeField = 'yearTotal',
  structureType = 'source'
) {
  const bucket = bucketFor(data, scope)
  switch (kind) {
    case 'kpi': {
      if (scope.dataScope === 'station' && kpiField === 'pointCount') return bucket.kpi.intensity
      const key = kpiField === 'pointCount' ? 'pointCount' : kpiField
      return (bucket.kpi as Record<string, number>)[key] ?? 0
    }
    case 'line':
      return bucket.line
    case 'surface':
      return bucket.surface
    case 'pie':
      return bucket.pies[structureType as keyof DashboardBucket['pies']] ?? emptyBucket().pies.source
    default:
      return 0
  }
}

export function useStationScopeSync<T>(opts: UseStationScopeSyncOptions<T>) {
  if (!isPreview()) return

  const run = (withEntrance: boolean) => {
    const paint = (data: DashboardLive) => {
      const scope = getPreviewStationScope(opts.chartEditStore)
      const structureType = opts.getStructureType?.() ?? 'source'
      const payload = resolvePayload(data, opts.kind, scope, opts.kpiField, structureType)
      opts.apply(payload as T)
      if (withEntrance && getScopeGeneration(opts.chartEditStore.requestGlobalConfig.requestParams) > 0) {
        void nextTick(() => {
          opts.replayEntrance?.()
        })
      }
    }
    paint(currentDashboard())
    void ensureDashboardLive()
  }

  watch(
    () => [
      opts.chartEditStore.requestGlobalConfig.requestParams.Params.dataScope,
      opts.chartEditStore.requestGlobalConfig.requestParams.Params.stationName,
      opts.chartEditStore.requestGlobalConfig.requestParams.Params.scopeGeneration
    ],
    () => run(true),
    { immediate: true }
  )

  watch(dashboardData, () => run(false))

  if (opts.kind === 'pie' && opts.getStructureType) {
    watch(opts.getStructureType, () => run(false))
  }
}
