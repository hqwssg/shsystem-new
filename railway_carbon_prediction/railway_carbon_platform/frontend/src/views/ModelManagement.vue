<template>
  <div class="page">
    <div class="stat-grid">
      <div class="stat-card">
        <div class="label">模型版本</div>
        <div class="value">{{ models.length }}</div>
        <div class="muted">含候选/启用/弃用</div>
      </div>
      <div class="stat-card">
        <div class="label">冠军模型</div>
        <div class="value">{{ championCount }}</div>
        <div class="muted">每个组织一个</div>
      </div>
      <div class="stat-card">
        <div class="label">运行中任务</div>
        <div class="value">{{ runningJobs }}</div>
        <div class="muted">训练/预测任务</div>
      </div>
      <div class="stat-card">
        <div class="label">最近训练</div>
        <div class="value" style="font-size: 17px">{{ latestTrained || '—' }}</div>
        <div class="muted">最近模型训练时间</div>
      </div>
    </div>

    <div class="page-card">
      <h2 class="page-title">模型管理</h2>
      <p class="page-desc">
        查看各组织冠军模型与候选模型，展示滑动窗口、测试指标和工件路径。支持手动提交训练任务，并在下方查看训练进度。
      </p>
      <div class="filter-row">
        <el-select v-model="orgId" placeholder="全部组织" clearable style="width: 170px" @change="loadModels">
          <el-option v-for="o in orgs" :key="o.orgId" :label="o.orgName" :value="o.orgId" />
        </el-select>
        <el-button type="primary" :icon="VideoPlay" @click="trainVisible = true">手动训练</el-button>
        <el-button :icon="Refresh" @click="reloadAll">刷新</el-button>
      </div>
    </div>

    <div class="page-card">
      <div class="table-toolbar">
        <div class="title">模型版本</div>
        <div class="muted">共 {{ models.length }} 个</div>
      </div>
      <el-table :data="models" v-loading="loading" border stripe height="420">
        <el-table-column label="组织" width="130">
          <template #default="{ row }">{{ row.orgName || orgName(row.orgId) }}</template>
        </el-table-column>
        <el-table-column label="模型类型" width="150">
          <template #default="{ row }">{{ label(MODEL_TYPE_LABEL, row.modelType) }}</template>
        </el-table-column>
        <el-table-column prop="modelId" label="模型编号" min-width="260">
          <template #default="{ row }"><span class="mono">{{ row.modelId }}</span></template>
        </el-table-column>
        <el-table-column label="窗口 W" width="90" align="center">
          <template #default="{ row }">{{ row.windowSize }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="tagType(row.status)" size="small">{{ label(MODEL_STATUS_LABEL, row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="冠军" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.champion" type="success" size="small">冠军</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="MASE" width="90" align="right">
          <template #default="{ row }">{{ metric(row, 'MASE') }}</template>
        </el-table-column>
        <el-table-column label="MAPE(%)" width="100" align="right">
          <template #default="{ row }">{{ metric(row, 'MAPE') }}</template>
        </el-table-column>
        <el-table-column prop="trainedAt" label="训练时间" width="165" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button
              v-if="row.status === 'deprecated'"
              link
              type="danger"
              @click="removeModel(row)"
            >删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="page-card">
      <div class="table-toolbar">
        <div class="title">训练/预测任务</div>
        <div class="muted">每 3 秒自动刷新运行中任务</div>
      </div>
      <el-table :data="jobs" border stripe height="260">
        <el-table-column prop="jobId" label="任务编号" min-width="260">
          <template #default="{ row }"><span class="mono">{{ row.jobId }}</span></template>
        </el-table-column>
        <el-table-column label="类型" width="110">
          <template #default="{ row }">{{ label(JOB_TYPE_LABEL, row.jobType) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="tagType(row.status)" size="small">{{ label(JOB_STATUS_LABEL, row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="operator" label="提交人" width="110" />
        <el-table-column prop="createdAt" label="创建时间" width="170" />
        <el-table-column prop="finishedAt" label="完成时间" width="170" />
        <el-table-column prop="error" label="错误信息" min-width="220" show-overflow-tooltip />
      </el-table>
    </div>

    <el-dialog v-model="detailVisible" title="模型详情" width="760px">
      <el-descriptions v-if="current" :column="2" border>
        <el-descriptions-item label="模型编号" :span="2">{{ current.modelId }}</el-descriptions-item>
        <el-descriptions-item label="组织">{{ current.orgName || orgName(current.orgId) }}</el-descriptions-item>
        <el-descriptions-item label="模型类型">{{ label(MODEL_TYPE_LABEL, current.modelType) }}</el-descriptions-item>
        <el-descriptions-item label="窗口 W">{{ current.windowSize }}</el-descriptions-item>
        <el-descriptions-item label="预测步长">{{ current.horizon }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ label(MODEL_STATUS_LABEL, current.status) }}</el-descriptions-item>
        <el-descriptions-item label="冠军">{{ current.champion ? '是' : '否' }}</el-descriptions-item>
        <el-descriptions-item label="训练区间">{{ current.trainStart }} ~ {{ current.trainEnd }}</el-descriptions-item>
        <el-descriptions-item label="样本数">{{ current.nSamples }}</el-descriptions-item>
        <el-descriptions-item label="工件路径" :span="2">{{ current.artifactPath }}</el-descriptions-item>
      </el-descriptions>
      <div class="table-toolbar" style="margin-top: 18px">
        <div class="title" style="font-size: 14px">测试/训练指标（JSON）</div>
      </div>
      <div class="json-box">{{ prettyMetrics }}</div>
    </el-dialog>

    <el-dialog v-model="trainVisible" title="手动训练" width="560px">
      <el-form :model="trainForm" label-width="96px">
        <el-form-item label="训练组织" required>
          <el-select v-model="trainForm.orgIds" multiple style="width: 100%">
            <el-option v-for="o in orgs.filter(x => x.orgId !== 'SHL')" :key="o.orgId" :label="o.orgName" :value="o.orgId" />
          </el-select>
        </el-form-item>
        <el-form-item label="训练模式">
          <el-select v-model="trainForm.mode" style="width: 100%">
            <el-option label="自动" value="auto" />
            <el-option label="全量重训" value="full" />
            <el-option label="增量微调" value="finetune" />
          </el-select>
        </el-form-item>
        <el-form-item label="截止月份">
          <el-date-picker v-model="trainForm.asOf" type="month" value-format="YYYY-MM" style="width: 100%" />
        </el-form-item>
        <el-form-item label="强制重训">
          <el-switch v-model="trainForm.force" />
        </el-form-item>
        <el-form-item label="提交人">
          <el-input v-model="trainForm.operator" />
        </el-form-item>
      </el-form>
      <el-alert
        title="训练任务由 Python 预测算法服务执行，提交后可在任务列表查看进度。"
        type="info"
        :closable="false"
        show-icon
      />
      <template #footer>
        <el-button @click="trainVisible = false">取消</el-button>
        <el-button type="primary" :loading="training" @click="submitTrain">提交训练</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, VideoPlay } from '@element-plus/icons-vue'
