<template>
  <div class="app-container carbon-statistics">
    <el-tabs v-model="activeTab" class="statistics-tabs" @tab-click="handleTabChange">
      <el-tab-pane label="业务排放数据" name="business" />
      <el-tab-pane label="核算结果" name="calculation" />
    </el-tabs>
    <div v-show="activeTab === 'business'">
    <div class="carbon-toolbar carbon-toolbar--actions">
      <el-button v-if="canExport" :icon="$icon('el-icon-download')" @click="exportCsv">导出结果</el-button>
    </div>

    <section class="carbon-panel">
      <el-form :model="query" size="small" :inline="true" label-width="82px">
        <el-form-item label="模板">
          <el-select v-model="query.templateId" filterable clearable style="width: 220px" @change="handleTemplateChange">
            <el-option v-for="item in templates" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="节点">
          <el-select v-model="query.nodeId" filterable clearable style="width: 240px">
            <el-option v-for="item in nodeOptions" :key="item.id" :label="nodeLabel(item)" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker
            v-model="query.dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="-"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 260px"
          />
        </el-form-item>
        <el-form-item label="来源">
          <el-select v-model="query.dataSource" clearable style="width: 140px">
            <el-option v-for="item in sourceOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="能源类型">
          <el-select v-model="query.energyType" clearable style="width: 140px">
            <el-option label="购入电力" :value="1" />
            <el-option label="化石燃料" :value="2" />
            <el-option label="外购热力" :value="3" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="$icon('el-icon-search')" @click="handleQuery">查询</el-button>
          <el-button :icon="$icon('el-icon-refresh')" @click="resetQuery">重置</el-button>
        </el-form-item>
      </el-form>
    </section>

    <div class="summary-grid">
      <div class="summary-item">
        <span>记录数</span>
        <strong>{{ total }}</strong>
      </div>
      <div class="summary-item">
        <span>碳排放量（tCO2e）</span>
        <strong>{{ formatNumber(summary.totalEmission) }}</strong>
      </div>
      <div class="summary-item">
        <span>自动 / 人工记录</span>
        <strong>{{ summary.autoCount }} / {{ summary.manualCount }}</strong>
      </div>
      <div class="summary-item">
        <span>平均质量</span>
        <strong>{{ formatPercent(summary.averageQuality) }}</strong>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="12">
        <section class="carbon-panel">
          <div class="panel-title">月度排放趋势</div>
          <div ref="trendChart" class="chart"></div>
        </section>
      </el-col>
      <el-col :xs="24" :lg="6">
        <section class="carbon-panel">
          <div class="panel-title">能源构成</div>
          <div ref="energyChart" class="chart"></div>
        </section>
      </el-col>
      <el-col :xs="24" :lg="6">
        <section class="carbon-panel">
          <div class="panel-title">采集方式</div>
          <div ref="sourceChart" class="chart"></div>
        </section>
      </el-col>
    </el-row>

    <section class="carbon-panel">
      <el-table v-loading="loading" :data="records" border>
        <el-table-column label="节点" prop="nodeName" min-width="160" show-overflow-tooltip />
        <el-table-column label="采集点" prop="collectionPointName" min-width="170" show-overflow-tooltip />
        <el-table-column label="日期" prop="dataDate" width="120" align="center" />
        <el-table-column label="能源类型" prop="energyTypeName" width="110" align="center" />
        <el-table-column label="活动量" prop="activityValue" width="130" align="right">
          <template #default="scope">{{ formatNumber(scope.row.activityValue) }}</template>
        </el-table-column>
        <el-table-column label="单位" width="90" align="center">
          <template #default="scope">{{ formatMeasurementUnit(scope.row.activityUnit) }}</template>
        </el-table-column>
        <el-table-column label="排放因子" prop="emissionFactor" width="120" align="right">
          <template #default="scope">{{ formatNumber(scope.row.emissionFactor) }}</template>
        </el-table-column>
        <el-table-column label="碳排放量" prop="calculatedValue" width="140" align="right">
          <template #default="scope">{{ formatNumber(scope.row.calculatedValue) }}</template>
        </el-table-column>
        <el-table-column label="数据来源" prop="dataSource" width="110" align="center">
          <template #default="scope">{{ sourceLabel(scope.row.dataSource) }}</template>
        </el-table-column>
        <el-table-column label="质量评分" prop="qualityScore" width="110" align="center">
          <template #default="scope">{{ formatPercent(scope.row.qualityScore) }}</template>
        </el-table-column>
        <el-table-column label="备注" prop="remarks" min-width="160" show-overflow-tooltip />
      </el-table>

      <el-pagination
        class="table-pagination"
        background
        layout="total, sizes, prev, pager, next, jumper"
        :total="total"
        v-model:page-size="query.size"
        v-model:current-page="query.page"
        :page-sizes="[10, 20, 50, 100]"
        @size-change="loadRecords"
        @current-change="loadRecords"
      />
    </section>
    </div>

    <div v-show="activeTab === 'calculation'">
      <div class="carbon-toolbar carbon-toolbar--actions">
        <el-button v-if="canExport" :icon="$icon('el-icon-download')" :loading="calcExporting" @click="exportCalculationExcel">导出Excel</el-button>
      </div>
      <section class="carbon-panel">
        <el-form :model="calcQuery" size="small" :inline="true" label-width="82px">
          <el-form-item label="模板名称"><el-input v-model.trim="calcQuery.templateName" clearable placeholder="支持模糊查询" style="width: 240px" @keyup.enter="queryCalcTasks" /></el-form-item>
          <el-form-item><el-button type="primary" @click="queryCalcTasks">查询</el-button><el-button @click="resetCalcQuery">重置</el-button></el-form-item>
        </el-form>
      </section>
      <section class="carbon-panel">
        <div class="panel-title">核算任务</div>
        <el-table v-loading="calcLoading" :data="calcTasks" border highlight-current-row @current-change="selectCalcTask">
          <el-table-column prop="id" label="任务ID" width="90" />
          <el-table-column prop="templateId" label="模板ID" width="90" />
          <el-table-column prop="templateName" label="模板名称" min-width="180" show-overflow-tooltip />
          <el-table-column prop="calculationCycleStartDate" label="周期开始" width="120" />
          <el-table-column prop="calculationCycleEndDate" label="周期结束" width="120" />
          <el-table-column prop="status" label="状态" width="90"><template #default="s">{{ calcStatusLabel(s.row.status) }}</template></el-table-column>
          <el-table-column prop="initiatorName" label="发起人" min-width="120" />
          <el-table-column prop="calculationStartTime" label="开始时间" min-width="190"><template #default="s">{{ formatBeijingDateTime(s.row.calculationStartTime) }}</template></el-table-column>
          <el-table-column prop="calculationEndTime" label="结束时间" min-width="190"><template #default="s">{{ formatBeijingDateTime(s.row.calculationEndTime) }}</template></el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="scope">
              <el-button
                v-if="canVoid && Number(scope.row.status) === 2"
                link
                size="small"
                :loading="voidingTaskId === scope.row.id"
                @click="voidCalculation(scope.row)"
              >作废</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination class="table-pagination" background layout="total, sizes, prev, pager, next" :total="calcTotal" v-model:page-size="calcQuery.size" v-model:current-page="calcQuery.page" :page-sizes="[10,20,50,100]" @size-change="loadCalcTasks" @current-change="loadCalcTasks" />
      </section>
      <section class="carbon-panel">
        <div class="panel-title">汇总明细 <span v-if="selectedCalcTask">（任务 {{ selectedCalcTask.id }}）</span></div>
        <el-table v-loading="calcDetailLoading" :data="calcDetails" border>
          <el-table-column prop="sourceNodeId" label="源节点ID" width="100" />
          <el-table-column prop="sourceNodeName" label="源节点" min-width="180" show-overflow-tooltip>
            <template #default="s">{{ s.row.sourceNodeName || '未找到节点' }}</template>
          </el-table-column>
          <el-table-column prop="emissionSubcategoryName" label="排放小类" min-width="130">
            <template #default="s">{{ s.row.emissionSubcategoryName || '未知排放小类' }}</template>
          </el-table-column>
          <el-table-column prop="energyCategoryL1Name" label="能源一级分类" min-width="140" show-overflow-tooltip>
            <template #default="s">{{ s.row.energyCategoryL1Name || '未配置' }}</template>
          </el-table-column>
          <el-table-column prop="energyCategoryL2Name" label="能源二级分类" min-width="140" show-overflow-tooltip>
            <template #default="s">{{ s.row.energyCategoryL2Name || '未配置' }}</template>
          </el-table-column>
          <el-table-column prop="energyCategoryL3Name" label="能源三级分类" min-width="140" show-overflow-tooltip>
            <template #default="s">{{ s.row.energyCategoryL3Name || '未配置' }}</template>
          </el-table-column>
          <el-table-column prop="directEnergyValue" label="直接活动量" width="130" />
          <el-table-column prop="childEnergyValue" label="子节点活动量" width="130" />
          <el-table-column prop="totalEnergyValue" label="节点活动量总计" width="140" />
          <el-table-column prop="calculationUnitCode" label="单位" width="100">
            <template #default="s">{{ s.row.calculationUnitCode || '未配置' }}</template>
          </el-table-column>
          <el-table-column prop="directCarbonEmission" label="直接排放(tCO₂)" width="150" />
          <el-table-column prop="childCarbonEmission" label="子节点排放(tCO₂)" width="150" />
          <el-table-column prop="totalCarbonEmission" label="节点排放总计(tCO₂)" width="170" />
        </el-table>
        <el-pagination class="table-pagination" background layout="total, sizes, prev, pager, next" :total="calcDetailTotal" v-model:page-size="calcDetailQuery.size" v-model:current-page="calcDetailQuery.page" :page-sizes="[10,20,50,100]" @size-change="loadCalcDetails" @current-change="loadCalcDetails" />
      </section>
    </div>
  </div>
