<template>
  <div class="page">
    <div class="stat-grid">
      <div class="stat-card">
        <div class="label">待审核异常</div>
        <div class="value">{{ total }}</div>
        <div class="muted">复核级</div>
      </div>
      <div class="stat-card">
        <div class="label">严重异常</div>
        <div class="value" style="color: #c0392b">{{ severeCount }}</div>
        <div class="muted">优先处理</div>
      </div>
      <div class="stat-card">
        <div class="label">涉及组织</div>
        <div class="value">{{ involvedOrgs }}</div>
        <div class="muted">当前列表</div>
      </div>
      <div class="stat-card">
        <div class="label">处理方式</div>
        <div class="value" style="font-size: 18px">保留 / 修正 / 排除 / 断点</div>
        <div class="muted">审核后自动重算排放</div>
      </div>
    </div>

    <div class="page-card">
      <h2 class="page-title">异常数据人工审核</h2>
      <p class="page-desc">
        新数据入库后自动进行异常筛选，异常数据进入待审核队列。审核通过前，相关活动数据不会被正式启用；审核通过后系统自动重算排放并追加审计。
      </p>
      <div class="filter-row">
        <el-select v-model="filters.orgId" placeholder="全部组织" clearable style="width: 160px">
          <el-option v-for="o in orgs" :key="o.orgId" :label="o.orgName" :value="o.orgId" />
        </el-select>
        <el-select v-model="filters.level" placeholder="全部等级" clearable style="width: 140px">
          <el-option label="关注" value="关注" />
          <el-option label="异常" value="异常" />
          <el-option label="严重异常" value="严重异常" />
        </el-select>
        <el-button type="primary" :icon="Search" @click="load">查询</el-button>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="page-card">
      <el-table
        :data="rows"
        v-loading="loading"
        border
        stripe
        height="560"
        empty-text="当前没有待审核异常；历史复核级异常已自动关闭，新数据入库后如命中异常会出现在这里"
      >
        <el-table-column label="组织" width="110">
          <template #default="{ row }">{{ row.orgName || orgName(row.orgId) }}</template>
        </el-table-column>
        <el-table-column label="月份" width="90">
          <template #default="{ row }">{{ formatPeriod(row.period) }}</template>
        </el-table-column>
        <el-table-column label="数据品种" width="120">
          <template #default="{ row }">{{ row.varName || varName(row.varId) }}</template>
        </el-table-column>
        <el-table-column label="等级" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="tagType(row.level)" size="small">{{ label(ANOMALY_LEVEL_LABEL, row.level) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="类别" width="150">
          <template #default="{ row }">{{ label(ANOMALY_CATEGORY_LABEL, row.category) }}</template>
        </el-table-column>
        <el-table-column label="得分" width="80" align="right">
          <template #default="{ row }">{{ formatNumber(row.score, 4) }}</template>
        </el-table-column>
        <el-table-column label="实测值" width="110" align="right">
          <template #default="{ row }">{{ formatNumber(row.value) }}</template>
        </el-table-column>
        <el-table-column label="参照值" width="110" align="right">
          <template #default="{ row }">{{ formatNumber(row.referenceValue) }}</template>
        </el-table-column>
        <el-table-column prop="evidence" label="证据摘要" min-width="250" show-overflow-tooltip />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看</el-button>
            <el-button link type="success" @click="openReview(row)">审核</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="load"
        />
      </div>
    </div>

    <el-dialog v-model="detailVisible" title="异常详情" width="680px">
      <el-descriptions v-if="current" :column="2" border>
        <el-descriptions-item label="组织">{{ current.orgName || orgName(current.orgId) }}</el-descriptions-item>
        <el-descriptions-item label="月份">{{ formatPeriod(current.period) }}</el-descriptions-item>
        <el-descriptions-item label="品种">{{ current.varName || varName(current.varId) }}</el-descriptions-item>
        <el-descriptions-item label="等级">{{ label(ANOMALY_LEVEL_LABEL, current.level) }}</el-descriptions-item>
        <el-descriptions-item label="类别">{{ label(ANOMALY_CATEGORY_LABEL, current.category) }}</el-descriptions-item>
        <el-descriptions-item label="综合得分">{{ formatNumber(current.score, 4) }}</el-descriptions-item>
        <el-descriptions-item label="触发通道">{{ formatChannels(current.channels || current.channel) }}</el-descriptions-item>
        <el-descriptions-item label="上下文">{{ formatContext(current.contextFlags) }}</el-descriptions-item>
        <el-descriptions-item label="证据" :span="2">
          <div style="line-height: 1.7">{{ current.evidence || '—' }}</div>
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button type="primary" @click="openReview(current)">进入审核</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reviewVisible" title="异常审核处置" width="560px">
      <el-alert
        v-if="current"
        :title="`${current.orgName || orgName(current.orgId)} · ${formatPeriod(current.period)} · ${current.varName || varName(current.varId)}`"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 18px"
      />
      <el-form :model="reviewForm" label-width="96px">
        <el-form-item label="处置动作" required>
          <el-select v-model="reviewForm.action" style="width: 100%">
            <el-option v-for="(text, key) in DISPOSITION_LABEL" :key="key" :label="text" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="reviewForm.action === 'correct'" label="修正值" required>
          <el-input-number v-model="reviewForm.correctionValue" :min="0" :precision="6" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="审核人" required>
          <el-input v-model="reviewForm.reviewer" />
        </el-form-item>
        <el-form-item label="审核意见">
          <el-input v-model="reviewForm.note" type="textarea" :rows="3" placeholder="说明判断依据、修正来源等" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitReview">提交审核</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import { getAnomalies, reviewAnomaly } from '../api'
import { useMeta } from '../utils/meta'
import {
  ANOMALY_CATEGORY_LABEL, ANOMALY_LEVEL_LABEL, DISPOSITION_LABEL,
  formatChannels, formatContext, formatNumber, formatPeriod, label, tagType
} from '../utils/dict'

const { orgs, orgName, varName } = useMeta()
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const detailVisible = ref(false)
const reviewVisible = ref(false)
const submitting = ref(false)
const current = ref(null)
const filters = reactive({ orgId: '', level: '' })
const reviewForm = reactive({
  action: 'keep',
  correctionValue: null,
  reviewer: 'platform',
  note: ''
})

const severeCount = computed(() => rows.value.filter((x) => x.level === '严重异常').length)
const involvedOrgs = computed(() => new Set(rows.value.map((x) => x.orgId)).size)

const load = async () => {
  loading.value = true
  try {
    const data = await getAnomalies({
      scope: 'review',
      status: 'pending',
      orgId: filters.orgId || undefined,
      level: filters.level || undefined,
      page: page.value,
      size: size.value
    })
    rows.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const openDetail = (row) => {
  current.value = row
  detailVisible.value = true
}

const openReview = (row) => {
  current.value = row
  detailVisible.value = false
  reviewForm.action = 'keep'
  reviewForm.correctionValue = row?.value ?? null
  reviewForm.reviewer = 'platform'
  reviewForm.note = ''
  reviewVisible.value = true
}

const submitReview = async () => {
  if (!current.value) return
  if (reviewForm.action === 'correct' && (reviewForm.correctionValue === null || reviewForm.correctionValue === undefined)) {
    ElMessage.warning('选择“修正数值”时必须填写修正值')
    return
  }
  if (!reviewForm.reviewer) {
    ElMessage.warning('请填写审核人')
    return
  }
  submitting.value = true
  try {
    await reviewAnomaly(current.value.id, {
      action: reviewForm.action,
      correctionValue: reviewForm.correctionValue,
      reviewer: reviewForm.reviewer,
      note: reviewForm.note
    })
    ElMessage.success('审核已提交，排放数据已重新计算')
    reviewVisible.value = false
    await load()
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
