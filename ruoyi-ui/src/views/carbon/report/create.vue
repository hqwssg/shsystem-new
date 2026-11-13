<template>
  <div class="app-container">
    <h3>新建碳排放报告</h3>
    <el-form label-width="120px" size="small" style="max-width:800px" :disabled="saving">
      <el-form-item label="报告公司">
        <el-select v-model="form.deptId" filterable clearable :loading="subjectsLoading" :disabled="subjectsLoading" placeholder="请选择报告公司" style="width:100%">
          <el-option v-for="item in subjects" :key="item.deptId" :value="item.deptId" :disabled="!item.configured" :label="subjectLabel(item)" />
        </el-select>
        <el-alert v-if="subjectsError" :title="subjectsError" type="error" :closable="false" />
        <p v-else-if="!subjectsLoading && subjects.length === 0" class="tip">暂无可选择的报告公司，请联系管理员检查公司登记和报告权限。</p>
        <p v-else-if="!subjectsLoading && !ready" class="tip">请选择本次报告所属公司；公司列表受现有报告权限控制。</p>
      </el-form-item>
      <el-form-item label="报告来源">
        <el-radio-group v-model="form.periodMode">
          <el-radio value="CALCULATION">选择核算结果</el-radio>
          <el-radio value="MANUAL">创建空白报告</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="withCalculation" label="筛选日期">
        <el-date-picker v-model="filterRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="筛选开始日期" end-placeholder="筛选结束日期" clearable />
        <p class="tip">可留空查询全部成功任务。筛选只用于查找，报告使用选中任务的完整周期。</p>
      </el-form-item>
      <el-form-item v-else label="报告期间">
        <el-date-picker v-model="manualRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" />
      </el-form-item>
      <el-form-item v-if="withCalculation" label="核算任务">
        <el-button :loading="calcsLoading" :disabled="!ready" @click="loadCalcs">查询成功任务</el-button>
        <el-table :data="calcs" row-key="id" :current-row-key="form.calculationTemplateId" highlight-current-row style="margin-top:8px" @current-change="row => form.calculationTemplateId = row && row.id">
          <el-table-column prop="id" label="任务ID" width="90" />
          <el-table-column prop="templateId" label="模板ID" width="90" />
          <el-table-column prop="templateName" label="模板名称" min-width="180" show-overflow-tooltip />
          <el-table-column label="核算周期" min-width="210">
            <template #default="scope">{{ formatDate(scope.row.cycleStart) }} - {{ formatDate(scope.row.cycleEnd) }}</template>
          </el-table-column>
          <el-table-column prop="finishedAt" label="完成时间" width="180" />
          <el-table-column label="状态" width="90">
            <template #default="scope">{{ scope.row.status === 2 ? '成功' : '未完成' }}</template>
          </el-table-column>
          <el-table-column prop="totalEmission" label="总量" />
          <el-table-column prop="warning" label="提示" />
        </el-table>
        <el-alert
          v-if="calcsQueried && (calcsError || calcs.length === 0)"
          :type="calcsError ? 'error' : 'warning'"
          :closable="false"
          show-icon
          style="margin-top:8px"
          :title="calcsError || '没有找到所选公司的成功任务，请核对筛选条件和核算任务公司归属。'"
        />
        <p class="tip">仅有一条成功任务时自动选中；多条时请选择本次采用的任务。报告期间与选中任务一致。</p>
      </el-form-item>
      <el-form-item v-if="periodStart && periodEnd" label="实际期间">
        {{ periodStart }} 至 {{ periodEnd }}（{{ periodKind }}）
      </el-form-item>
      <el-form-item label="报告名称">
        <el-input :model-value="reportTitle" readonly type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" placeholder="选择核算任务，或设置空白报告期间后自动生成" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" :disabled="!canSubmit" @click="submit(withCalculation)">{{ withCalculation ? '创建并带入' : '创建空白报告' }}</el-button>
        <el-button @click="$router.back()">返回</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>