import { deleteModel, getJob, getJobs, getModels, trainModels } from '../api'
import { useMeta } from '../utils/meta'
import {
  JOB_STATUS_LABEL, JOB_TYPE_LABEL, MODEL_STATUS_LABEL, MODEL_TYPE_LABEL,
  formatNumber, label, tagType
} from '../utils/dict'

const { orgs, orgName } = useMeta()
const models = ref([])
const jobs = ref([])
const orgId = ref('')
const loading = ref(false)
const training = ref(false)
const detailVisible = ref(false)
const trainVisible = ref(false)
const current = ref(null)
let timer = null

const trainForm = reactive({
  orgIds: ['JLG', 'SNF', 'YPF'],
  mode: 'auto',
  asOf: '2025-12',
  force: false,
  operator: 'platform'
})

const championCount = computed(() => models.value.filter((x) => x.champion).length)
const runningJobs = computed(() => jobs.value.filter((x) => ['queued', 'running'].includes(x.status)).length)
const latestTrained = computed(() => models.value[0]?.trainedAt || '')
const prettyMetrics = computed(() => {
  if (!current.value?.metrics) return '—'
  return JSON.stringify(current.value.metrics, null, 2)
})

const metric = (row, key) => {
  const m = row.metrics?.test_2025 || {}
  const v = m[key]
  return v === undefined || v === null ? '—' : formatNumber(v, 2)
}

const loadModels = async () => {
  loading.value = true
  try {
    models.value = await getModels({ orgId: orgId.value || undefined })
  } finally {
    loading.value = false
  }
}

const loadJobs = async () => {
  jobs.value = await getJobs({ limit: 50 })
}

const reloadAll = async () => {
  await Promise.all([loadModels(), loadJobs()])
}

const openDetail = (row) => {
  current.value = row
  detailVisible.value = true
}

const removeModel = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定删除已弃用模型“${row.modelId}”吗？仅删除模型注册记录，不删除工件文件；如已有预测结果引用，将不允许删除。`,
      '删除模型',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
    )
    await deleteModel(row.modelId)
    ElMessage.success('模型已删除')
    await loadModels()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      // HTTP 错误已由 axios 拦截器提示
    }
  }
}

const submitTrain = async () => {
  if (!trainForm.orgIds.length) {
    ElMessage.warning('请选择至少一个训练组织')
    return
  }
  training.value = true
  try {
    const result = await trainModels({ ...trainForm })
    ElMessage.success(`训练任务已提交：${result.job_id || ''}`)
    trainVisible.value = false
    await loadJobs()
    monitor(result.job_id)
  } finally {
    training.value = false
  }
}

const monitor = (jobId) => {
  if (!jobId) return
  if (timer) clearInterval(timer)
  timer = setInterval(async () => {
    try {
      await loadJobs()
      const job = await fetchJob(jobId)
      if (job?.status === 'succeeded' || job?.status === 'failed') {
        clearInterval(timer)
        timer = null
        await reloadAll()
      }
    } catch {
      // 轮询失败时保持页面可用
    }
  }, 3000)
}

const fetchJob = async (jobId) => getJob(jobId)

onMounted(reloadAll)
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>
