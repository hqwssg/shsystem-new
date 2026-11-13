<template>
  <div class="page">
    <div class="page-card">
      <h2 class="page-title">大事件日历表管理</h2>
      <p class="page-desc">
        维护春节、疫情、检修等日历事件，供异常检测解释季节峰谷和确定性能耗变化。事件类型、影响方向均以中文显示。
      </p>
      <div class="filter-row">
        <el-button type="primary" :icon="Plus" @click="openDialog()">新增事件</el-button>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="page-card">
      <el-table :data="rows" v-loading="loading" border stripe height="600">
        <el-table-column prop="eventId" label="事件编码" width="170">
          <template #default="{ row }"><span class="mono">{{ row.eventId }}</span></template>
        </el-table-column>
        <el-table-column label="事件类型" width="120">
          <template #default="{ row }">{{ label(EVENT_TYPE_LABEL, row.eventType) }}</template>
        </el-table-column>
        <el-table-column prop="eventName" label="事件名称" min-width="210" />
        <el-table-column prop="startDate" label="开始日期" width="120" />
        <el-table-column prop="endDate" label="结束日期" width="120" />
        <el-table-column label="适用组织" width="120">
          <template #default="{ row }">{{ row.orgId === 'ALL' ? '全部组织' : orgName(row.orgId) }}</template>
        </el-table-column>
        <el-table-column label="影响方向" width="100">
          <template #default="{ row }">{{ label(IMPACT_LABEL, row.impactDirection) }}</template>
        </el-table-column>
        <el-table-column prop="source" label="来源" min-width="170" show-overflow-tooltip />
        <el-table-column prop="note" label="说明" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDialog(row)">编辑</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑日历事件' : '新增日历事件'" width="560px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="事件编码" required>
          <el-input v-model="form.eventId" placeholder="如 CNY-2026" :disabled="!!form.id" />
        </el-form-item>
        <el-form-item label="事件类型" required>
          <el-select v-model="form.eventType" style="width: 100%">
            <el-option v-for="(text, key) in EVENT_TYPE_LABEL" :key="key" :label="text" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="事件名称" required>
          <el-input v-model="form.eventName" />
        </el-form-item>
        <el-form-item label="开始日期" required>
          <el-date-picker v-model="form.startDate" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="结束日期" required>
          <el-date-picker v-model="form.endDate" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="适用组织">
          <el-select v-model="form.orgId" style="width: 100%">
            <el-option label="全部组织" value="ALL" />
            <el-option v-for="o in orgs" :key="o.orgId" :label="o.orgName" :value="o.orgId" />
          </el-select>
        </el-form-item>
        <el-form-item label="影响方向">
          <el-select v-model="form.impactDirection" style="width: 100%">
            <el-option v-for="(text, key) in IMPACT_LABEL" :key="key" :label="text" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源">
          <el-input v-model="form.source" placeholder="文件/通知/URL" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { deleteCalendarEvent, getCalendarEvents, saveCalendarEvent } from '../api'
import { useMeta } from '../utils/meta'
import { EVENT_TYPE_LABEL, IMPACT_LABEL, label } from '../utils/dict'

const { orgs, orgName } = useMeta()
const rows = ref([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const form = reactive({
  id: null,
  eventId: '',
  eventType: 'spring_festival',
  eventName: '',
  startDate: '',
  endDate: '',
  orgId: 'ALL',
  impactDirection: 'down',
  source: '',
  note: ''
})

const load = async () => {
  loading.value = true
  try {
    rows.value = await getCalendarEvents()
  } finally {
    loading.value = false
  }
}

const openDialog = (row) => {
  if (row) {
    Object.assign(form, row)
  } else {
    Object.assign(form, {
      id: null,
      eventId: '',
      eventType: 'spring_festival',
      eventName: '',
      startDate: '',
      endDate: '',
      orgId: 'ALL',
      impactDirection: 'down',
      source: '',
      note: ''
    })
  }
  dialogVisible.value = true
}

const save = async () => {
  if (!form.eventId || !form.eventName || !form.startDate || !form.endDate) {
    ElMessage.warning('请填写事件编码、名称、开始日期和结束日期')
    return
  }
  saving.value = true
  try {
    await saveCalendarEvent({
      eventId: form.eventId,
      eventType: form.eventType,
      eventName: form.eventName,
      startDate: form.startDate,
      endDate: form.endDate,
      orgId: form.orgId,
      impactDirection: form.impactDirection,
      source: form.source,
      note: form.note
    })
    ElMessage.success('日历事件已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

const remove = async (row) => {
  await ElMessageBox.confirm(`确定删除事件“${row.eventName}”吗？`, '删除确认', { type: 'warning' })
  await deleteCalendarEvent(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>
