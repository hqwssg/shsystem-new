<template>
  <div class="app-container">
    <div class="run-actions">
      <el-button :icon="$icon('el-icon-back')" size="small" @click="$router.push('/carbon/energy')">返回重空协同</el-button>
      <el-button v-if="!terminal" type="warning" size="small" v-hasPermi="['carbon:energy:cancel']" @click="cancel">取消</el-button>
      <el-button type="danger" size="small" v-hasPermi="['carbon:energy:remove']" @click="remove">删除</el-button>
      <el-button size="small" :loading="loading" @click="reload(false)">刷新</el-button>
    </div>
    <el-alert v-if="holdReason" title="滚动结果不可下发" type="warning" :description="holdReason" show-icon />
    <el-alert v-if="run.runType !== 'storage_planning' && decisionAlert" :title="decisionAlert.title" :type="decisionAlert.type" :description="decisionAlert.description" show-icon />
    <el-alert v-if="simulationOnly" title="阶段仿真结果" description="本次结果用于方案分析，不能作为正式工程结论或现场下发依据。" type="info" :closable="false" show-icon style="margin:12px 0" />
    <el-alert v-if="comparisonUnavailable" title="节能改善未评价" :description="comparisonScope.comparison_note || '基线或候选未满足对比条件，原始能耗保留供诊断。'" type="warning" :closable="false" show-icon />
    <div v-if="headwayPreflight && headwayPreflight.blocking_pair_count" style="margin:18px 0">
      <h4>始发间隔预检查</h4>
      <p>要求间隔 {{ headwayPreflight.minimum_gap_s }} 秒，允许调整最多增加 {{ headwayPreflight.max_departure_separation_increase_s }} 秒；仍有 {{ headwayPreflight.blocking_pair_count }} 对车次无法满足。</p>
      <el-table :data="headwayPreflight.blocking_pairs" size="small" border>
        <el-table-column prop="first_train_id" label="前车" /><el-table-column prop="second_train_id" label="后车" />
        <el-table-column prop="observed_gap_s" label="当前间隔（秒）" /><el-table-column prop="remaining_gap_shortfall_s" label="调整后仍缺（秒）" />
      </el-table>
    </div>

    <div class="progress-card" :class="{ 'is-active': !terminal }">
      <el-steps :active="activeStep" finish-status="success" :process-status="stepProcessStatus" align-center>
        <el-step title="已提交" />
        <el-step title="排队" />
        <el-step title="计算中" />
        <el-step :title="terminalTitle" />
      </el-steps>
      <el-progress :percentage="progressPercent" :status="progressStatus" :stroke-width="16" />
      <p class="progress-text">{{ progressText }}</p>
    </div>

    <StoragePlanningResults v-if="run.status === 'succeeded' && run.runType === 'storage_planning'" :key="run.runId" :run-id="run.runId" />
    <div v-if="run.status === 'succeeded' && run.runType !== 'storage_planning'" class="kpi-row">
      <div v-for="card in kpiCards" :key="card.label" class="kpi-card">
        <div class="kpi-label">{{ card.label }}</div>
        <div class="kpi-value">{{ card.value }}</div>
      </div>
    </div>

    <div v-if="run.status === 'succeeded' && previewImages.length" class="preview-section">
      <h4>示意图</h4>
      <div class="figure-grid">
        <figure v-for="item in previewImages" :key="item.url">
          <img :src="item.url" :alt="item.displayName" @click="openFigure(item)">
          <figcaption>{{ item.displayName }}</figcaption>
        </figure>
      </div>
    </div>

    <div v-if="run.status === 'succeeded' && reportHtml" class="preview-section">
      <h4>{{ reportTitle }}</h4>
      <div class="report-body" v-html="reportHtml" />
    </div>

    <div v-for="table in previewTables" :key="table.title" class="preview-section">
      <h4>{{ table.title }}</h4>
      <el-table :data="table.rows" size="small" border>
        <el-table-column v-for="column in table.columns" :key="column.prop" :prop="column.prop" :label="column.label" min-width="110" show-overflow-tooltip />
      </el-table>
      <div v-if="table.truncated" class="empty-hint">仅显示前 {{ table.rows.length }} 行，共 {{ table.total }} 行，完整内容请下载。</div>
    </div>
    <div v-if="run.status === 'succeeded' && previewLoading" class="empty-hint">正在加载预览…</div>

    <h4 v-if="run.status === 'succeeded'">产出文件</h4>
    <el-table v-if="run.status === 'succeeded'" :data="namedArtifacts" size="small">
      <el-table-column label="文件" min-width="280">
        <template #default="scope">
          <div class="file-name">{{ scope.row.displayName }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="displaySize" label="大小" width="120" />
      <el-table-column label="操作" width="290">
        <template #default="scope">
          <el-button link v-hasPermi="['carbon:energy:download']" @click="download(scope.row)">下载</el-button>
          <template v-if="/\.md$/i.test(scope.row.relativePath)">
            <el-button v-for="kind in ['docx', 'pdf']" :key="kind" link v-hasPermi="['carbon:energy:download']" :loading="exporting === scope.row.relativePath + kind" :disabled="!!exporting" @click="exportDocument(scope.row, kind)">{{ kind === 'docx' ? '下载 Word' : '下载 PDF' }}</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>
    <div v-if="run.status === 'succeeded' && !namedArtifacts.length" class="empty-hint">这次任务没有可下载文件。</div>

    <el-dialog v-model:model-value="figureVisible" :title="figureTitle" width="80%" append-to-body>
      <img v-if="figureUrl" :src="figureUrl" class="figure-dialog-img" :alt="figureTitle">
    </el-dialog>
  </div>
</template>
<script>
import { getRun, cancelRun, deleteRun, getSummary, listArtifacts, downloadArtifact, exportReport } from '@/api/carbon/energy'
import { artifactDisplayName, artifactDownloadName, localizeEnergyReportFiles, formatEnergyArtifactSize, sortEnergyArtifacts, previewImageArtifacts, primaryReportArtifact, previewTableArtifacts, previewSummaryArtifact } from '@/utils/energyArtifactNames'
import { blobValidate } from '@/utils/ruoyi'
import { renderSimpleMarkdown, csvToPreviewTable, buildKpiCards, kpiPreviewTable, rollingPreviewTable, jointPreviewTable, parseJsonObject, decisionCopy as describeDecision } from '@/utils/energyPreview'
import { saveAs } from 'file-saver'
import StoragePlanningResults from './StoragePlanningResults.vue'
export default {
  components: { StoragePlanningResults },
  name: 'CarbonEnergyRun',
  data() {
    return {
      loading: false,
      previewLoading: false,
      exporting: '',
      run: {},
      summary: null,
      artifacts: [],
      previewImages: [],
      previewTables: [],
      reportTitle: '',
      reportHtml: '',
      previewExtra: {},
      figureVisible: false,
      figureTitle: '',
      figureUrl: '',
      timer: null,
      tickTimer: null,
      now: Date.now(),
      runningSince: 0
    }
  },
  computed: {
    terminal() {
      return ['succeeded', 'failed', 'cancelled'].indexOf(this.run.status) >= 0
    },
    statusLabel() {
      return {
        pending: '排队等待计算',
        queued: '排队等待计算',
        running: '正在计算',
        succeeded: '计算完成',
        failed: '计算失败',
        cancelled: '已取消'
      }[this.run.status] || '正在提交'
    },
    waitSeconds() {
      const start = this.parseTime(this.run.startedAt) || this.runningSince || this.parseTime(this.run.queuedAt)
      if (!start) {
        return 0
      }
      return Math.max(0, Math.floor((this.now - start) / 1000))
    },
    activeStep() {
      if (this.run.status === 'succeeded' || this.run.status === 'failed' || this.run.status === 'cancelled') {
        return 4
      }
      if (this.run.status === 'running') {
        return 2
      }
      if (this.run.status === 'pending' || this.run.status === 'queued') {
        return 1
      }
      return 0
    },
    stepProcessStatus() {
      if (this.run.status === 'failed' || this.run.status === 'cancelled') {
        return 'error'
      }
      return 'process'
    },
    terminalTitle() {
      if (this.run.status === 'failed') {
        return '失败'
      }
      if (this.run.status === 'cancelled') {
        return '已取消'
      }
      return '完成'
    },
    progressPercent() {
      if (this.run.status === 'succeeded') {
        return 100
      }
      if (this.run.status === 'failed' || this.run.status === 'cancelled') {
        return 100
      }
      if (this.run.status === 'running') {
        return Math.round(18 + 72 * (1 - Math.exp(-this.waitSeconds / 360)))
      }
      if (this.run.status === 'pending' || this.run.status === 'queued') {
        return Math.min(15, 8 + Math.floor(this.waitSeconds / 10))
      }
      return 8
    },
    progressStatus() {
      if (this.run.status === 'succeeded') {
        return 'success'
      }
      if (this.run.status === 'failed' || this.run.status === 'cancelled') {
        return 'exception'
      }
      return undefined
    },
    progressText() {
      const minutes = Math.floor(this.waitSeconds / 60)
      const seconds = this.waitSeconds % 60
      const waited = minutes > 0 ? (minutes + ' 分 ' + seconds + ' 秒') : (seconds + ' 秒')
      if (this.run.status === 'succeeded') {
        return '计算完成，可查看下面的结果。'
      }
      if (this.run.status === 'failed') {
        return '计算失败：' + (this.run.errorMessage || '未返回错误信息')
      }
      if (this.run.status === 'cancelled') {
        return '任务已取消。'
      }
      if (this.run.status === 'running') {
        return this.statusLabel + '，已用时 ' + waited + '。算法还在跑，进度会持续更新，请不要重复提交。'
      }
      return this.statusLabel + '，已等待 ' + waited + '。提交后算法可能需要几分钟，页面会自动刷新。'
    },
    resultDecision() { return this.previewExtra.result && this.previewExtra.result.optimization_decision || this.summary && this.summary.decision || {} },
    decisionAction() { return this.resultDecision.action },
    decisionAlert() {
      const message = describeDecision(this.decisionAction, this.resultDecision.reason)
      if (message && this.simulationOnly && this.decisionAction === 'optimize') return { ...message, title: '仿真中选中优化方案', description: '选中方案仅供本次仿真分析。' }
      return message
    },
    simulationOnly() { const context = this.previewExtra.result && this.previewExtra.result.algorithm_context; return !!context && context.ready_for_conclusions === false },
    comparisonScope() { return this.previewExtra.result && this.previewExtra.result.comparison || {} },
    comparisonUnavailable() { return this.comparisonScope.energy_comparison_eligible === false },
    headwayPreflight() { return this.previewExtra.result && this.previewExtra.result.headway_preflight },
    holdReason() {
      const events = (this.summary && this.summary.rollingEvents) || []
      const withheld = events.find(item => item.commitStatus === 'withheld_infeasible' || item.commit_status === 'withheld_infeasible')
      return withheld ? '本轮滚动结果不可下发，需要人工介入。' : ''
    },
    kpiCards() {
      return buildKpiCards(this.summary, this.run.runType, this.previewExtra)
    },
    namedArtifacts() {
      return sortEnergyArtifacts(this.artifacts).map(item => Object.assign({}, item, {
        displayName: artifactDisplayName(item.relativePath),
        downloadName: artifactDownloadName(item.relativePath),
        displaySize: formatEnergyArtifactSize(item.contentSizeBytes)
      }))
    }
  },
  created() {
    this.reload(true)
    this.tickTimer = setInterval(() => {
      this.now = Date.now()
    }, 1000)
  },
  watch: {
    '$route.params.runId'(value, previous) {
      if (value && value !== previous) {
        this.runningSince = 0
        this.reload(true)
      }
    }
  },
  beforeUnmount() {
    if (this.timer) clearInterval(this.timer)
    if (this.tickTimer) clearInterval(this.tickTimer)
    this.clearPreviewUrls()
  },
  methods: {
    parseTime(value) {
      if (!value) {
        return 0
      }
      if (Array.isArray(value) && value.length >= 3) {
        return Date.UTC(value[0], (value[1] || 1) - 1, value[2] || 1, value[3] || 0, value[4] || 0, value[5] || 0)
      }
      const text = String(value).trim()
      if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(text)) {
        const parsed = Date.parse(text.replace(' ', 'T'))
        return Number.isNaN(parsed) ? 0 : parsed
      }
      const parsed = Date.parse(text.replace(' ', 'T') + 'Z')
      return Number.isNaN(parsed) ? 0 : parsed
    },
    basename(relativePath) {
      const parts = String(relativePath || '').replace(/\\/g, '/').split('/')
      return parts[parts.length - 1] || ''
    },
    clearPreviewUrls() {
      this.previewImages.forEach(item => {
        if (item.url) URL.revokeObjectURL(item.url)
      })
      this.previewImages = []
    },
    structuredTables() {
      const type = this.run.runType
      const tables = []
      if (type === 'dispatch' || type === 'timetable_optimization') {
        const kpiTable = kpiPreviewTable(this.summary && this.summary.kpis)
        if (kpiTable) tables.push(kpiTable)
      }
      if (type === 'rolling_rescheduling') {
        const rollingTable = rollingPreviewTable(this.summary && this.summary.rollingEvents)
        if (rollingTable) tables.push(rollingTable)
      }
      return tables
    },
    skippedTableNames() {
      const skip = []
      const structured = this.structuredTables()
      if (structured.some(item => item.title === '滚动各轮结果')) {
        skip.push('rolling_cycles.csv')
      }
      if (structured.some(item => item.title === '基线与优化指标对比')) {
        skip.push('kpi_comparison.csv', 'kpi_summary.csv')
      }
      return skip
    },
    loadPreviews() {
      this.clearPreviewUrls()
      this.reportTitle = ''
      this.reportHtml = ''
      this.previewExtra = {}
      this.previewTables = this.structuredTables()
      if (this.run.status !== 'succeeded') {
        this.previewLoading = false
        return Promise.resolve()
      }
      const runId = this.run.runId
      const images = previewImageArtifacts(this.artifacts)
      const report = primaryReportArtifact(this.run.runType, this.artifacts)
      const tableFiles = previewTableArtifacts(this.run.runType, this.artifacts, this.skippedTableNames())
      const summaryFile = previewSummaryArtifact(this.run.runType, this.artifacts)
      this.previewLoading = true
      const imageJobs = images.map(item => downloadArtifact(runId, item.relativePath).then(blob => {
        if (!blobValidate(blob)) {
          return null
        }
        return {
          displayName: artifactDisplayName(item.relativePath),
          url: URL.createObjectURL(blob)
        }
      }).catch(() => null))
      const reportJob = report
        ? downloadArtifact(runId, report.relativePath).then(blob => {
          if (!blobValidate(blob)) {
            return null
          }
          return blob.text().then(text => ({
            title: artifactDisplayName(report.relativePath),
            html: renderSimpleMarkdown(localizeEnergyReportFiles(text, this.artifacts))
          }))
        }).catch(() => null)
        : Promise.resolve(null)
      const tableJobs = tableFiles.map(item => downloadArtifact(runId, item.relativePath).then(blob => {
        if (!blobValidate(blob)) {
          return null
        }
        return blob.text().then(text => csvToPreviewTable(text, artifactDisplayName(item.relativePath), this.basename(item.relativePath)))
      }).catch(() => null))
      const summaryJob = summaryFile
        ? downloadArtifact(runId, summaryFile.relativePath).then(blob => {
          // The summary is a JSON artifact, so application/json is expected here.
          return blob.text().then(text => parseJsonObject(text))
        }).catch(() => null)
        : Promise.resolve(null)
      return Promise.all([Promise.all(imageJobs), reportJob, Promise.all(tableJobs), summaryJob]).then(([imageRows, reportBody, csvTables, summaryJson]) => {
        if (this.run.runId !== runId) {
          imageRows.filter(Boolean).forEach(item => URL.revokeObjectURL(item.url))
          return
        }
        this.previewImages = imageRows.filter(Boolean)
        if (reportBody) {
          this.reportTitle = reportBody.title
          this.reportHtml = reportBody.html
        }
        const extra = {}
        if (summaryJson) {
          extra.result = summaryJson
          if (this.run.runType === 'joint_parameter_robustness') {
            extra.joint = summaryJson
          } else if (this.run.runType === 'rolling_rescheduling') {
            extra.benchmark = summaryJson
          } else if (this.run.runType === 'timetable_optimization') {
            extra.optimizer = summaryJson
          }
        }
        this.previewExtra = extra
        const tables = this.structuredTables().concat(csvTables.filter(Boolean))
        const jointTable = jointPreviewTable(extra.joint)
        this.previewTables = jointTable ? [jointTable].concat(tables) : tables
      }).finally(() => {
        if (this.run.runId === runId) {
          this.previewLoading = false
        }
      })
    },
    openFigure(item) {
      this.figureTitle = item.displayName
      this.figureUrl = item.url
      this.figureVisible = true
    },
    reload(showLoading) {
      const runId = this.$route.params.runId
      if (showLoading) this.loading = true
      getRun(runId).then(res => {
        this.run = res.data || {}
        if (this.run.status === 'running' && !this.runningSince) {
          this.runningSince = this.parseTime(this.run.startedAt) || Date.now()
        }
        if (this.run.status === 'succeeded') {
          return Promise.all([
            getSummary(runId),
            listArtifacts(runId)
          ]).then(([summary, artifacts]) => {
            this.summary = summary.data
            this.artifacts = artifacts.data || []
            return this.loadPreviews()
          })
        }
        this.summary = null
        this.artifacts = []
        this.previewTables = []
        this.previewExtra = {}
        this.reportTitle = ''
        this.reportHtml = ''
        this.clearPreviewUrls()
        return null
      }).catch(() => {
        this.$message.error('加载任务失败')
      }).finally(() => {
        this.loading = false
        this.schedulePoll()
      })
    },
    schedulePoll() {
      if (this.timer) clearInterval(this.timer)
      if (this.terminal) return
      this.timer = setInterval(() => this.reload(false), 2000)
    },
    cancel() {
      cancelRun(this.run.runId, { reason: 'cancelled_by_platform' }).then(() => this.reload(false)).catch(() => {
        this.$message.error('取消失败')
      })
    },
    remove() {
      this.$confirm('删除后不可恢复，结果工件也会一并删除。是否继续？', '删除任务', {
        type: 'warning'
      }).then(() => deleteRun(this.run.runId)).then(() => {
        this.$message.success('已删除')
        this.$router.push('/carbon/energy')
      }).catch(err => {
        if (err !== 'cancel' && err !== 'close') {
          this.$message.error('删除失败')
        }
      })
    },
    async exportDocument(row, format) {
      if (this.exporting) return
      this.exporting = row.relativePath + format
      const runId = this.run.runId
      const name = (row.downloadName || artifactDownloadName(row.relativePath)).replace(/\.md$/i, '.' + format)
      try {
        const blob = await exportReport(runId, row.relativePath, format)
        if (!blobValidate(blob)) {
          const error = JSON.parse(await blob.text())
          throw new Error(error.msg || '报告导出失败')
        }
        saveAs(blob, name)
      } catch (error) {
        this.$message.error(error.message || '报告导出失败，请稍后重试')
      } finally {
        this.exporting = ''
      }
    },
    download(row) {
      const artifacts = this.artifacts
      downloadArtifact(this.run.runId, row.relativePath).then(async blob => {
        if (/\.md$/i.test(row.relativePath) && blobValidate(blob)) {
          blob = new Blob([localizeEnergyReportFiles(await blob.text(), artifacts)], { type: 'text/markdown;charset=utf-8' })
        }
        saveAs(blob, row.downloadName || row.relativePath)
      }).catch(() => this.$message.error('下载失败'))
    }
  }
}
</script>
<style scoped>.run-actions {
  margin: 0 0 16px;
}

