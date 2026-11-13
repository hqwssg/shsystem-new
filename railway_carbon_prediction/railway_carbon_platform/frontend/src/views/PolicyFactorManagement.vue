<template>
  <div class="page">
    <div class="page-card">
      <h2 class="page-title">政策/外部因子月度数据</h2>
      <p class="page-desc">
        管理煤价、供给、运输、电力、气象、政策等外部因子。该类因子用于 GRA 因素筛选和情景解释，与排放因子分表管理。
      </p>
      <div class="filter-row">
        <el-select v-model="filters.category" placeholder="因子类别" clearable style="width: 160px">
          <el-option v-for="(text, key) in POLICY_CATEGORY_LABEL" :key="key" :label="text" :value="key" />
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
        <el-button type="primary" :icon="Plus" @click="openDialog">新增因子</el-button>
      </div>
    </div>

    <div class="page-card">
      <div class="table-toolbar">
        <div class="title">外部因子列表</div>
        <div class="muted">共 {{ total }} 条</div>
      </div>
      <el-table :data="rows" v-loading="loading" border stripe height="560">
        <el-table-column prop="factorName" label="因子名称" min-width="200" />
        <el-table-column prop="factorId" label="因子编码" min-width="170">
          <template #default="{ row }"><span class="mono">{{ row.factorId }}</span></template>
        </el-table-column>
        <el-table-column label="月份" width="90">
          <template #default="{ row }">{{ formatPeriod(row.period) }}</template>
        </el-table-column>
        <el-table-column label="数值" width="120" align="right">
          <template #default="{ row }">{{ formatNumber(row.value, 4) }}</template>
        </el-table-column>
        <el-table-column prop="unit" label="单位" width="90" />
        <el-table-column label="类别" width="80">
          <template #default="{ row }">{{ label(POLICY_CATEGORY_LABEL, row.category) }}</template>
        </el-table-column>
        <el-table-column label="来源层级" width="90">
          <template #default="{ row }">{{ label(SOURCE_LEVEL_LABEL, row.sourceLevel) }}</template>
        </el-table-column>
        <el-table-column prop="sourceStatus" label="来源状态" width="110" />
        <el-table-column label="仅情景" width="70" align="center">
          <template #default="{ row }">{{ row.scenarioOnly ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column prop="dataSource" label="数据来源" min-width="180" show-overflow-tooltip />
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :page-sizes="[30, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          @current-change="load"
          @size-change="search"
        />
      </div>
    </div>

    <el-dialog v-model="dialogVisible" title="新增政策/外部因子" width="560px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="因子编码" required>
          <el-input v-model="form.factorId" placeholder="如 COAL_PRICE_QHD5500" />
        </el-form-item>
        <el-form-item label="因子名称" required>
          <el-input v-model="form.factorName" placeholder="如 秦皇岛港5500大卡动力煤长协价" />
        </el-form-item>
        <el-form-item label="月份" required>
          <el-date-picker v-model="form.period" type="month" value-format="YYYY-MM" style="width: 100%" />
        </el-form-item>
        <el-form-item label="数值" required>
          <el-input-number v-model="form.value" :precision="4" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="单位" required>
          <el-input v-model="form.unit" placeholder="如 元/吨、℃·d" />
        </el-form-item>
        <el-form-item label="类别">
          <el-select v-model="form.category" style="width: 100%">
            <el-option v-for="(text, key) in POLICY_CATEGORY_LABEL" :key="key" :label="text" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源层级">
          <el-select v-model="form.sourceLevel" style="width: 100%">
            <el-option v-for="(text, key) in SOURCE_LEVEL_LABEL" :key="key" :label="text" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源状态">
          <el-input v-model="form.sourceStatus" placeholder="如 原始、插值" />
        </el-form-item>
        <el-form-item label="仅情景输入">
          <el-switch v-model="form.scenarioOnly" />
        </el-form-item>
        <el-form-item label="数据来源">
          <el-input v-model="form.dataSource" placeholder="文件/机构/URL" />
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
import { ElMessage } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { getPolicyFactors, savePolicyFactors } from '../api'
import {
  POLICY_CATEGORY_LABEL, SOURCE_LEVEL_LABEL, formatNumber, formatPeriod, label
} from '../utils/dict'

const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(30)
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const filters = reactive({ category: '', range: [] })

const form = reactive({
  factorId: 'COAL_PRICE_QHD5500',
  factorName: '秦皇岛港5500大卡动力煤长协价',
  period: '2026-01',
  value: 710,
  unit: '元/吨',
  category: 'price',
  sourceLevel: 'market',
  sourceStatus: '原始',
  scenarioOnly: false,
  dataSource: ''
})

const load = async () => {
  loading.value = true
  try {
    const data = await getPolicyFactors({
      category: filters.category || undefined,
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

const openDialog = () => {
  form.factorId = ''
  form.factorName = ''
  form.period = '2026-01'
  form.value = 0
  form.unit = ''
  form.category = 'price'
  form.sourceLevel = 'market'
  form.sourceStatus = '原始'
  form.scenarioOnly = false
  form.dataSource = ''
  dialogVisible.value = true
}

const save = async () => {
  if (!form.factorId || !form.factorName || !form.period || form.value === null || !form.unit) {
    ElMessage.warning('请填写因子编码、名称、月份、数值和单位')
    return
  }
  saving.value = true
  try {
    await savePolicyFactors({ operator: 'platform', factors: [{ ...form }] })
    ElMessage.success('政策/外部因子已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
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
