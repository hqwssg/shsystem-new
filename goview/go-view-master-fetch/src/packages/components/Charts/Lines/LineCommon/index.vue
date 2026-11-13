<template>
  <div class="panorama-chart">
  <div v-if="emptyPanorama" class="panorama-empty">暂无月度核算数据</div>
  <v-chart v-show="!emptyPanorama"
    ref="vChartRef"
    :init-options="initOptions"
    :theme="themeColor"
    :option="option"
    :manual-update="isPreview()"
    :update-options="{
      replaceMerge: replaceMergeArr
    }"
    autoresize
  >
  </v-chart>
  </div>
</template>

<script setup lang="ts">
import { PropType, computed, watch, ref, nextTick } from 'vue'
import VChart from 'vue-echarts'
import { useCanvasInitOptions } from '@/hooks/useCanvasInitOptions.hook'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import config, { includes, seriesItem } from './config'
import { mergeTheme } from '@/packages/public/chart'
import { useChartEditStore } from '@/store/modules/chartEditStore/chartEditStore'
import { useChartDataFetch, useStationScopeSync } from '@/hooks'
import { isPreview } from '@/utils'
import { DatasetComponent, GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import isObject from 'lodash/isObject'
import { cloneDeep } from 'lodash'

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

const emptyPanorama = computed(() => isPreview() && props.chartConfig.id === 'dash-line-001'
  && !(props.chartConfig.option.dataset?.source || []).some((row: any) => (Array.isArray(row) ? row[1] : row.actual) != null))
const initOptions = useCanvasInitOptions(props.chartConfig.option, props.themeSetting)

use([DatasetComponent, CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent])

const replaceMergeArr = ref<string[]>()

const option = computed(() => {
  return mergeTheme(props.chartConfig.option, props.themeSetting, includes)
})

// dataset 无法变更条数的补丁
watch(
  () => props.chartConfig.option.dataset,
  (newData: { dimensions: any }, oldData) => {
    try {
      if (!isObject(newData) || !('dimensions' in newData)) return
      if (Array.isArray(newData?.dimensions)) {
        const previous = oldData as { dimensions?: unknown[] } | undefined
        if (Array.isArray(previous?.dimensions) && previous.dimensions.length === newData.dimensions.length) return
        const seriesArr = []
        for (let i = 0; i < newData.dimensions.length - 1; i++) {
          seriesArr.push(cloneDeep(seriesItem))
        }
        replaceMergeArr.value = ['series']
        props.chartConfig.option.series = seriesArr
        nextTick(() => {
          replaceMergeArr.value = []
        })
      }
    } catch (error) {
      console.log(error)
    }
  },
  {
    deep: false
  }
)

const { vChartRef, applyDataset } = useChartDataFetch(props.chartConfig, useChartEditStore, (newData: any) => {
  props.chartConfig.option.dataset = newData
})

if (isPreview() && props.chartConfig.id === 'dash-line-001') {
  useStationScopeSync<any>({
    chartEditStore: useChartEditStore(),
    kind: 'line',
    apply: dataset => {
      props.chartConfig.option.dataset = dataset
      applyDataset(dataset)
    }
  })
}
</script>

<style scoped>
.panorama-chart{position:relative;width:100%;height:100%}.panorama-empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#9ab4cb;font-size:16px}
</style>
