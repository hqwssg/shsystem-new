<template>
  <div class="attribution-selector">
    <el-input :model-value="displayName" readonly placeholder="请选择能耗归属部门" @click="open">
      <template #append><el-button @click.stop="open">选择</el-button></template>
    </el-input>
    <el-dialog v-model="visible" title="能耗归属部门选择" width="660px" append-to-body>
      <div class="filters"><el-input v-model="keyword" clearable placeholder="输入部门名称" @keyup.enter="load" /><el-button type="primary" @click="load">查询</el-button></div>
      <el-table v-loading="loading" :data="rows" highlight-current-row height="380" @current-change="current=$event">
        <el-table-column width="48"><template #default="scope"><el-radio :model-value="current?.deptId" :value="scope.row.deptId" @change="current=scope.row" >{{ scope.row.deptId }}</el-radio></template></el-table-column>
        <el-table-column prop="deptName" label="部门" width="180" />
        <el-table-column prop="deptPath" label="层级路径" min-width="300" />
      </el-table>
      <template #footer><el-button @click="visible=false">取消</el-button><el-button type="primary" :disabled="!current" @click="confirm">选择</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
const props=defineProps({ modelValue: [Number, String], displayName: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue', 'update:displayName'])
const visible=ref(false), loading=ref(false), keyword=ref(''), rows=ref([]), current=ref(null)
const open=async()=>{visible.value=true;current.value=null;await load()}
const load=async()=>{loading.value=true;try{rows.value=(await axios.get('/api/energy-attribution-departments',{params:{keyword:keyword.value}})).data||[];current.value=rows.value.find(item=>String(item.deptId)===String(props.modelValue))||null}catch(e){ElMessage.error(e.response?.data?.message||'加载部门失败')}finally{loading.value=false}}
const confirm=()=>{emit('update:modelValue',current.value.deptId);emit('update:displayName',current.value.deptName);visible.value=false}
</script>
<style scoped>.filters{display:flex;gap:8px;margin-bottom:12px}.attribution-selector{width:100%}</style>
