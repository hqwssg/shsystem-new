<template>
  <div v-if="isPanorama" class="panorama-status" :class="{ error: dashboardStatus === 'error' }" role="status">
    <label>数据模式
      <select :value="dashboardMode" aria-label="数据模式" @change="changeMode">
        <option value="real">正式数据</option>
        <option value="demo">演示数据</option>
      </select>
    </label>
    <span>{{ message }}</span>
    <button :disabled="dashboardStatus === 'loading'" @click="reload">刷新数据</button>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useChartEditStore } from '@/store/modules/chartEditStore/chartEditStore'
import { dashboardData, dashboardStatus, dashboardLoadError, ensureDashboardLive, dashboardMode, setDashboardMode } from '@/assets/dashboard/dashboardLiveData'
import { setPreviewStationScope } from '@/assets/dashboard/stationScopeController'
const store = useChartEditStore()
const isPanorama = computed(() => store.getComponentList.some(item => item.id === 'dash-map-001'))
const message = computed(() => {
  if (dashboardMode.value === 'demo') return '演示数据：模拟生成，非实际核算，不写入业务数据库'
  if (dashboardStatus.value === 'error') return dashboardLoadError.value
  if (dashboardStatus.value === 'loading' || dashboardStatus.value === 'idle') return '正在加载核算数据…'
  if (dashboardStatus.value === 'empty') return '当前期间没有可展示的核算结果，请核对核算任务、期间及公司归属'
  return dashboardData.value.overall.line.source.length ? '已加载核算数据' : '已加载期间合计；暂无月度核算明细'
})
const reload = () => { void ensureDashboardLive(true) }
const changeMode = (event: Event) => {
  setPreviewStationScope(store, 'overall')
  void setDashboardMode((event.target as HTMLSelectElement).value as 'real' | 'demo')
}
</script>
<style scoped>
.panorama-status{flex-wrap:wrap;align-items:center}.panorama-status label{display:flex;align-items:center;gap:8px}.panorama-status select{background:#12324b;border:1px solid #2d688d;color:#dcf1ff;padding:4px;border-radius:3px}
.panorama-status{position:fixed;bottom:12px;left:12px;z-index:10000;display:flex;gap:16px;align-items:center;max-width:calc(100vw - 24px);padding:8px 12px;border:1px solid #27506b;border-radius:4px;background:rgba(4,22,36,.92);color:#b9d4e9;font:13px "Microsoft YaHei",sans-serif}.panorama-status.error{color:#ffb0a4;border-color:#a85c53}.panorama-status button{flex-shrink:0;background:#12324b;border:1px solid #2d688d;border-radius:3px;color:#dcf1ff;padding:4px 10px;cursor:pointer}.panorama-status button:disabled{opacity:.5}
</style>
