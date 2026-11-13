<template>
  <div class="page">
    <div class="page-card">
      <h2 class="page-title">历史数据浏览</h2>
      <p class="page-desc">浏览已入库的月度活动数据，按组织、品种、月份和质量状态筛选。编码字段均转换为中文名称显示。</p>
      <div class="filter-row">
        <el-select v-model="filters.orgId" placeholder="组织" clearable @change="onOrgChange">
          <el-option v-for="o in orgs.filter(x => x.orgId !== 'SHL')" :key="o.orgId" :label="o.orgName" :value="o.orgId" />
        </el-select>
        <el-select v-model="filters.varId" placeholder="数据品种" clearable filterable>
          <el-option v-for="v in varOptions" :key="v.varId" :label="v.varName" :value="v.varId" />
        </el-select>
        <el-date-picker
          v-model="filters.range"
          type="monthrange"
          value-format="YYYY-MM"
          range-separator="至"
          start-placeholder="开始月份"
          end-placeholder="结束月份"
        />
        <el-select v-model="filters.qualityStatus" placeholder="质量状态" clearable>
          <el-option label="有效" value="valid" />
          <el-option label="待审核" value="pending" />
          <el-option label="已排除" value="excluded" />
        </el-select>
        <el-button type="primary" :icon="Search" @click="search">查询</el-button>
        <el-button :icon="Refresh" @click="reset">重置</el-button>
      </div>
    </div>

    <div class="page-card">
      <div class="table-toolbar">
        <div class="title">数据列表</div>
        <div class="muted">共 {{ total }} 条记录</div>
      </div>
      <el-table :data="rows" v-loading="loading" stripe border height="560">
        <el-table-column label="组织" width="110">
          <template #default="{ row }">{{ row.orgName || orgName(row.orgId) }}</template>
        </el-table-column>
        <el-table-column label="月份" width="90">
          <template #default="{ row }">{{ formatPeriod(row.period) }}</template>
        </el-table-column>
        <el-table-column label="数据品种" width="130">
          <template #default="{ row }">{{ row.varName || varName(row.varId) }}</template>
        </el-table-column>
        <el-table-column label="活动量" width="130" align="right">
          <template #default="{ row }">{{ formatNumber(row.value) }}</template>
        </el-table-column>
        <el-table-column label="报表值" width="130" align="right">
          <template #default="{ row }">{{ formatNumber(row.reportedValue) }}</template>
        </el-table-column>
        <el-table-column prop="unit" label="单位" width="80" />
        <el-table-column label="来源" width="140">
          <template #default="{ row }">{{ label(SOURCE_LABEL, row.sourceStatus) }}</template>
        </el-table-column>
        <el-table-column label="是否推算" width="80" align="center">
          <template #default="{ row }">{{ row.estimated ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="质量状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="tagType(row.qualityStatus)" size="small">
              {{ label(QUALITY_LABEL, row.qualityStatus) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="数据标记" width="220">
          <template #default="{ row }">{{ label(DATA_FLAG_LABEL, row.dataFlag || '') }}</template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :page-sizes="[20, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="load"
          @size-change="search"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { getActivity } from '../api'
import { useMeta } from '../utils/meta'
import {
  DATA_FLAG_LABEL, QUALITY_LABEL, SOURCE_LABEL, formatNumber, formatPeriod, label, tagType
} from '../utils/dict'

const { orgs, vars, orgName, varName, varsForOrg } = useMeta()
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const filters = reactive({
  orgId: '',
  varId: '',
  range: [],
  qualityStatus: ''
})

const varOptions = computed(() => varsForOrg(filters.orgId))

const onOrgChange = () => {
  if (filters.varId && !varOptions.value.some((x) => x.varId === filters.varId)) {
    filters.varId = ''
  }
}

const load = async () => {
  loading.value = true
  try {
    const params = {
      page: page.value,
      size: size.value,
      orgId: filters.orgId || undefined,
      varId: filters.varId || undefined,
      qualityStatus: filters.qualityStatus || undefined,
      start: filters.range?.[0] || undefined,
      end: filters.range?.[1] || undefined
    }
    const data = await getActivity(params)
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

const reset = () => {
  filters.orgId = ''
  filters.varId = ''
  filters.range = []
  filters.qualityStatus = ''
  search()
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
