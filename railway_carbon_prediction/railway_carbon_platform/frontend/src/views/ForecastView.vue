<template>
  <div class="page">
    <div class="page-card">
      <h2 class="page-title">碳排放预测</h2>
      <p class="page-desc">
        查看未来 12 个月碳排放预测、历史排放趋势和平台 API。预测值为可比口径，同时保留报表口径折算值；编码字段均以中文展示。
      </p>
      <div class="filter-row">
        <el-select v-model="orgId" placeholder="组织" style="width: 160px" @change="loadAll">
          <el-option v-for="o in orgs.filter(x => x.orgId !== 'SHL')" :key="o.orgId" :label="o.orgName" :value="o.orgId" />
        </el-select>
        <el-select v-model="scenario" placeholder="情景" style="width: 150px" @change="loadForecast">
          <el-option v-for="(text, key) in SCENARIO_LABEL" :key="key" :label="text" :value="key" />
        </el-select>
        <el-button type="primary" :icon="Refresh" :loading="generating" @click="regenerate">重新生成预测</el-button>
        <el-button :icon="Download" @click="exportCsv">导出预测 CSV</el-button>
        <span v-if="generationMessage" class="generation-status">{{ generationMessage }}</span>
      </div>
    </div>

    <el-tabs v-model="tab" class="forecast-tabs">
      <el-tab-pane label="预测结果" name="forecast">
        <div class="stat-grid">
          <div class="stat-card">
            <div class="label">2026 年预测合计</div>
            <div class="value">{{ formatNumber(forecastTotal, 0) }}<span class="suffix">tCO2e</span></div>
            <div class="muted">可比口径 · {{ scenarioLabel }}</div>
          </div>
          <div class="stat-card">
            <div class="label">2025 年实际合计</div>
            <div class="value">{{ formatNumber(history2025Total, 0) }}<span class="suffix">tCO2e</span></div>
            <div class="muted">可比口径</div>
          </div>
          <div class="stat-card">
            <div class="label">同比变化</div>
            <div class="value" :style="{ color: yoy >= 0 ? '#c0392b' : '#1e8449' }">
              {{ yoy === null ? '—' : `${yoy > 0 ? '+' : ''}${yoy.toFixed(2)}%` }}
            </div>
            <div class="muted">2026 预测 vs 2025 实际</div>
          </div>
          <div class="stat-card">
            <div class="label">预测区间</div>
            <div class="value" style="font-size: 18px">90%</div>
            <div class="muted">按模型残差/回测生成</div>
          </div>
        </div>

        <div class="page-card">
          <div class="table-toolbar">
            <div class="title">{{ orgName(orgId) }} · 实际与预测趋势</div>
            <div class="muted">单位：tCO2e</div>
          </div>
          <div ref="chartRef" class="chart"></div>
        </div>

        <div class="page-card">
          <div class="table-toolbar">
            <div class="title">未来 12 个月预测明细</div>
            <div class="muted">共 {{ forecast.length }} 条</div>
          </div>
          <el-table :data="forecast" border stripe height="420">
            <el-table-column label="月份" width="120">
              <template #default="{ row }">{{ formatPeriod(row.period) }}</template>
            </el-table-column>
            <el-table-column label="组织" width="130">
              <template #default="{ row }">{{ row.orgName || orgName(row.orgId) }}</template>
            </el-table-column>
            <el-table-column label="情景" width="120">
              <template #default="{ row }">{{ label(SCENARIO_LABEL, row.scenario) }}</template>
            </el-table-column>
            <el-table-column label="点预测" width="150" align="right">
              <template #default="{ row }">{{ formatNumber(row.point) }}</template>
            </el-table-column>
            <el-table-column label="区间下界" width="150" align="right">
              <template #default="{ row }">{{ formatNumber(row.lowerBound) }}</template>
            </el-table-column>
            <el-table-column label="区间上界" width="150" align="right">
              <template #default="{ row }">{{ formatNumber(row.upperBound) }}</template>
            </el-table-column>
            <el-table-column label="报表口径" width="150" align="right">
              <template #default="{ row }">{{ formatNumber(row.reportedPoint) }}</template>
            </el-table-column>
            <el-table-column label="置信水平" width="110" align="center">
              <template #default="{ row }">{{ row.confidenceLevel }}</template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="历史数据" name="history">
        <div class="page-card">
          <div class="filter-row">
            <el-date-picker
              v-model="historyRange"
              type="monthrange"
              value-format="YYYY-MM"
              range-separator="至"
              start-placeholder="开始月份"
              end-placeholder="结束月份"
            />
            <el-button type="primary" :icon="Search" @click="loadHistory">查询</el-button>
          </div>
        </div>
        <div class="page-card">
          <div class="table-toolbar">
            <div class="title">{{ orgName(orgId) }} · 历史排放</div>
            <div class="muted">共 {{ history.length }} 条</div>
          </div>
          <el-table :data="history" border stripe height="560">
            <el-table-column label="月份" width="110">
              <template #default="{ row }">{{ formatPeriod(row.period) }}</template>
            </el-table-column>
            <el-table-column label="报表口径" width="170" align="right">
              <template #default="{ row }">{{ formatNumber(row.totalReportedTco2) }}</template>
            </el-table-column>
            <el-table-column label="可比口径" width="170" align="right">
              <template #default="{ row }">{{ formatNumber(row.totalComparableTco2) }}</template>
            </el-table-column>
            <el-table-column label="电力因子" width="130" align="right">
              <template #default="{ row }">{{ Number(row.electricityFactor).toFixed(4) }}</template>
            </el-table-column>
            <el-table-column label="热力因子" width="120" align="right">
              <template #default="{ row }">{{ Number(row.heatFactor).toFixed(4) }}</template>
            </el-table-column>
            <el-table-column prop="factorVersion" label="因子版本" min-width="240">
              <template #default="{ row }"><span class="mono">{{ row.factorVersion || '—' }}</span></template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="API 接口" name="api">
        <div class="page-card">
          <h3 class="page-title" style="font-size: 16px">平台对外 API</h3>
          <p class="page-desc">平台其他系统可通过以下接口获取预测结果和历史排放数据；接口统一返回 JSON。</p>
          <el-table :data="apiList" border stripe>
            <el-table-column label="方法" width="90">
              <template #default="{ row }">
                <el-tag type="success" size="small">{{ row.method }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="path" label="接口路径" min-width="330">
              <template #default="{ row }"><span class="mono">{{ row.path }}</span></template>
            </el-table-column>
            <el-table-column prop="description" label="说明" min-width="280" />
            <el-table-column label="操作" width="110">
              <template #default="{ row }">
                <el-button link type="primary" @click="copy(row.sample)">复制示例</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="page-card" v-if="apiList.length">
          <div class="table-toolbar">
            <div class="title">调用示例</div>
          </div>
          <pre class="json-box">{{ apiList[0].sample }}</pre>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Refresh, Search } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { getApiInfo, getDashboard, getForecast, getHistory, getJob, generateForecast } from '../api'