.file-name {
  font-weight: 600;
}

.empty-hint {
  color: #909399;
  font-size: 12px;
  margin: 8px 0 16px;
}

.progress-card {
  margin: 16px 0 24px;
  padding: 20px 24px 8px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
}

.progress-card .el-progress {
  margin-top: 20px;
}

.progress-card.is-active :deep(.el-progress-bar__inner) {
  background-image: linear-gradient(45deg, rgba(255, 255, 255, 0.28) 25%, transparent 25%, transparent 50%, rgba(255, 255, 255, 0.28) 50%, rgba(255, 255, 255, 0.28) 75%, transparent 75%, transparent);
  background-size: 24px 24px;
  animation: energy-progress-stripe 0.8s linear infinite;
}

@keyframes energy-progress-stripe {
  from {
    background-position: 0 0;
  }
  to {
    background-position: 24px 0;
  }
}
.progress-text {
  margin: 12px 0 8px;
  color: #606266;
  line-height: 1.6;
}

.kpi-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin: 0 0 20px;
}

.kpi-card {
  flex: 1;
  min-width: 140px;
  padding: 12px 16px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
}

.kpi-label {
  color: #909399;
  font-size: 12px;
}

.kpi-value {
  margin-top: 6px;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.preview-section {
  margin: 0 0 24px;
}

.preview-section h4 {
  margin: 0 0 12px;
}

.figure-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}

