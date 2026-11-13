<template>
  <div class="app-container energy-analysis">
    <aside class="analysis-nav" aria-label="能耗统计分析导航">
      <el-menu :default-active="activeMenu" :default-openeds="['companies']" @select="navigate">
        <el-sub-menu index="companies">
          <template #title><el-icon class="" ><component :is="$icon('el-icon-office-building')" /></el-icon><span>按分公司统计</span></template>
          <el-menu-item v-for="c in options.companies" :key="c.id" :index="'company:' + c.id">{{ c.name }}</el-menu-item>
          <el-menu-item v-if="!options.companies.length" index="stats">选择公司</el-menu-item>
        </el-sub-menu>
        <el-menu-item index="node"><el-icon class="" ><component :is="$icon('el-icon-connection')" /></el-icon><span>按核算点统计</span></el-menu-item>
        <el-menu-item index="org"><el-icon class="" ><component :is="$icon('el-icon-data-analysis')" /></el-icon><span>各公司数据对比</span></el-menu-item>
      </el-menu>
    </aside>
    <main class="analysis-content">
      <h2>{{ pageTitle }}</h2>
      <p class="muted">按模板确定采集点范围，读取月度核算结果；切换数据口径将同步更新图表、明细和导出。</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <el-button v-if="!ready" :loading="optionsLoading" @click="loadOptions">重新加载公司和模板</el-button>
      <section class="panel" v-loading="optionsLoading">
        <el-form size="small" inline label-width="86px">
          <el-form-item :label="page === 'org' ? '对比公司' : '统计公司'">
            <el-select key="multiple-companies" v-if="page === 'org'" v-model="q.companyIds" multiple collapse-tags filterable placeholder="选择多个公司" @change="syncSelections">
              <el-option v-for="c in options.companies" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
            <el-select key="single-company" v-else :model-value="q.companyIds[0]" filterable placeholder="选择公司" @change="selectCompany">
              <el-option v-for="c in options.companies" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="数据口径">
            <el-radio-group v-model="q.valueMode" size="small" @update:model-value="onModeChange">
              <el-radio-button value="ADOPTED">核算采用值</el-radio-button><el-radio-button value="RAW" :disabled="usesNodeRollup">原始值</el-radio-button><el-radio-button value="ADJUSTED" :disabled="usesNodeRollup">修正值</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <div v-for="s in q.selections" :key="s.companyId" class="template-choice">
            <el-form-item :label="companyName(s.companyId)">
              <el-select v-model="s.templateId" filterable :placeholder="'请选择统计模板'" style="width:340px" @change="s.nodeId = null">
                <el-option v-for="t in companyTemplates(s.companyId)" :key="t.id" :value="t.id" :label="t.name" />
              </el-select>
              <span v-if="!companyTemplates(s.companyId).length" class="warning">没有当前可访问的有效模板</span>
            </el-form-item>
            <el-form-item v-if="page === 'node'" label="核算点">
              <el-select v-model="s.nodeId" filterable clearable placeholder="全部有效核算点" style="width:300px">
                <el-option v-for="n in nodeOptions(s)" :key="n.id" :value="n.id" :label="n.label" />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item label="统计粒度">
            <el-select v-model="q.grain" style="width:110px"><el-option label="月 / 连续月份" value="MONTH" /><el-option label="季度" value="QUARTER" /><el-option label="年度" value="YEAR" /></el-select>
          </el-form-item>
          <el-form-item v-if="q.grain === 'MONTH'" label="时间">
            <el-date-picker v-model="q.months" type="monthrange" value-format="YYYY-MM" range-separator="至" start-placeholder="开始月份" end-placeholder="结束月份" style="width:250px" />
          </el-form-item>
          <el-form-item v-else label="时间">
            <el-date-picker v-model="q.startYear" type="year" value-format="YYYY" style="width:105px" />
            <el-select v-if="q.grain === 'QUARTER'" v-model="q.startQuarter" style="width:95px"><el-option v-for="n in 4" :key="n" :label="'第' + n + '季度'" :value="n" /></el-select>
            <span> 至 </span>
            <el-date-picker v-model="q.endYear" type="year" value-format="YYYY" style="width:105px" />
            <el-select v-if="q.grain === 'QUARTER'" v-model="q.endQuarter" style="width:95px"><el-option v-for="n in 4" :key="n" :label="'第' + n + '季度'" :value="n" /></el-select>
          </el-form-item>
          <el-form-item label="统计维度">
            <el-select v-model="q.dimension" style="width:125px" @change="resetDimension"><el-option label="能源品类" value="ENERGY" /><el-option label="能耗场景" value="SCENE" /><el-option v-if="page !== 'node'" label="部门" value="DEPARTMENT" /><el-option v-if="page !== 'node'" label="站点" value="STATION" /></el-select>
          </el-form-item>
          <el-form-item v-if="q.dimension === 'SCENE'" label="场景层级">
            <el-select v-model="q.categoryLevel" style="width:110px" @change="q.category = ''"><el-option label="一级汇总" :value="1" /><el-option label="二级汇总" :value="2" /></el-select>
            <el-select v-model="q.category" clearable filterable placeholder="全部场景"><el-option v-for="c in sceneOptions" :key="c.code" :label="c.name" :value="c.code" /></el-select>
          </el-form-item>
          <el-form-item label="能源筛选"><el-select v-model="q.energy" clearable filterable placeholder="全部能源"><el-option v-for="e in options.energies" :key="e" :label="energyName(e)" :value="e" /></el-select></el-form-item>
          <el-form-item v-if="q.dimension === 'DEPARTMENT' || q.dimension === 'STATION'" label="组织筛选">
            <el-select v-if="q.dimension === 'DEPARTMENT'" v-model="q.departmentIds" multiple collapse-tags clearable filterable placeholder="全部部门"><el-option v-for="d in options.departments" :key="d.id" :label="d.name" :value="d.id" /></el-select>
            <el-select v-else v-model="q.stationIds" multiple collapse-tags clearable filterable placeholder="全部站点"><el-option v-for="d in options.stations" :key="d.id" :label="d.name" :value="d.id" /></el-select>
          </el-form-item>
          <el-form-item label="对比方式"><el-select v-model="q.compareType" style="width:120px"><el-option :label="page === 'org' ? '组织对比' : '不对比'" :value="page === 'org' ? 'ORGANIZATION' : 'NONE'" /><el-option label="同比" value="YOY" /><el-option label="环比" value="MOM" /></el-select></el-form-item>
          <el-form-item><el-button type="primary" :icon="$icon('el-icon-search')" :loading="loading" :disabled="!ready" @click="runQuery">查询</el-button></el-form-item>
        </el-form>
        <p class="muted">无基准模板时请手动选择。跨年查询沿用所选模板的采集点范围；不同单位分别统计。</p>
        <p v-if="usesNodeRollup" class="muted">排放小类合计来自核算节点月度表的子树合计，单位是核算单位。未选择具体核算点时只统计根节点。</p>
        <p v-if="q.compareType === 'MOM'" class="muted">环比按月、季度、年度分别对齐上一月、上一季度、上一年；连续多月逐月对齐上月。</p>
      </section>
      <template v-if="result">
        <p><el-tag>{{ modeLabel }}</el-tag> {{ result.startMonth }} 至 {{ result.endMonth }} <span v-if="result.previousStartMonth">；基期 {{ result.previousStartMonth }} 至 {{ result.previousEndMonth }}</span></p>
        <el-alert v-for="n in result.notices" :key="n" :title="n" type="warning" show-icon :closable="false" class="notice" />
        <el-alert v-if="result.summary.generatedCount === 0" title="未生成月度结果：当前范围没有可用月度记录，请先完成月度核算。" type="info" :closable="false" />
        <div class="cards">
          <div class="card"><span>碳排放合计 · tCO₂e</span><strong>{{ number(result.summary.selectedCarbon) }}</strong><small v-if="result.summary.incomplete" class="warning">已统计月份合计 · 数据不完整</small></div>
          <div v-for="e in result.summary.energies" :key="e.energy + e.unit" class="card"><span>{{ e.energyName }} · {{ e.unit }}</span><strong>{{ number(e.selectedEnergy) }}</strong><small v-if="e.incomplete" class="warning">已统计可用部分</small></div>
        </div>
        <section class="panel">
          <div class="panel-heading"><b>统计趋势 · {{ modeLabel }}</b><el-radio-group v-model="metric" size="small" @change="renderChart"><el-radio-button value="carbon">碳排放</el-radio-button><el-radio-button value="energy">能耗</el-radio-button></el-radio-group>
            <el-select v-if="metric === 'energy'" v-model="chartEnergy" size="small" @change="renderChart"><el-option v-for="e in result.summary.energies" :key="e.energy + e.unit" :value="e.energy + '|' + e.unit" :label="e.energyName + '（' + e.unit + '）'" /></el-select>
          </div>
          <div ref="chart" class="chart" />
        </section>
        <section class="panel">
          <div class="panel-heading"><b>分组统计 · {{ modeLabel }}</b><div><el-button size="small" @click="openDetails">查看修正明细</el-button><el-button size="small" :loading="exporting" @click="exportExcel">导出 Excel</el-button></div></div>
          <el-table :data="tableRows" border max-height="520" size="small">
            <el-table-column type="expand"><template #default="s"><p>缺失或未生成的采集点月份：{{ (s.row.missingMonths || []).join('、') || '无' }}。具体原因请查看修正明细。</p></template></el-table-column>
            <el-table-column prop="companyName" label="公司" min-width="130" /><el-table-column prop="period" label="期间" width="100" /><el-table-column prop="groupName" label="分组" min-width="140" /><el-table-column prop="energyName" label="能源" width="100" /><el-table-column prop="unit" label="单位" width="80" />
            <el-table-column label="能耗" min-width="120"><template #default="s">{{ number(s.row.selectedEnergy) }}</template></el-table-column><el-table-column label="排放 tCO₂e" min-width="130"><template #default="s">{{ number(s.row.selectedCarbon) }}</template></el-table-column>
            <el-table-column v-if="usesNodeRollup" label="直属能耗" min-width="110"><template #default="s">{{ number(s.row.directEnergy) }}</template></el-table-column>
            <el-table-column v-if="usesNodeRollup" label="缺失采集点" min-width="140"><template #default="s">{{ (s.row.missingPoints || []).join('、') || '无' }}</template></el-table-column>
            <template v-if="temporal"><el-table-column label="基期能耗" min-width="120"><template #default="s">{{ number(s.row.previousEnergy) }}</template></el-table-column><el-table-column label="能耗变化率" width="115"><template #default="s">{{ percentage(s.row.rateEnergy) }}</template></el-table-column><el-table-column label="基期排放" min-width="120"><template #default="s">{{ number(s.row.previousCarbon) }}</template></el-table-column><el-table-column label="排放变化率" width="115"><template #default="s">{{ percentage(s.row.rateCarbon) }}</template></el-table-column></template>
            <el-table-column label="质量提示" min-width="180"><template #default="s"><el-tag v-if="s.row.incomplete" type="warning" size="small">本期不完整</el-tag> <el-tag v-if="s.row.previousIncomplete" type="warning" size="small">基期不完整</el-tag> <el-tag v-if="s.row.abnormalCount" type="warning" size="small">补全 / 异常 {{ s.row.abnormalCount }}</el-tag><span v-if="!s.row.incomplete && !s.row.previousIncomplete && !s.row.abnormalCount">完整</span></template></el-table-column>
          </el-table>
          <el-pagination v-model:current-page="tablePage" :page-size="50" layout="total, prev, pager, next" :total="result.rows.length" />
        </section>
      </template>
      <el-empty v-else-if="!loading" description="选择公司、统计模板和时间后查询" />
      <el-dialog title="采集点月度修正明细" v-model:model-value="detailsVisible" width="94%">
        <p>{{ modeLabel }}；修正差额 = 修正值 − 原始值。缺失为“—”，真实零值为 0。</p>
        <el-radio-group v-if="temporal" v-model="detailPeriod" size="small" @change="detailPage = 1; loadDetails()"><el-radio-button value="current">本期</el-radio-button><el-radio-button value="previous">基期</el-radio-button></el-radio-group>
        <el-table v-loading="detailsLoading" :data="details.content" border max-height="500" size="small">
          <el-table-column prop="companyName" label="公司" width="125" /><el-table-column prop="pointName" label="采集点" min-width="210" /><el-table-column prop="month" label="月份" width="95" /><el-table-column label="能源" width="95"><template #default="s">{{ energyName(s.row.energy) }}</template></el-table-column><el-table-column prop="unit" label="单位" width="70" />
          <el-table-column v-for="c in detailColumns" :key="c.key" :label="c.label" width="125"><template #default="s">{{ number(s.row[c.key]) }}</template></el-table-column>
          <el-table-column label="采用方式" width="100"><template #default="s">{{ s.row.method === 1 ? '修正值' : s.row.method === 2 ? '原始值' : '未明确' }}</template></el-table-column>
          <el-table-column label="质量说明" min-width="240"><template #default="s"><span :class="s.row.dataStatus !== 1 || !s.row.generated || s.row.missing ? 'warning' : ''">{{ s.row.description || (s.row.dataStatus === 1 ? '正常' : '请核对') }}</span></template></el-table-column>
        </el-table>
        <el-pagination v-model:current-page="detailPage" :page-size="50" layout="total, prev, pager, next" :total="details.totalElements" @current-change="loadDetails" />
      </el-dialog>
    </main>
  </div>