import { useMeta } from '../utils/meta'
import { SCENARIO_LABEL, formatNumber, formatPeriod, label } from '../utils/dict'

const { orgs, orgName } = useMeta()
const orgId = ref('JLG')
const scenario = ref('BAU')
const tab = ref('forecast')
const forecast = ref([])
const history = ref([])
const dashboard = ref([])
const apiList = ref([])
const historyRange = ref(['2024-01', '2025-12'])
const generating = ref(false)
const generationMessage = ref('')
const chartRef = ref(null)
let chart = null
let loadSequence = 0

const forecastTotal = computed(() => forecast.value.reduce((s, x) => s + Number(x.point || 0), 0))
const history2025Total = computed(() => history.value
  .filter((x) => String(x.period).startsWith('2025'))
  .reduce((s, x) => s + Number(x.totalComparableTco2 || 0), 0))
const yoy = computed(() => {
  if (!history2025Total.value) return null
  return ((forecastTotal.value - history2025Total.value) / history2025Total.value) * 100
})
const scenarioLabel = computed(() => label(SCENARIO_LABEL, scenario.value))

const loadForecast = async () => {
  forecast.value = await getForecast({ orgId: orgId.value, scenario: scenario.value })
  await nextTick()
  renderChart()
}

const loadHistory = async () => {
  history.value = await getHistory({
    orgId: orgId.value,
    start: historyRange.value?.[0],
    end: historyRange.value?.[1]
  })
  await nextTick()
  renderChart()
}

const loadAll = async () => {
  const sequence = ++loadSequence
  const [nextDashboard, nextForecast, nextHistory] = await Promise.all([
    getDashboard(),
    getForecast({ orgId: orgId.value, scenario: scenario.value }),
    getHistory({
      orgId: orgId.value,
      start: historyRange.value?.[0],
      end: historyRange.value?.[1]
    })
  ])
  if (sequence !== loadSequence) return
  dashboard.value = nextDashboard
  forecast.value = nextForecast
  history.value = nextHistory
  await nextTick()
  renderChart()
}

