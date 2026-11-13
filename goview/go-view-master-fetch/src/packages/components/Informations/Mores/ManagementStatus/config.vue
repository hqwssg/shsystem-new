<template><div style="padding:16px">显示内容：<n-select v-model:value="option.mode" :options="modes" />默认数据模式：<n-select v-model:value="option.dataMode" :options="dataModes" /></div></template>
<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ optionData: any }>()
const option = computed(() => props.optionData)
const modes = [{ label: '年份及公司筛选', value: 'controls' }, { label: '月度任务覆盖矩阵', value: 'coverage' }]
const dataModes = [{ label: '正式数据', value: 'real' }, { label: '演示数据（模拟生成）', value: 'demo' }]
</script>