</template>

<script>
import * as echarts from 'echarts'
import { templateApi, nodeApi, emissionApi, calcSummaryApi, flattenCarbonTree, pickDefaultCalculationTemplate } from '@/api/carbon'
import { hasAnyPermission, hasAnyRole } from '@/utils/permissionMatch'
import { formatMeasurementUnit } from '@/utils/carbonUnitDisplay'

export default {
  name: 'CarbonStatistics',
  computed: {
    canExport() {
      return hasAnyRole(this.$store.getters.roles, ['admin'])
        || hasAnyPermission(this.$store.getters.permissions, ['carbon:statistics:export'])
    },
    canVoid() {
      return hasAnyRole(this.$store.getters.roles, ['admin'])
        || hasAnyPermission(this.$store.getters.permissions, ['carbon:model:edit'])
    }
  },
  data() {
    return {
      activeTab: 'business',
      calcLoading: false,
      voidingTaskId: null,
      calcDetailLoading: false,
      calcExporting: false,
      calcTasks: [], calcTotal: 0, selectedCalcTask: null,
      calcDetails: [], calcDetailTotal: 0,
      calcQuery: { templateName: '', page: 1, size: 20 },
      calcDetailQuery: { page: 1, size: 20 },
      loading: false,
      templates: [],
      nodeOptions: [],
      records: [],
      total: 0,
      summary: {
        totalEmission: 0,
        averageQuality: null,
        autoCount: 0,
        manualCount: 0,
        factorMissingCount: 0
      },
      query: {
        templateId: null,
        nodeId: null,
        dateRange: [],
        dataSource: '',
        energyType: null,
        page: 1,
        size: 20
      },
      sourceOptions: [
        { label: '手工录入', value: 'MANUAL' },
        { label: '自动采集', value: 'AUTO' },
        { label: '核算结果', value: 'CALCULATED' }
      ],
      trendChart: null,
      energyChart: null,
      sourceChart: null
    }
  },
  created() {
    this.loadTemplates()
  },
  mounted() {
    window.addEventListener('resize', this.resizeCharts)
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.resizeCharts)
    if (this.trendChart) this.trendChart.dispose()
    if (this.energyChart) this.energyChart.dispose()
    if (this.sourceChart) this.sourceChart.dispose()
  },
  methods: {
    formatMeasurementUnit,
    handleTabChange() { if (this.activeTab === 'calculation' && !this.calcTasks.length) this.loadCalcTasks() },
    calcTaskParams() { return { templateName: this.calcQuery.templateName, page: this.calcQuery.page - 1, size: this.calcQuery.size } },
    async loadCalcTasks() { this.calcLoading = true; try { const page = await calcSummaryApi.tasks(this.calcTaskParams()); this.calcTasks = page.content || []; this.calcTotal = page.totalElements || 0; if (!this.selectedCalcTask && this.calcTasks.length) this.selectCalcTask(this.calcTasks[0]) } finally { this.calcLoading = false } },
    queryCalcTasks() { this.calcQuery.page = 1; this.selectedCalcTask = null; this.calcDetails = []; this.loadCalcTasks() },
    resetCalcQuery() { this.calcQuery = { templateName: '', page: 1, size: 20 }; this.queryCalcTasks() },
    async selectCalcTask(row) { if (!row) return; this.selectedCalcTask = row; this.calcDetailQuery.page = 1; await this.loadCalcDetails() },
    async loadCalcDetails() { if (!this.selectedCalcTask) return; this.calcDetailLoading = true; try { const page = await calcSummaryApi.details(this.selectedCalcTask.id, { page: this.calcDetailQuery.page - 1, size: this.calcDetailQuery.size }); this.calcDetails = page.content || []; this.calcDetailTotal = page.totalElements || 0 } finally { this.calcDetailLoading = false } },
    async exportCalculationExcel() { this.calcExporting = true; try { const blob = await calcSummaryApi.exportExcel(this.calcTaskParams()); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `碳排放核算结果_${Date.now()}.xlsx`; link.click(); URL.revokeObjectURL(url) } finally { this.calcExporting = false } },
    calcStatusLabel(status) { return ({ 0: '未开始', 1: '执行中', 2: '成功', 3: '失败', 4: '已作废' })[status] || status },
    async voidCalculation(row) {
      try {
        await this.$confirm(
          `确认作废核算任务 ${row.id} 的当前结果吗？历史明细将保留，作废后可重新核算。`,
          '作废核算结果',
          { type: 'warning', confirmButtonText: '确认作废', cancelButtonText: '取消' }
        )
        this.voidingTaskId = row.id
        await calcSummaryApi.voidTask(row.id)
        this.$message.success('核算结果已作废，可以重新核算')
        this.selectedCalcTask = null
        this.calcDetails = []
        this.calcDetailTotal = 0
        await this.loadCalcTasks()
      } catch (error) {
        if (error !== 'cancel' && error !== 'close') {
          this.$message.error((error && error.message) || '作废核算结果失败')
        }
      } finally {
        this.voidingTaskId = null
      }
    },
    async loadTemplates() {
      try {
        const [templates, baselines] = await Promise.all([
          templateApi.list({ silent: true }),
          templateApi.statisticsBaselines().catch(() => [])
        ])
        this.templates = Array.isArray(templates) ? templates : []
        if (!this.query.templateId) {
          const defaultTemplate = pickDefaultCalculationTemplate(this.templates, baselines)
          if (defaultTemplate) this.query.templateId = defaultTemplate.id
        }
        await this.loadNodes()
        await this.loadRecords()
      } catch (error) {
        this.templates = []
        this.nodeOptions = []
        this.records = []
        this.total = 0
        this.$message.error(this.resolveServiceError(error, '统计模板加载失败，请检查碳排放服务和权限配置。'))
      }
    },
    async handleTemplateChange() {
      this.query.nodeId = null
      await this.loadNodes()
      this.handleQuery()
    },
    async loadNodes() {
      this.nodeOptions = []
      if (!this.query.templateId) return
      try {
        const tree = await nodeApi.tree(this.query.templateId, { silent: true })
        this.nodeOptions = flattenCarbonTree(tree).filter(item => item.typeId === 3 || item.typeId === 4)
      } catch (error) {
        this.$message.warning(this.resolveServiceError(error, '模板节点读取失败，仍可查询全部已审核记录。'))
      }
    },
    queryParams(size) {
      const range = this.query.dateRange || []
      return {
        templateId: this.query.templateId,
        nodeId: this.query.nodeId,
        startDate: range[0],
        endDate: range[1],
        dataSource: this.query.dataSource,
        energyType: this.query.energyType,
        page: this.query.page - 1,
        size: size || this.query.size,
        sortBy: 'dataDate',
        sortDirection: 'DESC'
      }
    },
    async loadRecords() {
      this.loading = true
      try {
        const page = await emissionApi.query(this.queryParams())
        this.records = page.content || []
        this.total = page.totalElements || 0
      } catch (error) {
        this.records = []
        this.total = 0
        this.summary = { totalEmission: 0, averageQuality: null, autoCount: 0, manualCount: 0, factorMissingCount: 0 }
        this.renderCharts({})
        this.$message.error(this.resolveServiceError(error, '统计明细读取失败，请检查模型服务、数据库和数据权限。'))
        return
      } finally {
        this.loading = false
      }
      try {
        await this.loadSummary()
      } catch (error) {
        this.summary = { totalEmission: 0, averageQuality: null, autoCount: 0, manualCount: 0, factorMissingCount: 0 }
        this.renderCharts({})
        this.$message.warning(this.resolveServiceError(error, '明细已读取，但统计汇总暂时不可用。'))
      }
    },
    async loadSummary() {
      const statistics = await emissionApi.statistics(this.queryParams())
      this.summary = statistics.summary || this.summary
      this.renderCharts(statistics)
    },
    handleQuery() {
      this.query.page = 1
      this.loadRecords()
    },
    resetQuery() {
      this.query.dateRange = []
      this.query.dataSource = ''
      this.query.energyType = null
      this.query.page = 1
      this.loadRecords()
    },
    renderCharts(statistics) {
      const trend = statistics.trend || []
      const energy = statistics.energyMix || []
      const source = statistics.sourceMix || []
      this.$nextTick(() => {
        if (!this.trendChart) this.trendChart = echarts.init(this.$refs.trendChart)
        if (!this.energyChart) this.energyChart = echarts.init(this.$refs.energyChart)
        if (!this.sourceChart) this.sourceChart = echarts.init(this.$refs.sourceChart)
        this.trendChart.setOption({
          color: ['#1f8f6b'],
          tooltip: { trigger: 'axis' },
          legend: { data: ['碳排放量'] },
          grid: { left: 36, right: 16, top: 48, bottom: 28 },
          xAxis: { type: 'category', data: trend.map(item => item.period) },
          yAxis: { type: 'value' },
          series: [{ name: '碳排放量', type: 'line', smooth: true, areaStyle: { opacity: 0.08 }, data: trend.map(item => item.value) }]
        })
        this.energyChart.setOption(this.pieOption(energy, ['#2265b4', '#b4691f', '#1f8f6b']))
        this.sourceChart.setOption(this.pieOption(source, ['#1f8f6b', '#2265b4']))
      })
    },
    pieOption(data, colors) {
      return {
        color: colors,
        tooltip: { trigger: 'item' },
        series: [{
          type: 'pie',
          radius: ['44%', '70%'],
          center: ['50%', '52%'],
          label: { formatter: '{b}\n{d}%' },
          data
        }]
      }
    },
    resizeCharts() {
      if (this.trendChart) this.trendChart.resize()
      if (this.energyChart) this.energyChart.resize()
      if (this.sourceChart) this.sourceChart.resize()
    },
    exportCsv() {
      const header = ['节点', '采集点', '日期', '能源类型', '活动量', '单位', '排放因子', '因子单位', '碳排放量(tCO2e)', '数据来源', '质量评分', '备注']
      const rows = this.records.map(item => [
        item.nodeName || '',
        item.collectionPointName || '',
        item.dataDate || '',
        item.energyTypeName || '',
        item.activityValue || '',
        item.activityUnit || '',
        item.emissionFactor || '',
        item.factorUnit || '',
        item.calculatedValue || '',
        this.sourceLabel(item.dataSource),
        item.qualityScore || '',
        item.remarks || ''
      ])
      const csv = [header].concat(rows).map(row => row.map(value => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\n')
      this.downloadText(csv, '碳排放统计查询.csv', 'text/csv;charset=utf-8')
    },
    downloadText(content, filename, type) {
      const blob = new Blob([content], { type })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
    },
    sourceLabel(value) {
      const item = this.sourceOptions.find(source => source.value === value)
      return item ? item.label : value
    },
    nodeLabel(item) {
      return `${'　'.repeat(item.level || 0)}${item.name}`
    },
    formatNumber(value) {
      if (value === undefined || value === null || value === '') return '-'
      return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })
    },
    formatPercent(value) {
      if (value === undefined || value === null || value === '') return '-'
      return `${(Number(value) * 100).toFixed(0)}%`
    },
    formatBeijingDateTime(value) {
      if (!value) return '-'
      const raw = String(value)
      const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
      const normalized = raw.replace(' ', 'T')
      // Backend LocalDateTime values are serialized without an offset but are
      // stored/transmitted as UTC. Convert them to Beijing time explicitly.
      const date = new Date(hasZone ? normalized : `${normalized}Z`)
      if (Number.isNaN(date.getTime())) return raw.replace('T', ' ')
      const parts = new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'Asia/Shanghai',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
      }).formatToParts(date).reduce((result, part) => {
        result[part.type] = part.value
        return result
      }, {})
      return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`
    },
    resolveServiceError(error, fallback) {
      const response = error && error.response
      const body = response && response.data
      return (body && (body.msg || body.message || body.error)) || (error && error.message) || fallback
    }
  }
}
</script>

<style scoped lang="scss">
.carbon-statistics {
  min-height: calc(100vh - 84px);
  background: #f6f8fb;
}

.carbon-toolbar,
.panel-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.carbon-toolbar {
  margin-bottom: 16px;

  h2 {
    margin: 0 0 6px;
    color: #1f2d3d;
    font-size: 22px;
  }

  span {
    color: #7a8797;
  }
}

.carbon-toolbar--actions {
  justify-content: flex-end;
}

.carbon-panel {
  margin-bottom: 16px;
  padding: 16px;
  border: 1px solid #e5eaf1;
  border-radius: 6px;
  background: #fff;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.summary-item {
  padding: 18px;
  border: 1px solid #e5eaf1;
  border-radius: 6px;
  background: #fff;

  span {
    display: block;
    color: #7a8797;
    font-size: 13px;
  }

  strong {
    display: block;
    margin-top: 10px;
    color: #1f2d3d;
    font-size: 24px;
  }
}

.panel-title {
  margin-bottom: 12px;
  color: #1f2d3d;
  font-weight: 700;
}

.chart {
  width: 100%;
  height: 330px;
}

.table-pagination {
  margin-top: 16px;
  text-align: right;
}

@media (max-width: 1000px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .carbon-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .carbon-toolbar--actions {
    align-items: flex-end;
  }

  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