const regenerate = async () => {
  generating.value = true
  generationMessage.value = '正在提交预测任务，请勿重复点击'
  try {
    const submitted = await generateForecast({
      orgIds: [orgId.value],
      horizon: 12,
      scenario: scenario.value,
      asOf: '2025-12',
      writeDb: true,
      operator: 'platform',
      asyncRun: true
    })
    const jobId = submitted?.job_id
    if (!jobId) throw new Error('预测任务未返回任务编号')
    generationMessage.value = '模型可能需要较长时间，正在生成预测数据'
    const result = await waitForJob(jobId)
    if (result.status !== 'succeeded') {
      throw new Error(result.error || '预测任务失败')
    }
    ElMessage.success('预测已重新生成')
    await loadAll()
  } catch (error) {
    const message = error?.message || '预测任务失败'
    ElMessage.error(message)
  } finally {
    generating.value = false
    generationMessage.value = ''
  }
}

const waitForJob = async (jobId) => {
  const deadline = Date.now() + 10 * 60 * 1000
  while (Date.now() < deadline) {
    const job = await getJob(jobId)
    if (job?.status === 'succeeded' || job?.status === 'failed') return job
    await new Promise((resolve) => window.setTimeout(resolve, 2000))
  }
  throw new Error('预测任务等待超时，请到任务记录中查看后台状态')
}

const renderChart = () => {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  const map = new Map()
  history.value.forEach((x) => {
    const key = formatPeriod(x.period)
    map.set(key, {
      ...(map.get(key) || {}),
      period: key,
      actual: Number(x.totalComparableTco2 || 0)
    })
  })
  forecast.value.forEach((x) => {
    const key = formatPeriod(x.period)
    map.set(key, {
      ...(map.get(key) || {}),
      period: key,
      point: Number(x.point || 0),
      lower: Number(x.lowerBound || 0),
      upper: Number(x.upperBound || 0)
    })
  })
  const rows = [...map.values()].sort((a, b) => a.period.localeCompare(b.period))
  chart.setOption({
    color: ['#2f6fb2', '#e67e22', '#95a5a6'],
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v) => `${formatNumber(v, 0)} tCO2e`
    },
    legend: { data: ['历史实际', '预测点值', '预测区间上界'], top: 4 },
    grid: { left: 70, right: 30, top: 42, bottom: 50 },
    xAxis: {
      type: 'category',
      data: rows.map((x) => x.period),
      axisLabel: { color: '#6b7a8d', fontSize: 11 },
      axisLine: { lineStyle: { color: '#dfe6ef' } }
    },
    yAxis: {
      type: 'value',
      name: 'tCO2e',
      axisLabel: { color: '#6b7a8d', formatter: (v) => (v / 1000).toFixed(0) + 'k' },
      splitLine: { lineStyle: { color: '#eef2f7' } }
    },
    series: [
      {
        name: '历史实际',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        data: rows.map((x) => x.actual ?? null),
        areaStyle: { opacity: 0.06 }
      },
      {
        name: '预测点值',
        type: 'line',
        smooth: true,
        symbol: 'diamond',
        symbolSize: 6,
        data: rows.map((x) => x.point ?? null),
        lineStyle: { type: 'dashed', width: 2 }
      },
      {
        name: '预测区间上界',
        type: 'line',
        symbol: 'none',
        data: rows.map((x) => x.upper ?? null),
        lineStyle: { type: 'dotted', width: 1 }
      }
    ]
  })
}

const exportCsv = () => {
  const header = ['月份', '情景', '点预测', '区间下界', '区间上界', '报表口径']
  const lines = [header.join(',')].concat(forecast.value.map((x) => [
    formatPeriod(x.period), label(SCENARIO_LABEL, x.scenario), x.point, x.lowerBound, x.upperBound, x.reportedPoint
  ].join(',')))
  const blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `${orgId.value}-${scenario.value}-预测.csv`
  link.click()
  URL.revokeObjectURL(link.href)
}

const copy = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('示例已复制')
  } catch {
    ElMessage.warning('浏览器不允许复制，请手动选择')
  }
}

const resize = () => chart?.resize()

onMounted(async () => {
  apiList.value = await getApiInfo()
  await loadAll()
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})
</script>

<style scoped>
.forecast-tabs {
  margin-top: -4px;
}

.chart {
  width: 100%;
  height: 380px;
}

.generation-status {
  color: #6b7a8d;
  font-size: 13px;
}
</style>