<script>
import { createTask, listCalculations, listReportSubjects, prefillPreview, prefillCommit } from '@/api/carbon/report'
import { classifyReportPeriod } from '@/utils/reportPeriod'
export default {
  name: 'CarbonReportCreate',
  data() {
    return {
      saving: false,
      creationKey: '',
      calcs: [],
      calcsQueried: false,
      calcsError: '',
      calcsLoading: false,
      calcsRequestId: 0,
      subjects: [], subjectsLoading: false, subjectsError: '', subjectsRequestId: 0,
      filterRange: [],
      manualRange: [(new Date().getFullYear() - 1) + '-01-01', (new Date().getFullYear() - 1) + '-12-31'],
      form: { deptId: null, periodMode: 'CALCULATION', calculationTemplateId: null }
    }
  },
  watch: {
    'form.deptId': 'resetCalculations',
    'form.periodMode': 'resetCalculations',
    filterRange: 'resetCalculations',
    reportTitle() { this.creationKey = 'report-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2) }
  },
  beforeUnmount() {
    this.calcsRequestId++
    this.subjectsRequestId++
  },
  created() { this.loadSubjects() },
  computed: {
    withCalculation() { return this.form.periodMode === 'CALCULATION' },
    selected() { return this.calcs.find(item => item.id === this.form.calculationTemplateId) },
    periodStart() { return this.withCalculation ? this.formatDate(this.selected && this.selected.cycleStart) : (this.manualRange || [])[0] },
    periodEnd() { return this.withCalculation ? this.formatDate(this.selected && this.selected.cycleEnd) : (this.manualRange || [])[1] },
    periodKind() { return classifyReportPeriod(this.periodStart, this.periodEnd) },
    reportTitle() {
      const company = this.subjects.find(item => item.deptId === this.form.deptId)
      const name = this.withCalculation ? this.selected && this.selected.templateName : company && company.deptName
      return name && this.periodStart && this.periodEnd ? name + '（' + this.periodStart + '至' + this.periodEnd + '）碳排放报告' : ''
    },
    canSubmit() { return this.ready && !this.calcsLoading && !!this.reportTitle && this.periodStart <= this.periodEnd && (!this.withCalculation || !!this.selected) },
    ready() {
      return !this.subjectsLoading && !this.subjectsError && this.subjects.some(item => item.deptId === this.form.deptId && item.configured)
    }
  },
  methods: {
    subjectLabel(item) {
      return item.deptName + (item.configured ? '' : '（未配置报告数据来源）')
    },
    loadSubjects() {
      const requestId = ++this.subjectsRequestId
      this.subjectsLoading = true
      this.subjectsError = ''
      this.resetCalculations()
      return listReportSubjects().then(res => {
        if (requestId !== this.subjectsRequestId) return
        this.subjects = Array.isArray(res.data) ? res.data : []
        const valid = this.subjects.filter(item => item.configured)
        if (!valid.some(item => item.deptId === this.form.deptId)) this.form.deptId = valid.length === 1 ? valid[0].deptId : null
      }).catch(() => {
        if (requestId === this.subjectsRequestId) this.subjectsError = '报告公司加载失败，请刷新页面重试'
      }).finally(() => { if (requestId === this.subjectsRequestId) this.subjectsLoading = false })
    },
    periodRange() {
      return this.filterRange && this.filterRange.length === 2
        ? { periodStart: this.filterRange[0], periodEnd: this.filterRange[1] } : {}
    },
    resetCalculations() {
      this.calcsRequestId++
      this.form.calculationTemplateId = null
      this.calcs = []
      this.calcsQueried = false
      this.calcsError = ''
      this.calcsLoading = false
    },
    loadCalcs() {
      this.resetCalculations()
      if (!this.ready) return Promise.resolve()
      const requestId = this.calcsRequestId
      this.calcsLoading = true
      return listCalculations({ ...this.periodRange(), deptId: this.form.deptId, periodMode: 'CALCULATION' }).then(res => {
        if (requestId !== this.calcsRequestId) return
        this.calcsQueried = true
        this.calcs = Array.isArray(res.data) ? res.data : []
        if (this.calcs.length === 1) this.form.calculationTemplateId = this.calcs[0].id
      }).catch(error => {
        if (requestId !== this.calcsRequestId) return
        this.calcsQueried = true
        const response = error && error.response
        const data = response && response.data
        this.calcsError = (data && (data.msg || data.message)) || '成功任务查询失败，请检查报告服务和数据库连接。'
      }).finally(() => {
        if (requestId === this.calcsRequestId) this.calcsLoading = false
      })
    },
    formatDate(value) {
      if (!value) return ''
      return String(value).slice(0, 10)
    },
    submit(withCalculation = true) {
      if (!this.canSubmit || this.saving) return Promise.resolve()
      if (withCalculation && !this.calcs.some(item => item.id === this.form.calculationTemplateId)) {
        this.$message.warning('请先查询并选择当前公司的成功任务')
        return Promise.resolve()
      }
      this.saving = true
      const body = { ...this.form, requestKey: this.creationKey, periodStart: this.periodStart, periodEnd: this.periodEnd, deferPrefill: true, calculationTemplateId: withCalculation ? this.form.calculationTemplateId : null }
      return createTask(body).then(async res => {
        const id = res.data.id
        try {
          if (withCalculation && !res.data.creationReused && Number(res.data.version) <= 1) {
            const response = await prefillPreview(id, {})
            const preview = response.data || {}
            if (!preview.lineCount) this.$message.warning('没有可带入数据，已保留空白草稿，请核对来源')
            else {
              const gaps = preview.gaps || []
              if (gaps.length || preview.partialPeriod) await this.$confirm(
                '可带入' + preview.lineCount + '条；实际核算期间：' + preview.cycleStart + '至' + preview.cycleEnd + '。' +
                (preview.partialPeriod ? '与报告期间不同，不自动截取或分摊。' : '') + gaps.join('；') + '。确认带入后，未解决问题仍会阻止正式生成。',
                '核对来源和缺项', { type: 'warning', confirmButtonText: '确认带入可用明细', cancelButtonText: '保留草稿，稍后处理' })
              await prefillCommit(id, { calculationTemplateId: body.calculationTemplateId, version: preview.reportVersion, previewHash: preview.previewHash, acceptPartial: true })
            }
          }
        } catch (error) {
          if (error !== 'cancel' && error !== 'close') this.$message.warning('带入未完成，草稿已保留，可在活动数据中重新预览')
        } finally { this.$router.push('/carbon/report/edit/' + id) }
      }).catch(() => {}).finally(() => { this.saving = false })
    }
  }
}
</script>
<style scoped>
.tip { color: #888; font-size: 12px; }
</style>
