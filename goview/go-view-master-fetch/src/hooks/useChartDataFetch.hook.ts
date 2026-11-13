import { ref, toRefs, toRaw, watch, onScopeDispose, onMounted, nextTick } from 'vue'
import { managementLive, acquireManagement } from '@/assets/dashboard/managementLive'
import { managementDataset } from '@/assets/dashboard/managementDatasets.mjs'
import type VChart from 'vue-echarts'
import { customizeHttp } from '@/api/http'
import { useChartDataPondFetch } from '@/hooks/'
import { CreateComponentType, ChartFrameEnum } from '@/packages/index.d'
import { useChartEditStore } from '@/store/modules/chartEditStore/chartEditStore'
import { RequestDataTypeEnum } from '@/enums/httpEnum'
import { isPreview, newFunctionHandle, intervalUnitHandle } from '@/utils'
import { setOption } from '@/packages/public/chart'
import { isNil } from 'lodash'

// 获取类型
type ChartEditStoreType = typeof useChartEditStore

/**
 * setdata 数据监听与更改
 * @param targetComponent
 * @param useChartEditStore 若直接引会报错，只能动态传递
 * @param updateCallback 自定义更新函数
 */
export const useChartDataFetch = (
  targetComponent: CreateComponentType,
  useChartEditStore: ChartEditStoreType,
  updateCallback?: (...args: any) => any
) => {
  const vChartRef = ref<typeof VChart | null>(null)
  let fetchInterval: any = 0
  let pendingDataset: any

  // 数据池
  const { addGlobalDataInterface } = useChartDataPondFetch()

  // 组件类型
  const { chartFrame } = targetComponent.chartConfig

  // eCharts 组件配合 vChart 库更新方式
  const echartsUpdateHandle = (dataset: any) => {
    if (chartFrame === ChartFrameEnum.ECHARTS) {
      pendingDataset = dataset
      if (vChartRef.value) {
        setOption(vChartRef.value, { dataset: dataset }, false)
      }
    }
  }

  watch(vChartRef, chart => {
    if (chart && pendingDataset !== undefined) {
      setOption(chart, { dataset: pendingDataset }, false)
    }
  })

  const requestIntervalFn = () => {
    const chartEditStore = useChartEditStore()

    // 全局数据
    const {
      requestOriginUrl,
      requestIntervalUnit: globalUnit,
      requestInterval: globalRequestInterval
    } = toRefs(chartEditStore.getRequestGlobalConfig)

    // 目标组件
    const {
      requestDataType,
      requestUrl,
      requestIntervalUnit: targetUnit,
      requestInterval: targetInterval
    } = toRefs(targetComponent.request)

    // 非请求类型
    if (requestDataType.value !== RequestDataTypeEnum.AJAX) return

    try {
      // 处理地址
      // @ts-ignore
      if (requestUrl?.value) {
        // requestOriginUrl 允许为空
        const completePath = requestOriginUrl && requestOriginUrl.value + requestUrl.value
        if (!completePath) return

        clearInterval(fetchInterval)

        const fetchFn = async () => {
          const res = await customizeHttp(toRaw(targetComponent.request), toRaw(chartEditStore.getRequestGlobalConfig))
          if (res) {
            try {
              const filter = targetComponent.filter
              const { data } = res
              const globalParams = chartEditStore.getRequestGlobalConfig.requestParams?.Params || {}
              const localParams = targetComponent.request.requestParams?.Params || {}
              const view = {
                ...res,
                dataScope: globalParams.dataScope,
                stationName: globalParams.stationName,
                structureType: localParams.structureType
              }
              const dataset = newFunctionHandle(data, view, filter)
              echartsUpdateHandle(dataset)
              if (updateCallback) {
                updateCallback(dataset)
              }
            } catch (error) {
              console.error(error)
            }
          }
        }

        // 普通初始化与组件交互处理监听
        watch(
          () => targetComponent.request.requestParams,
          () => {
            fetchFn()
          },
          {
            immediate: true,
            deep: true
          }
        )

        watch(
          () => {
            const params = chartEditStore.getRequestGlobalConfig.requestParams?.Params
            return [params?.dataScope, params?.stationName]
          },
          () => {
            fetchFn()
          }
        )

        // 定时时间
        const time = targetInterval && !isNil(targetInterval.value) ? targetInterval.value : globalRequestInterval.value
        // 单位
        const unit = targetInterval && !isNil(targetInterval.value) ? targetUnit.value : globalUnit.value
        // 开启轮询
        if (time) {
          fetchInterval = setInterval(fetchFn, intervalUnitHandle(time, unit))
        }
      }
      // eslint-disable-next-line no-empty
    } catch (error) {
      console.log(error)
    }
  }

  // Management template shares one abortable request; existing dashboards keep their own fetch flow.
  if (targetComponent.id.startsWith('management-') && targetComponent.option.managementRole) {
    const release = acquireManagement()
    const apply = (data: any) => {
      const dataset = managementDataset(targetComponent.option.managementRole, data, managementLive)
      echartsUpdateHandle(dataset)
      updateCallback?.(dataset)
    }
    const stop = watch(() => [managementLive.data, managementLive.energyType, managementLive.energyUnit], ([data]) => apply(data), { flush: 'post' })
    onMounted(() => { void nextTick(() => apply(managementLive.data)) })
    onScopeDispose(() => { stop(); release() })
    return { vChartRef, applyDataset: echartsUpdateHandle }
  }

  // Built-in panorama panels use the shared authenticated snapshot, including old static canvases.
  if (isPreview() && ['dash-line-001', 'dash-pie-001', 'dash-3d-001', 'dash-table-001',
    'dash-kpi-001', 'dash-kpi-002', 'dash-kpi-003', 'dash-kpi-004'].includes(targetComponent.id))
    return { vChartRef, applyDataset: echartsUpdateHandle }

  if (isPreview()) {
    targetComponent.request.requestDataType === RequestDataTypeEnum.Pond
      ? addGlobalDataInterface(targetComponent, useChartEditStore, (newData: any) => {
          echartsUpdateHandle(newData)
          if (updateCallback) updateCallback(newData)
        })
      : requestIntervalFn()
  } else {
    requestIntervalFn()
  }
  return { vChartRef, applyDataset: echartsUpdateHandle }
}
