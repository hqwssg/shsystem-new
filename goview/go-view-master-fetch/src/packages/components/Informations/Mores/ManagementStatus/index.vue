<template>
  <div class="management-status">
    <template v-if="chartConfig.option.mode === 'controls'">
      <div class="controls">
        <label>数据模式 <select aria-label="数据模式" v-model="state.dataMode" @change="changeMode"><option value="demo">演示数据</option><option value="real">正式数据</option></select></label>
        <label>统计年度 <select aria-label="统计年度" v-model="state.year" @change="refresh"><option v-for="y in years" :key="y" :value="String(y)">{{ y }}年</option></select></label>
        <label>公司范围 <select aria-label="公司范围" v-model="state.companyId" @change="refresh"><option value="">{{ state.dataMode === 'demo' ? '全部演示公司' : '全部正式核算公司' }}</option><option v-for="c in companies" :key="c.id" :value="String(c.id)">{{ c.name }}</option></select></label>
        <label>能耗对比 <select aria-label="能耗对比能源" v-model="state.energyType"><option value="electricity">电力</option><option value="fuel">燃料</option><option value="heat">热力</option></select></label>
        <label>单位 <select aria-label="能耗对比单位" v-model="state.energyUnit"><option v-if="!units.length" value="">暂无数据</option><option v-for="unit in units" :key="unit" :value="unit">{{ unit }}</option></select></label>
        <button @click="refresh" :disabled="state.loading">{{ state.loading ? '更新中…' : '刷新数据' }}</button>
        <span :class="{ error: state.error }">{{ state.error || (state.dataMode === 'demo' ? '模拟生成 · 非实际核算' : state.loading ? '正在读取正式核算快照' : '每60秒刷新 · 排除展示数据') }}</span>
      </div>
    </template>
    <template v-else>
      <p class="legend">完整 / 质量待核对 / 因子快照缺失 / 核算失败 / 仅期间任务 / 无月度任务</p>
      <div v-if="!state.data" class="empty">{{ state.error || (state.loading ? '正在读取月度覆盖情况…' : '暂无覆盖数据') }}</div>
      <div v-else class="matrix">
        <table><thead><tr><th>公司</th><th v-for="m in 12" :key="m">{{ m }}月</th></tr></thead>
          <tbody><tr v-for="row in state.data.coverage" :key="row.company"><th>{{ row.company }}</th>
            <td v-for="cell in row.cells" :key="cell.month"><button :class="tone(cell.state)" @click="selected = { ...cell, company: row.company }" :title="cell.description">{{ cell.state }}</button></td>
          </tr></tbody>
        </table>
      </div>
      <p class="description">{{ state.data?.coverageLabel || '覆盖率非采集完整率；没有月度明细时不拆分年度总量。' }}</p>
      <div v-if="selected" class="detail" role="status"><strong>{{ selected.company }} · {{ selected.month }}月 · {{ selected.state }}</strong><span v-if="selected.taskId"> · 任务 {{ selected.taskId }}</span>：{{ selected.description }}<button @click="selected = null">关闭</button></div>
    </template>
  </div>
</template>
<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { managementLive as state, acquireManagement, refreshManagement } from '@/assets/dashboard/managementLive'
import { managementEnergyUnits } from '@/assets/dashboard/managementDatasets.mjs'
const props = defineProps<{ chartConfig: any }>()
const selected = ref<any>(null)
// Keep selectors while a refresh clears the previous result.
const companies = ref<any[]>([]), availableYears = ref<number[]>([])
watch(() => state.data, data => { if (data) { companies.value = data.companies; availableYears.value = data.years } selected.value = null }, { immediate: true })
const years = computed(() => availableYears.value.length ? availableYears.value : [Number(state.year) || new Date().getFullYear()])
const units = computed(() => managementEnergyUnits(state.data, state.energyType))
watch([() => state.data, () => state.energyType], () => {
  if (state.data && !units.value.includes(state.energyUnit)) state.energyUnit = units.value[0] || ''
}, { immediate: true })
const refresh = () => { void refreshManagement() }
const changeMode = () => { state.companyId = ''; state.year = ''; state.energyUnit = ''; companies.value = []; availableYears.value = []; void refreshManagement() }
const tone = (value: string) => value === '完整' ? 'good' : ['无月度任务', '仅期间任务'].includes(value) ? 'missing' : 'warning'
onScopeDispose(acquireManagement(props.chartConfig.option.dataMode))
</script>
<style scoped>
.management-status{color:#c8d9ed;font:16px "Microsoft YaHei",sans-serif;height:100%;overflow:auto}.controls{display:flex;align-items:center;gap:18px;height:100%;flex-wrap:wrap}.controls label{display:flex;gap:12px;align-items:center}select,button{font:inherit;color:#dcefff;background:#102c49;border:1px solid #2b597a;border-radius:5px;padding:8px 12px;cursor:pointer}button:disabled{opacity:.6}select option{background:#10243b}.controls span,.legend,.description{font-size:14px;color:#8faac6}.error{color:#ffb88e!important}.legend{margin:4px 0 20px}.matrix{overflow:auto;max-height:210px}table{width:100%;border-collapse:collapse;table-layout:fixed}th{font-weight:normal;font-size:14px;padding:10px 0;color:#a4bcd6}th:first-child{width:135px}td{padding:6px 3px;text-align:center}td button{width:100%;padding:10px 1px;font-size:12px;white-space:normal}.good{color:#65e1b8;border-color:#276852;background:#133f39}.missing{color:#9aacc2;border-color:#34465d;background:#1d2e43}.warning{color:#ffd183;border-color:#856533;background:#44351e}.detail{padding:12px;background:#15344b;font-size:14px}.detail button{float:right;padding:2px 8px}.empty{padding:35px;text-align:center;color:#8298ae}
</style>
