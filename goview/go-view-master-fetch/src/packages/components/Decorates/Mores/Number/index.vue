<template>
  <n-statistic tabular-nums class="go-decorates-number">
    <template #prefix>
      <span :style="`color:${prefixColor};font-size:${numberSize}px`">
        {{ prefixText }}
      </span>
    </template>
    <span :style="`color:${numberColor};font-size:${numberSize}px`">
      <span v-if="isPanoramaKpi && dashboardStatus !== 'ready'" style="font-size:20px">{{ dashboardStatus === 'loading' ? '加载中' : '暂无数据' }}</span>
      <n-number-animation v-else
        :key="animKey"
        :from="option.from"
        :to="option.dataset"
        :duration="dur * 1000"
        :show-separator="showSeparator"
        :precision="precision"
      ></n-number-animation>
    </span>
    <template #suffix>
      <span :style="`color:${suffixColor};font-size:${numberSize}px`">
        {{ suffixText }}
      </span>
    </template>
  </n-statistic>
</template>

<script setup lang="ts">
import { PropType, toRefs, ref, reactive, watch } from 'vue'
import { CreateComponentType } from '@/packages/index.d'
import { useChartEditStore } from '@/store/modules/chartEditStore/chartEditStore'
import { useChartDataFetch, useStationScopeSync } from '@/hooks'
import { dashboardStatus } from '@/assets/dashboard/dashboardLiveData'
import type { KpiScopeField } from '@/hooks/useStationScopeSync.hook'
import { isPreview } from '@/utils'

const props = defineProps({
  chartConfig: {
    type: Object as PropType<CreateComponentType>,
    required: true
  }
})

const KPI_FIELD_BY_ID: Record<string, KpiScopeField> = {
  'dash-kpi-001': 'yearTotal',
  'dash-kpi-002': 'monthTotal',
  'dash-kpi-003': 'yoyPercent',
  'dash-kpi-004': 'pointCount'
}

const isPanoramaKpi = isPreview() && !!KPI_FIELD_BY_ID[props.chartConfig.id]

if (isPanoramaKpi) {
  const field = KPI_FIELD_BY_ID[props.chartConfig.id]
  props.chartConfig.option.dataset = 0
  if (field === 'yearTotal' || field === 'monthTotal') {
    props.chartConfig.option.suffixText = 'tCO₂e'
    props.chartConfig.option.precision = 3
  }
}

const option = reactive({
  from: 0,
  dataset: 0
})
const animKey = ref(0)
const { w, h } = toRefs(props.chartConfig.attr)
let { dur, showSeparator, prefixText, prefixColor, suffixText, suffixColor, precision, numberSize, numberColor } =
  toRefs(props.chartConfig.option)

const updateNumber = (newData: number) => {
  // 原来的目标值作为新的数字动画的起始值
  option.from = option.dataset
  option.dataset = newData
}

watch(
  () => props.chartConfig.option.from,
  () => {
    option.from = props.chartConfig.option.from
  },
  { immediate: true }
)

watch(
  () => props.chartConfig.option.dataset,
  () => {
    option.dataset = props.chartConfig.option.dataset
  },
  {
    immediate: true,
    deep: false
  }
)

useChartDataFetch(props.chartConfig, useChartEditStore, updateNumber)

const replayEntranceFromZero = (value: number) => {
  option.from = 0
  option.dataset = value
  animKey.value++
}

if (isPanoramaKpi) {
  const chartEditStore = useChartEditStore()
  useStationScopeSync<number>({
    chartEditStore,
    kind: 'kpi',
    kpiField: KPI_FIELD_BY_ID[props.chartConfig.id] ?? 'yearTotal',
    apply: v => {
      option.dataset = v
    },
    replayEntrance: () => {
      replayEntranceFromZero(option.dataset)
    }
  })
}
</script>

<style lang="scss" scoped>
@include go('decorates-number') {
  display: flex;
  justify-content: center;
  align-items: center;
  white-space: nowrap;

  :deep(.n-statistic) {
    white-space: nowrap;
  }

  :deep(.n-statistic-value) {
    white-space: nowrap;
    flex-wrap: nowrap;
  }

  :deep(.n-statistic-value__prefix),
  :deep(.n-statistic-value__content),
  :deep(.n-statistic-value__suffix) {
    white-space: nowrap;
  }
}
</style>