.figure-grid figure {
  margin: 0;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  overflow: hidden;
}

.figure-grid img {
  display: block;
  width: 100%;
  cursor: zoom-in;
  background: #fafafa;
}

.figure-grid figcaption {
  padding: 8px 12px;
  font-size: 13px;
  color: #606266;
}

.figure-dialog-img {
  display: block;
  max-width: 100%;
  margin: 0 auto;
}

.report-body {
  max-height: 480px;
  overflow: auto;
  padding: 8px 16px 16px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  line-height: 1.65;
  color: #303133;
}

.report-body :deep(h3),
.report-body :deep(h4),
.report-body :deep(h5) {
  margin: 16px 0 8px;
}

.report-body :deep(p),
.report-body :deep(li) {
  margin: 6px 0;
}

.report-body :deep(code) {
  padding: 0 4px;
  background: #f4f4f5;
  border-radius: 2px;
  font-size: 12px;
}

.report-body :deep(.md-table-wrap) {
  overflow-x: auto;
  margin: 8px 0 12px;
}

.report-body :deep(table) {
  border-collapse: collapse;
  min-width: 100%;
  font-size: 12px;
}

.report-body :deep(th),
.report-body :deep(td) {
  border: 1px solid #ebeef5;
  padding: 6px 8px;
  white-space: nowrap;
}

.report-body :deep(th) {
  background: #f5f7fa;
}</style>
