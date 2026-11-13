<template>
  <div class="attribution-selector">
    <el-input :model-value="displayName" readonly placeholder="请选择能耗归属站点/区间" @click="open">
      <template #append><el-button @click.stop="open">选择</el-button></template>
    </el-input>
    <el-dialog v-model="visible" title="能耗归属站点/区间选择" width="760px" append-to-body>
      <div class="filters">
        <el-input v-model="query.keyword" clearable placeholder="输入拼音首字母或站点/区间名称" @keyup.enter="load" />
        <el-select v-model="query.lineName" clearable placeholder="所属线路" @change="load">
          <el-option v-for="item in lineOptions" :key="item.code" :label="item.value" :value="item.value" />
        </el-select>
        <el-select v-model="query.branchCompany" clearable placeholder="所属分公司" @change="load">
          <el-option v-for="item in branchOptions" :key="item.code" :label="item.value" :value="item.value" />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
      </div>
      <el-table v-loading="loading" :data="rows" highlight-current-row height="390" @current-change="current = $event">
        <el-table-column width="48"><template #default="scope"><el-radio :model-value="current?.id" :value="scope.row.id" @change="current=scope.row" >{{ scope.row.id }}</el-radio></template></el-table-column>
        <el-table-column prop="name" label="站点/区间" min-width="150" />
        <el-table-column prop="lineName" label="线路" width="100"><template #default="s">{{ s.row.lineName || '-' }}</template></el-table-column>
        <el-table-column prop="branchCompany" label="分公司" width="120" />
      </el-table>
      <template #footer>
        <el-button @click="visible=false">取消</el-button>
        <el-button type="primary" :disabled="!current" @click="confirm">选择</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { energyAttributionApi } from '../api/energyAttribution'

const props = defineProps({ modelValue: [Number, String], displayName: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue', 'update:displayName'])
const visible = ref(false), loading = ref(false), rows = ref([]), current = ref(null)
const lineOptions = ref([]), branchOptions = ref([])
const query = reactive({ keyword: '', lineName: '', branchCompany: '' })
const open = async () => {
  visible.value = true
  current.value = null
  try { [lineOptions.value, branchOptions.value] = await Promise.all([energyAttributionApi.listDict('shuohuang_railway_line'), energyAttributionApi.listDict('energy_allocation')]); await load() }
  catch (e) { ElMessage.error(e.response?.data?.message || '加载能耗归属站点失败') }
}
const load = async () => {
  loading.value = true
  try {
    rows.value = await energyAttributionApi.listStations(query)
    current.value = rows.value.find(item => String(item.id) === String(props.modelValue)) || null
  }
  finally { loading.value = false }
}
const confirm = () => { emit('update:modelValue', current.value.id); emit('update:displayName', current.value.name); visible.value = false }
</script>

<style scoped>.filters{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:8px;margin-bottom:12px}.attribution-selector{width:100%}</style>