</template>

<script>
import * as echarts from 'echarts'
import { saveAs } from 'file-saver'
import { monthlyAnalysisApi } from '@/api/carbon'

const emptyOptions = () => ({ companies: [], categories: [], departments: [], stations: [], energies: [] })
const energyNames = { electricity: '电力', PE: '电力', diesel: '柴油', gasoline: '汽油', natural_gas: '天然气', heat: '热力', PH: '热力' }
export default {
  name: 'CarbonEnergyAnalysis',
  data() {
    const year = String(new Date().getFullYear())
    return {
      page: 'stats', options: emptyOptions(), ready: false, optionsLoading: false, loading: false, error: '', result: null,
      q: { companyIds: [], selections: [], valueMode: 'ADOPTED', grain: 'MONTH', months: [year + '-01', year + '-12'], startYear: year, endYear: year, startQuarter: 1, endQuarter: 4, dimension: 'ENERGY', categoryLevel: 1, energy: '', category: '', departmentIds: [], stationIds: [], compareType: 'NONE' },
      epoch: 0, optionsEpoch: 0, detailEpoch: 0, metric: 'carbon', chartEnergy: '', tablePage: 1, exporting: false,
      detailsVisible: false, detailsLoading: false, detailPage: 1, detailPeriod: 'current', details: { content: [], totalElements: 0 },
      detailColumns: [{ key: 'rawEnergy', label: '原始用量' }, { key: 'adjustedEnergy', label: '修正用量' }, { key: 'adoptedEnergy', label: '采用用量' }, { key: 'energyDifference', label: '用量修正差额' }, { key: 'rawCarbon', label: '原始排放 tCO₂e' }, { key: 'adjustedCarbon', label: '修正排放 tCO₂e' }, { key: 'adoptedCarbon', label: '采用排放 tCO₂e' }, { key: 'carbonDifference', label: '排放修正差额' }]
    }
  },
  computed: {
    activeMenu() { return this.page === 'stats' && this.q.companyIds.length ? 'company:' + this.q.companyIds[0] : this.page },
    pageTitle() { return this.page === 'node' ? '按核算点统计' : this.page === 'org' ? '各公司数据对比' : '按分公司统计' },
    modeLabel() { return { ADOPTED: '核算采用值', RAW: '原始值', ADJUSTED: '修正值' }[this.q.valueMode] },
    temporal() { return ['YOY', 'MOM'].includes(this.q.compareType) },
    usesNodeRollup() { return this.q.dimension === 'ENERGY' && (this.page === 'node' || this.page === 'org') },
    sceneOptions() { return this.options.categories.filter(c => Number(c.level) === this.q.categoryLevel) },
    tableRows() { return this.result ? this.result.rows.slice((this.tablePage - 1) * 50, this.tablePage * 50) : [] },
    cacheKey() { return 'monthly-analysis-v1:' + this.$store.getters.id }
  },
  watch: {
    '$route.query': { handler() { this.applyRoute() }, deep: true },
    q: { deep: true, handler() { this.invalidate(); if (this.ready) this.saveFilters() } }
  },
  created() { this.applyRoute(); this.loadOptions() },
  mounted() { window.addEventListener('resize', this.resizeChart) },
  beforeUnmount() { this.epoch++; this.optionsEpoch++; this.detailEpoch++; window.removeEventListener('resize', this.resizeChart); if (this.chart) this.chart.dispose() },
  methods: {
    async onModeChange() { const reload = this.result || this.loading; await this.$nextTick(); if (reload && this.ready) return this.runQuery() },
    resetDimension() { this.q.category = ''; this.q.departmentIds = []; this.q.stationIds = [] },
    number(v) { return v === null || v === undefined || v === '' ? '—' : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 6 }) },
    percentage(v) { return v === null || v === undefined ? '—' : this.number(v) + '%' },
    energyName(e) { return energyNames[e] || e || '未分类' },
    companyName(id) { const c = this.options.companies.find(c => c.id === id); return c ? c.name : '公司' },
    companyTemplates(id) { const c = this.options.companies.find(c => c.id === id); return c ? c.templates : [] },
    nodeOptions(s) {
      const t = this.companyTemplates(s.companyId).find(t => t.id === s.templateId)
      if (!t) return []
      return t.nodes.map(n => { let depth = 0, parent = n.parentId; const seen = new Set([n.id]); while (parent && !seen.has(parent)) { seen.add(parent); const p = t.nodes.find(x => x.id === parent); if (!p) break; depth++; parent = p.parentId } return { ...n, label: '　'.repeat(depth) + n.name } })
    },
    invalidate() { this.epoch++; this.detailEpoch++; this.loading = false; this.detailsLoading = false; this.result = null; this.tablePage = 1; this.detailsVisible = false; this.details = { content: [], totalElements: 0 }; if (this.chart) this.chart.clear() },
    applyRoute() {
      const view = this.$route.query.analysisView || 'stats'
      this.page = view === 'org' ? 'org' : view === 'node' ? 'node' : 'stats'
      if (view === 'period') this.q.compareType = 'YOY'
      else if (this.page === 'org' && this.q.compareType === 'NONE') this.q.compareType = 'ORGANIZATION'
      else if (this.page !== 'org' && this.q.compareType === 'ORGANIZATION') this.q.compareType = 'NONE'
      const company = Number(this.$route.query.companyId)
      if (this.ready && this.options.companies.some(c => c.id === company)) this.q.companyIds = [company]
      if (this.page !== 'org' && this.q.companyIds.length > 1) this.q.companyIds = this.q.companyIds.slice(0, 1)
      if (this.page === 'node' && !['ENERGY', 'SCENE'].includes(this.q.dimension)) this.q.dimension = 'ENERGY'
      if (this.ready) this.syncSelections()
      this.invalidate()
    },
    navigate(key) { const companyId = key.startsWith('company:') ? key.substring(8) : undefined; const analysisView = companyId ? 'stats' : key; this.$router.push({ path: this.$route.path, query: { ...this.$route.query, analysisView, companyId } }).catch(() => {}) },
    selectCompany(id) { this.q.companyIds = [id]; this.syncSelections() },
    syncSelections() {
      this.q.companyIds = this.q.companyIds.filter(id => this.options.companies.some(c => c.id === id))
      this.q.selections = this.q.companyIds.map(id => {
        const c = this.options.companies.find(c => c.id === id)
        const old = this.q.selections.find(s => s.companyId === id)
        const templateId = old && c.templates.some(t => t.id === old.templateId) ? old.templateId : c.defaultTemplateId || null
        const selection = { companyId: id, templateId, nodeId: old ? old.nodeId : null }
        if (!this.nodeOptions(selection).some(n => n.id === selection.nodeId)) selection.nodeId = null
        return selection
      })
    },
    async loadOptions() {
      const ticket = ++this.optionsEpoch; this.optionsLoading = true; this.ready = false; this.error = ''; this.invalidate()
      try {
        const data = await monthlyAnalysisApi.options(); if (ticket !== this.optionsEpoch) return
        this.options = data
        let cached
        try { cached = JSON.parse(sessionStorage.getItem(this.cacheKey)) } catch (_) { cached = null }
        if (cached) {
          Object.keys(this.q).forEach(k => { if (cached[k] !== undefined) this.q[k] = cached[k] })
          if (!['ADOPTED', 'RAW', 'ADJUSTED'].includes(this.q.valueMode)) this.q.valueMode = 'ADOPTED'
          if (!['MONTH', 'QUARTER', 'YEAR'].includes(this.q.grain)) this.q.grain = 'MONTH'
          if (!['ENERGY', 'SCENE', 'DEPARTMENT', 'STATION'].includes(this.q.dimension)) this.q.dimension = 'ENERGY'
          if (!['NONE', 'ORGANIZATION', 'YOY', 'MOM'].includes(this.q.compareType)) this.q.compareType = 'NONE'
          this.q.companyIds = Array.isArray(this.q.companyIds) ? this.q.companyIds : []; this.q.selections = Array.isArray(this.q.selections) ? this.q.selections : []
          this.q.departmentIds = (this.q.departmentIds || []).filter(id => data.departments.some(d => d.id === id))
          this.q.stationIds = (this.q.stationIds || []).filter(id => data.stations.some(d => d.id === id))
          if (!data.energies.includes(this.q.energy)) this.q.energy = ''
          if (!data.categories.some(c => c.code === this.q.category)) this.q.category = ''
        }
        this.ready = true; this.applyRoute(); this.syncSelections()
        if (!this.q.companyIds.length && data.companies.length === 1) this.selectCompany(data.companies[0].id)
        await this.$nextTick(); this.saveFilters()
      } catch (e) { if (ticket === this.optionsEpoch) this.error = this.errorMessage(e) }
      finally { if (ticket === this.optionsEpoch) this.optionsLoading = false }
    },
    saveFilters() { try { sessionStorage.setItem(this.cacheKey, JSON.stringify(this.q)) } catch (_) { /* unavailable storage does not block querying */ } },
    periodRange() {
      if (this.q.grain === 'MONTH') return this.q.months || []
      const month = (year, n) => year + '-' + String(n).padStart(2, '0')
      return this.q.grain === 'YEAR' ? [month(this.q.startYear, 1), month(this.q.endYear, 12)] : [month(this.q.startYear, this.q.startQuarter * 3 - 2), month(this.q.endYear, this.q.endQuarter * 3)]
    },
    request() {
      const [startMonth, endMonth] = this.periodRange()
      if (!this.q.selections.length || this.q.selections.some(s => !s.templateId)) throw new Error('请选择公司和对应的统计模板')
      if (!/^\d{4}-\d{2}$/.test(startMonth) || !/^\d{4}-\d{2}$/.test(endMonth) || startMonth > endMonth) throw new Error('请选择有效的起止时间')
      if (this.q.compareType === 'ORGANIZATION' && this.q.selections.length < 2 && this.q.departmentIds.length < 2 && this.q.stationIds.length < 2) throw new Error('请选择至少两个公司、部门或站点进行对比')
      const rollup = this.q.dimension === 'ENERGY' && this.page === 'node' ? 'CALC_NODE' : this.q.dimension === 'ENERGY' && this.page === 'org' ? 'ROOT' : 'COLLECTION'
      return { selections: this.q.selections.map(s => ({ ...s, nodeId: this.page === 'node' ? s.nodeId : null })), startMonth, endMonth, grain: this.q.grain, dimension: this.q.dimension, categoryLevel: this.q.categoryLevel, energy: this.q.energy || null, category: this.q.dimension === 'SCENE' ? this.q.category || null : null, valueMode: rollup === 'COLLECTION' ? this.q.valueMode : 'ADOPTED', compareType: this.q.compareType, rollup, departmentIds: this.q.dimension === 'DEPARTMENT' ? this.q.departmentIds : [], stationIds: this.q.dimension === 'STATION' ? this.q.stationIds : [] }
    },
    errorMessage(e) { const d = e.response && e.response.data; return (d && (d.message || d.error)) || e.message || '月度统计查询失败，请检查模型服务和月度表是否已部署' },
    async runQuery() {
      let body
      try { body = this.request() } catch (e) { this.$message.warning(e.message); return }
      this.invalidate(); this.error = ''; const ticket = ++this.epoch; this.loading = true
      try {
        const result = await monthlyAnalysisApi[body.compareType === 'NONE' ? 'query' : 'compare'](body)
        if (ticket !== this.epoch) return
        this.result = result; this.chartEnergy = result.summary.energies.length ? result.summary.energies[0].energy + '|' + result.summary.energies[0].unit : ''
        await this.$nextTick(); if (ticket === this.epoch) this.renderChart()
      } catch (e) { if (ticket === this.epoch) this.error = this.errorMessage(e) }
      finally { if (ticket === this.epoch) this.loading = false }
    },
    chartData() {
      if (!this.result) return { labels: [], series: [] }
      const groups = new Map(), metric = this.metric === 'energy' ? 'Energy' : 'Carbon'
      this.result.rows.forEach(r => {
        if (this.metric === 'energy' && r.energy + '|' + r.unit !== this.chartEnergy) return
        const label = r.companyName + ' · ' + r.groupName
        const add = (name, key) => { if (!groups.has(name)) groups.set(name, new Map()); const values = groups.get(name); const v = r[key]; if (v !== null && v !== undefined) values.set(r.period, (values.get(r.period) || 0) + Number(v)) }
        add(label, 'selected' + metric); if (this.temporal) add(label + ' · 基期', 'previous' + metric)
      })
      return { labels: this.result.periods, series: [...groups].map(([name, values]) => ({ name, type: 'line', connectNulls: false, data: this.result.periods.map(p => values.has(p) ? values.get(p) : null) })) }
    },
    renderChart() {
      if (!this.result || !this.$refs.chart) return
      if (this.chart && this.chart.getDom() !== this.$refs.chart) { this.chart.dispose(); this.chart = null }
      if (!this.chart) this.chart = echarts.init(this.$refs.chart)
      const data = this.chartData()
      this.chart.setOption({ tooltip: { trigger: 'axis' }, legend: { type: 'scroll' }, grid: { left: 75, right: 25, top: 55, bottom: 75 }, dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18 }], xAxis: { type: 'category', data: data.labels }, yAxis: { type: 'value', name: this.metric === 'carbon' ? 'tCO₂e' : this.chartEnergy.split('|')[1] || '' }, series: data.series }, true)
    },
    resizeChart() { if (this.chart) this.chart.resize() },
    openDetails() { this.detailPage = 1; this.detailPeriod = 'current'; this.detailsVisible = true; this.loadDetails() },
    async loadDetails() {
      const ticket = ++this.detailEpoch; this.detailsLoading = true; this.details = { content: [], totalElements: 0 }
      try {
        const body = { ...this.request(), page: this.detailPage - 1, size: 50 }
        if (this.detailPeriod === 'previous' && this.result.previousStartMonth) { body.startMonth = this.result.previousStartMonth; body.endMonth = this.result.previousEndMonth }
        const data = await monthlyAnalysisApi.details(body); if (ticket === this.detailEpoch) this.details = data
      } catch (e) { if (ticket === this.detailEpoch) this.$message.warning(this.errorMessage(e)) }
      finally { if (ticket === this.detailEpoch) this.detailsLoading = false }
    },
    async exportExcel() {
      const ticket = this.epoch; this.exporting = true
      try { const body = this.request(); const blob = await monthlyAnalysisApi.export(body); if (ticket === this.epoch) saveAs(blob, '能耗统计-' + this.modeLabel + '-' + body.startMonth + '至' + body.endMonth + '.xlsx') }
      catch (e) { if (ticket === this.epoch) { if (e.response && e.response.data instanceof Blob) { try { const d = JSON.parse(await e.response.data.text()); this.$message.warning(d.message || d.error || '导出失败') } catch (_) { this.$message.warning('导出失败') } } else this.$message.warning(this.errorMessage(e)) } }
      finally { this.exporting = false }
    }
  }
}
</script>

