<template>
  <div class="station-settings">
    <div class="page-title"><h2>能耗归属站点设置</h2><span>统一维护采集点可选择的能耗归属站点和区间目录</span></div>
    <div class="toolbar">
      <el-input v-model="query.keyword" clearable placeholder="输入拼音首字母或站点/区间名称" @keyup.enter="load" />
      <el-select v-model="query.lineName" clearable placeholder="所属线路" @change="load">
        <el-option v-for="item in lineOptions" :key="item.code" :label="item.value" :value="item.value" />
      </el-select>
      <el-select v-model="query.branchCompany" clearable placeholder="所属分公司" @change="load">
        <el-option v-for="item in branchOptions" :key="item.code" :label="item.value" :value="item.value" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
      <el-button v-if="canEdit" type="success" @click="openEditor()">新增</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="name" label="站点/区间" min-width="180" />
      <el-table-column prop="lineName" label="线路" width="150"><template #default="s">{{ s.row.lineName || '-' }}</template></el-table-column>
      <el-table-column prop="branchCompany" label="分公司" min-width="160" />
      <el-table-column v-if="canEdit" label="操作" width="160" align="center" fixed="right">
        <template #default="scope">
          <div class="station-actions">
            <el-button link type="primary" @click="openEditor(scope.row)">修改</el-button>
            <el-button link type="danger" @click="remove(scope.row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
    <el-dialog v-model="editorVisible" :title="form.id ? '修改能耗归属站点/区间' : '新增能耗归属站点/区间'" width="480px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="名称" prop="name"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="所属线路" prop="lineName"><el-select v-model="form.lineName" clearable style="width:100%"><el-option v-for="item in lineOptions" :key="item.code" :label="item.value" :value="item.value" /></el-select></el-form-item>
        <el-form-item label="所属分公司" prop="branchCompany"><el-select v-model="form.branchCompany" style="width:100%"><el-option v-for="item in branchOptions" :key="item.code" :label="item.value" :value="item.value" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="editorVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { energyAttributionApi } from '../api/energyAttribution'

defineProps({ canEdit: { type: Boolean, default: false } })
const query = reactive({ keyword: '', lineName: '', branchCompany: '' })
const form = reactive({ id: null, name: '', lineName: '', branchCompany: '' })
const rows = ref([]), lineOptions = ref([]), branchOptions = ref([])
const loading = ref(false), saving = ref(false), editorVisible = ref(false), formRef = ref(null)
const rules = { name: [{ required: true, message: '请输入名称', trigger: 'blur' }], branchCompany: [{ required: true, message: '请选择所属分公司', trigger: 'change' }] }
const load = async () => { loading.value = true; try { rows.value = await energyAttributionApi.listStations(query) } catch (e) { ElMessage.error(e.response?.data?.message || '加载失败') } finally { loading.value = false } }
const openEditor = (row) => { Object.assign(form, { id: row?.id || null, name: row?.name || '', lineName: row?.lineName || '', branchCompany: row?.branchCompany || '' }); editorVisible.value = true }
const save = async () => { await formRef.value.validate(); saving.value = true; try { const body = { name: form.name, lineName: form.lineName || null, branchCompany: form.branchCompany }; if (form.id) await energyAttributionApi.updateStation(form.id, body); else await energyAttributionApi.createStation(body); ElMessage.success('保存成功'); editorVisible.value = false; await load() } catch (e) { ElMessage.error(e.response?.data?.message || e.response?.data || '保存失败') } finally { saving.value = false } }
const remove = async (row) => { try { await ElMessageBox.confirm(`确认删除“${row.name}”吗？`, '提示', { type: 'warning' }); await energyAttributionApi.deleteStation(row.id); ElMessage.success('删除成功'); await load() } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(e.response?.data?.message || e.response?.data || '删除失败') } }
onMounted(async () => { try { [lineOptions.value, branchOptions.value] = await Promise.all([energyAttributionApi.listDict('shuohuang_railway_line'), energyAttributionApi.listDict('energy_allocation')]); await load() } catch (e) { ElMessage.error(e.response?.data?.message || '初始化失败') } })
</script>

<style scoped>.station-settings{padding:20px}.page-title{display:flex;align-items:baseline;gap:14px;margin-bottom:18px}.page-title h2{margin:0}.page-title span{color:#909399}.toolbar{display:grid;grid-template-columns:2fr 1fr 1fr auto auto;gap:10px;margin-bottom:16px}.station-actions{display:inline-flex;align-items:center;justify-content:center;flex-wrap:nowrap;gap:12px;white-space:nowrap}.station-actions .el-button+.el-button{margin-left:0}</style>
