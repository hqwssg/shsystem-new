<template>
  <div class="panorama-chart">
  <div v-if="emptyPanorama" class="panorama-empty">{{ emptyText }}</div>
  <v-chart v-show="!emptyPanorama"
    ref="vChartRef"
    autoresize
    :init-options="initOptions"
    :theme="themeColor"
    :option="option"
    :manual-update="isPreview()"
    @mouseover="handleHighlight"
    @mouseout="handleDownplay"
  ></v-chart>
  </div>
</template>

<script setup lang="ts">
import { computed, PropType, onMounted, watch } from 'vue'
import VChart from 'vue-echarts'
import { useCanvasInitOptions } from '@/hooks/useCanvasInitOptions.hook'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart } from 'echarts/charts'
import { mergeTheme } from '@/packages/public/chart'
import config, { includes } from './config'
import { useChartDataFetch, useStationScopeSync } from '@/hooks'
import { useChartEditStore } from '@/store/modules/chartEditStore/chartEditStore'
import { isPreview } from '@/utils'
import {
  applyDashPieHoverLabels,
  DASH_PIE_TOOLTIP
} from '@/assets/dashboard/dashPieHoverLabels'
import { DatasetComponent, GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import dataJson from './data.json'

const props = defineProps({
  themeSetting: {
    type: Object,
    required: true
  },
  themeColor: {
    type: Object,
    required: true
  },
  chartConfig: {
    type: Object as PropType<config>,
    required: true
  }
})
const emptyPanorama = computed(() => isPreview() && props.chartConfig.id === 'dash-pie-001'
  && !(props.chartConfig.option.dataset?.source || []).some((row: any) => Number(row.value ?? row[1]) !== 0 && Number.isFinite(Number(row.value ?? row[1]))))
const emptyText = computed(() => props.chartConfig.option.dataset?.source?.length ? '本期排放为0' : '暂无排放结构数据')
const initOptions = useCanvasInitOptions(props.chartConfig.option, props.themeSetting)
let seriesDataNum = -1
let seriesDataMaxLength = 0
let intervalInstance: any = null

use([DatasetComponent, CanvasRenderer, PieChart, GridComponent, TooltipComponent, LegendComponent])

const option = computed(() => {
  const merged = mergeTheme(props.chartConfig.option, props.themeSetting, includes)
  // 组件内 legend 配置优先，防止全局主题 x/y/orient 覆盖
  if (props.chartConfig.option?.legend) {
    merged.legend = { ...merged.legend, ...props.chartConfig.option.legend }
  }
  if (props.chartConfig.id === 'dash-pie-001' && isPreview()) {
    merged.tooltip = { ...merged.tooltip, ...DASH_PIE_TOOLTIP }
    const series = Array.isArray(merged.series) ? merged.series : []
    if (series[0]) {
      merged.series = [applyDashPieHoverLabels(series[0] as Record<string, unknown>), ...series.slice(1)]
    }
  }
  return merged
})

// 会重新选择需要选中和展示的数据
const handleSeriesData = () => {
  if (seriesDataNum > -1) {
    vChartRef.value?.dispatchAction({
      type: 'downplay',
      dataIndex: seriesDataNum
    })
  }
  seriesDataNum = seriesDataNum >= seriesDataMaxLength - 1 ? 0 : seriesDataNum + 1
  vChartRef.value?.dispatchAction({
    type: 'highlight',
    dataIndex: seriesDataNum
  })
}

// 新增轮播
const addPieInterval = (newData?: typeof dataJson, skipPre = false) => {
  if (!skipPre && !Array.isArray(newData?.source)) return
  if (!skipPre) seriesDataMaxLength = newData?.source.length || 0
  clearInterval(intervalInstance)
  intervalInstance = setInterval(() => {
    handleSeriesData()
  }, 1000)
}

// 取消轮播
const clearPieInterval = () => {
  vChartRef.value?.dispatchAction({
    type: 'downplay',
    dataIndex: seriesDataNum
  })
  clearInterval(intervalInstance)
  intervalInstance = null
}

// 处理鼠标聚焦高亮内容
const handleHighlight = () => {
  clearPieInterval()
}

// 处理鼠标取消悬浮
const handleDownplay = () => {
  if (props.chartConfig.option.isCarousel && !intervalInstance) {
    // 恢复轮播
    addPieInterval(undefined, true)
  }
}

watch(
  () => props.chartConfig.option.type,
  newData => {
    try {
      // 防止初始化时触发修改，导致部分参数丢失
      if (isPreview()) {
        return
      }
      if (newData === 'nomal') {
        props.chartConfig.option.series[0].radius = '70%'
        props.chartConfig.option.series[0].roseType = false
      } else if (newData === 'ring') {
        props.chartConfig.option.series[0].radius = ['40%', '65%']
        props.chartConfig.option.series[0].roseType = false
      } else {
        props.chartConfig.option.series[0].radius = '70%'
        props.chartConfig.option.series[0].roseType = true
      }
    } catch (error) {
      console.log(error)
    }
  },
  { deep: false, immediate: true }
)

watch(
  () => props.chartConfig.option.isCarousel,
  newData => {
    if (newData) {
      addPieInterval(undefined, true)
      props.chartConfig.option.legend.show = false
    } else {
      props.chartConfig.option.legend.show = true
      clearPieInterval()
    }
  }
)

const { vChartRef, applyDataset } = useChartDataFetch(props.chartConfig, useChartEditStore, (newData: typeof dataJson) => {
  clearPieInterval()
  if (props.chartConfig.option.isCarousel) {
    addPieInterval(newData)
  }
})

if (isPreview() && props.chartConfig.id === 'dash-pie-001') {
  useStationScopeSync<typeof dataJson>({
    chartEditStore: useChartEditStore(),
    kind: 'pie',
    getStructureType: () => props.chartConfig.request.requestParams.Params?.structureType || 'source',
    apply: dataset => {
      props.chartConfig.option.dataset = dataset
      applyDataset(dataset)
      clearPieInterval()
      if (props.chartConfig.option.isCarousel) addPieInterval(dataset)
    }
  })
}

onMounted(() => {
  seriesDataMaxLength = dataJson.source.length
  if (props.chartConfig.option.isCarousel) {
    addPieInterval(undefined, true)
  }
})
</script>

<style scoped>
.panorama-chart{position:relative;width:100%;height:100%}.panorama-empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#9ab4cb;font-size:16px}
</style>