<style scoped>.energy-analysis {
  display: flex;
  gap: 20px;
  background: #f5f7fa;
  min-height: 85vh;
}

.analysis-nav {
  flex: 0 0 220px;
  background: #fff;
  border: 1px solid #e5eaf0;
  border-radius: 6px;
  align-self: flex-start;
}

.analysis-nav .el-menu {
  border: 0;
}

.analysis-nav .el-menu-item {
  overflow: hidden;
  text-overflow: ellipsis;
}

.analysis-content {
  flex: 1;
  min-width: 0;
}

.analysis-content h2 {
  margin: 0 0 10px;
  font-weight: 500;
}

.muted {
  color: #8090a2;
  font-size: 13px;
  line-height: 1.7;
}

.panel {
  background: #fff;
  border: 1px solid #e5eaf0;
  border-radius: 6px;
  padding: 20px;
  margin: 16px 0;
}

.template-choice {
  border-top: 1px dashed #e5eaf0;
  padding-top: 12px;
}

.notice {
  margin: 10px 0;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(195px, 1fr));
  gap: 14px;
  margin: 16px 0;
}

.card {
  background: #fff;
  border: 1px solid #e5eaf0;
  border-radius: 6px;
  padding: 20px;
}

.card span {
  display: block;
  color: #8090a2;
  font-size: 13px;
}

.card strong {
  display: block;
  font-size: 27px;
  margin: 14px 0 7px;
  color: #263849;
}

.warning {
  color: #d99315;
}

.panel-heading {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: space-between;
  margin-bottom: 14px;
}

.chart {
  height: 390px;
}

.el-pagination {
  margin-top: 15px;
}

.el-tag {
  margin: 2px;
}

.el-form-item {
  vertical-align: top;
}

@media (max-width: 1100px) {
  .energy-analysis {
    display: block;
  }
  .analysis-nav {
    margin-bottom: 15px;
  }
  .analysis-content {
    width: 100%;
  }
}
@media (max-width: 700px) {
  .panel {
    padding: 12px;
  }
  .energy-analysis {
    padding: 10px;
  }
  .energy-analysis :deep(.el-form-item) {
    display: block;
    margin-right: 0;
  }
  .energy-analysis :deep(.el-form-item__label) {
    float: none;
    display: block;
    text-align: left;
    width: auto !important;
  }
  .energy-analysis :deep(.el-form-item__content) {
    display: block;
    max-width: 100%;
  }
  .energy-analysis :deep(.el-select), .energy-analysis :deep(.el-date-editor) {
    max-width: 100%;
  }
  .chart {
    height: 320px;
  }
}</style>
