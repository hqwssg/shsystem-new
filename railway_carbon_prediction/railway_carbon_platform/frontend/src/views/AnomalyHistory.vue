<template>
  <div class="page">
    <div class="page-card">
      <h2 class="page-title">历史异常数据浏览</h2>
      <p class="page-desc">
        查询复核级异常和关注级异常的历史记录。复核级进入人工审核队列；关注级只进入监控表，用于月度数据质量报告。
      </p>
      <el-tabs v-model="scope" @tab-change="search">
        <el-tab-pane label="复核级异常" name="review" />
        <el-tab-pane label="关注级监控" name="watch" />
      </el-tabs>
      <div class="filter-row">
        <el-select v-model="filters.orgId" placeholder="全部组织" clearable style="width: 160px">
          <el-option v-for="o in orgs" :key="o.orgId" :label="o.orgName" :value="o.orgId" />
        </el-select>
        <el-select v-if="scope === 'review'" v-model="filters.status" placeholder="全部状态" clearable style="width: 150px">
          <el-option v-for="(text, key) in ANOMALY_STATUS_LABEL" :key="key" :label="text" :value="key" />
        </el-select>
        <el-select v-model="filters.level" placeholder="全部等级" clearable style="width: 140px">
          <el-option label="关注" value="关注" />
          <el-option label="异常" value="异常" />
          <el-option label="严重异常" value="严重异常" />
        </el-select>
        <el-date-picker
          v-model="filters.range"
          type="monthrange"
          value-format="YYYY-MM"
          range-separator="至"
          start-placeholder="开始月份"
          end-placeholder="结束月份"
        />
        <el-button type="primary" :icon="Search" @click="search">查询</el-button>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="page-card">
      <div class="table-toolbar">
        <div class="title">异常记录</div>
        <div class="muted">共 {{ total }} 条</div>
      </div>
      <el-table :data="rows" v-loading="loading" border stripe height="560">
        <el-table-column label="组织" width="110">
          <template #default="{ row }">{{ row.orgName || orgName(row.orgId) }}</template>
        </el-table-column>
        <el-table-column label="月份" width="90">
          <template #default="{ row }">{{ formatPeriod(row.period) }}</template>
        </el-table-column>
        <el-table-column label="品种" width="110">
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
        <el-table-column v-if="scope === 'review'" label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="tagType(row.status)" size="small">{{ label(ANOMALY_STATUS_LABEL, row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="scope === 'review'" label="处置" width="100">
          <template #default="{ row }">{{ label(DISPOSITION_LABEL, row.finalDisposition) }}</template>
        </el-table-column>
        <el-table-column prop="evidence" label="证据摘要" min-width="240" show-overflow-tooltip />
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
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
        <el-descriptions-item label="得分">{{ formatNumber(current.score, 4) }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ label(ANOMALY_STATUS_LABEL, current.status) }}</el-descriptions-item>
        <el-descriptions-item label="处置">{{ label(DISPOSITION_LABEL, current.finalDisposition) }}</el-descriptions-item>
        <el-descriptions-item label="触发通道">{{ formatChannels(current.channels || current.channel) }}</el-descriptions-item>
        <el-descriptions-item label="上下文">{{ formatContext(current.contextFlags) }}</el-descriptions-item>
        <el-descriptions-item label="证据" :span="2">
          <div style="line-height: 1.7">{{ current.evidence || '—' }}</div>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { getAnomalies } from '../api'
import { useMeta } from '../utils/meta'
import {
  ANOMALY_CATEGORY_LABEL, ANOMALY_LEVEL_LABEL, ANOMALY_STATUS_LABEL,
  DISPOSITION_LABEL, formatChannels, formatContext, formatNumber, formatPeriod, label, tagType
} from '../utils/dict'

const { orgs, orgName, varName } = useMeta()
const scope = ref('review')
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const detailVisible = ref(false)
const current = ref(null)
const filters = reactive({ orgId: '', status: '', level: '', range: [] })

const load = async () => {
  loading.value = true
  try {
    const data = await getAnomalies({
      scope: scope.value,
      status: scope.value === 'review' ? (filters.status || undefined) : undefined,
      orgId: filters.orgId || undefined,
      level: filters.level || undefined,
      start: filters.range?.[0] || undefined,
      end: filters.range?.[1] || undefined,
      page: page.value,
      size: size.value
    })
    rows.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const search = () => {
  page.value = 1
  load()
}

const openDetail = (row) => {
  current.value = row
  detailVisible.value = true
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
