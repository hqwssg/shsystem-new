<template>
  <div class="review-step">
    <el-alert v-if="isRange" title="本报告按实际核算期间统计，不自动进行年度同比或月度环比。" type="info" :closable="false" style="margin-bottom:16px" />
    <template v-if="!isRange">
    <h4>{{ isMonthly ? '同比与环比' : '上年对比' }}</h4>
    <el-alert
      :title="periodContract ? '只使用完整对比期间且口径一致的数据。有一条合格结果时自动带入；多条请选定。已保存的基准保持冻结，也可明确选择手工填报或不比较。' : isMonthly
        ? '同比为去年同月、环比为上月。有对应月份核算时会自动带入；没有可手填。不填也可以生成，第6章缺哪组就空哪组。'
        : '有上年核算或上年报告快照时会自动带入。本地没有上年数据时可手填；不填也可以生成，第6章同比会空。'"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom:8px"
    />
    <div v-if="periodContract" v-loading="comparisonLoading" style="margin-bottom:16px">
      <div v-for="slot in comparisonSlots" :key="slot" style="margin-bottom:8px">
        <span>{{ slot === 'mom' ? '环比基准' : '同比基准' }}：</span>
        <el-select v-model="comparisonChoice[slot]" style="width:480px;max-width:100%" @change="comparisonChanged(slot)">
          <el-option label="不比较 / 暂无可比数据" value="NONE" />
          <el-option label="手工填报（该对比期间）" value="MANUAL" />
          <el-option v-if="savedBaseline(slot) && savedBaseline(slot).mode === 'TASK' && !optionsFor(slot).some(item => String(item.taskId) === String(savedBaseline(slot).taskId))" :value="String(savedBaseline(slot).taskId)" :label="'已冻结：核算任务' + savedBaseline(slot).taskId" />
          <el-option v-for="item in optionsFor(slot)" :key="item.taskId" :value="String(item.taskId)" :label="'任务' + item.taskId + ' / ' + item.templateName + ' / ' + (item.finishedAt || '')" />
        </el-select>
        <p class="tip" v-if="comparisonOptions[slot]">对比期间：{{ comparisonOptions[slot].start }} 至 {{ comparisonOptions[slot].end }}</p>
      </div>
    </div>
    <el-form v-if="!isMonthly" label-width="160px" size="small" class="prior-form">
      <el-form-item label="上年总量 tCO2">
        <el-input v-model="prior.total_emissions_tco2" :readonly="isTaskBaseline('yoy')" @input="comparisonDirty = true; validationOk = false" />
      </el-form-item>
      <el-form-item label="上年燃料 tCO2">
        <el-input v-model="prior.fuel_combustion_tco2" :readonly="isTaskBaseline('yoy')" @input="comparisonDirty = true; validationOk = false" />
      </el-form-item>
      <el-form-item label="上年电力 tCO2">
        <el-input v-model="prior.electricity_emissions_tco2" :readonly="isTaskBaseline('yoy')" @input="comparisonDirty = true; validationOk = false" />
      </el-form-item>
      <el-form-item label="上年热力 tCO2">
        <el-input v-model="prior.heat_emissions_tco2" :readonly="isTaskBaseline('yoy')" @input="comparisonDirty = true; validationOk = false" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" size="small" @click="savePrior">保存上年对比</el-button>
      </el-form-item>
    </el-form>
    <div v-else class="month-compare">
      <el-form label-width="168px" size="small" class="prior-form">
        <h5>同比（去年同月{{ yoyLabel }}）</h5>
        <el-form-item label="同期总量 tCO2">
          <el-input v-model="yoy.total_emissions_tco2" :readonly="isTaskBaseline('yoy')" @input="comparisonDirty = true; validationOk = false" />
        </el-form-item>
        <el-form-item label="同期燃料 tCO2">
          <el-input v-model="yoy.fuel_combustion_tco2" :readonly="isTaskBaseline('yoy')" @input="comparisonDirty = true; validationOk = false" />
        </el-form-item>
        <el-form-item label="同期电力 tCO2">
          <el-input v-model="yoy.electricity_emissions_tco2" :readonly="isTaskBaseline('yoy')" @input="comparisonDirty = true; validationOk = false" />
        </el-form-item>
        <el-form-item label="同期热力 tCO2">
          <el-input v-model="yoy.heat_emissions_tco2" :readonly="isTaskBaseline('yoy')" @input="comparisonDirty = true; validationOk = false" />
        </el-form-item>
      </el-form>
      <el-form label-width="168px" size="small" class="prior-form">
        <h5>环比（上月{{ momLabel }}）</h5>
        <el-form-item label="上月总量 tCO2">
          <el-input v-model="mom.total_emissions_tco2" :readonly="isTaskBaseline('mom')" @input="comparisonDirty = true; validationOk = false" />
        </el-form-item>
        <el-form-item label="上月燃料 tCO2">
          <el-input v-model="mom.fuel_combustion_tco2" :readonly="isTaskBaseline('mom')" @input="comparisonDirty = true; validationOk = false" />
        </el-form-item>
        <el-form-item label="上月电力 tCO2">
          <el-input v-model="mom.electricity_emissions_tco2" :readonly="isTaskBaseline('mom')" @input="comparisonDirty = true; validationOk = false" />
        </el-form-item>
        <el-form-item label="上月热力 tCO2">
          <el-input v-model="mom.heat_emissions_tco2" :readonly="isTaskBaseline('mom')" @input="comparisonDirty = true; validationOk = false" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="small" @click="savePrior">保存同比环比</el-button>
        </el-form-item>
      </el-form>
    </div>
    </template>
    <el-button type="primary" :disabled="busy || (aiEnabled && llmConfigLoading)" @click="validate">开始校验</el-button>
    <el-switch v-model="aiEnabled" :disabled="busy" active-text="启用 AI" style="margin-left:16px" @change="onAiEnabledChange" />
    <el-card v-if="aiEnabled" v-loading="llmConfigLoading" shadow="never" class="llm-config">
      <p class="llm-tip">启用 AI 后，开始校验会实际请求所选模型；校验失败时不能用 AI 生成。API Key 留空时使用系统默认密钥，填写后仅用于本次报告，不保存到报告草稿或任务记录。</p>
      <el-form label-width="110px" size="small">
        <el-form-item label="服务地址">
          <el-input v-model.trim="llmForm.baseUrl" placeholder="例如：https://api.example.com/v1" @input="validationOk = false" />
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model.trim="llmForm.model" placeholder="例如：deepseek-chat" @input="validationOk = false" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="llmForm.apiKey" autocomplete="off"
            placeholder="留空使用服务端默认密钥，或输入本次密钥"
            @input="validationOk = false" />
        </el-form-item>
        <el-form-item v-if="llmSettings.isAdmin">
          <el-button :disabled="busy || llmConfigLoading" @click="saveLlmDefault">设为全局默认</el-button>
          <span class="llm-tip">管理员可更新全局默认；密钥加密保存，留空会保留原默认密钥。</span>
        </el-form-item>
      </el-form>
    </el-card>
    <div style="margin-top:16px">
      <el-button :disabled="!canGenerateWord" @click="generate('docx')">生成 Word</el-button>
      <el-button :disabled="!canGeneratePdf" @click="generate('pdf')">生成 PDF</el-button>
    </div>
    <el-alert
      v-if="job && job.status === 'succeeded' && !busy"
      title="已有生成产物，可直接下载。修改填报内容后需重新生成才会更新文件。"
      type="success"
      :closable="false"
      show-icon
      style="margin-top:12px"
    />
    <el-alert
      v-if="aiFallback"
      title="AI 调用未成功，已按模板生成。"
      type="warning"
      :closable="false"
      show-icon
      style="margin-top:12px"
    />
    <el-table v-if="issues.length" :data="issues" size="small" style="margin-top:16px">
      <el-table-column prop="severity" label="级别" width="90" />
      <el-table-column prop="message" label="问题" />
    </el-table>
    <div v-if="job && busy" class="gen-progress">
      <el-progress :percentage="progress" :status="progressStatus" :stroke-width="16" />
      <p>{{ stageText }}</p>
    </div>
    <div v-if="job && job.status === 'failed'" class="gen-progress">
      <p>生成失败：{{ job.errorMessage || '请查看服务日志' }}</p>
    </div>
    <el-button v-if="job && job.docxFileId" link @click="download(job.docxFileId, artifactName('docx'))">下载 Word</el-button>
    <el-button v-if="job && job.pdfFileId" link @click="download(job.pdfFileId, artifactName('pdf'))">下载 PDF</el-button>
  </div>
</template>
<script>
import { saveAs } from 'file-saver'
import { validateTask, getFactorPlan, createGenerationJob, getLatestGenerationJob, getGenerationJob, saveSection, downloadReportArtifact, listComparisonCandidates, getReportLlmConfig, saveReportLlmConfigDefault } from '@/api/carbon/report'
import { reportPeriod, reportArtifactName } from '@/utils/reportPeriod'

function emptyPeriod() {
  return {
    report_year: null,
    report_month: null,
    total_emissions_tco2: '',
    fuel_combustion_tco2: '',
    electricity_emissions_tco2: '',
    heat_emissions_tco2: ''
  }
}

function previousMonth(year, month) {
  if (!year || !month) return { year: null, month: null }
  if (Number(month) <= 1) return { year: Number(year) - 1, month: 12 }
  return { year: Number(year), month: Number(month) - 1 }
}

export default {
  name: 'ReviewStep',
  props: { draft: { type: Object, required: true } },
  data() {
    return {
      aiEnabled: false,
      llmConfigLoading: false,
      llmSettingsLoaded: false,
      llmSettings: { baseUrl: '', model: '', apiKeyConfigured: false, isAdmin: false },
      llmForm: { baseUrl: '', model: '', apiKey: '' },
      job: null,
      issues: [],
      validationOk: false,
      pdfReady: true,
      timer: null,
      comparisonOptions: {}, comparisonLoading: false, comparisonDirty: false, comparisonError: false,
      comparisonChoice: { yoy: 'NONE', mom: 'NONE' }, comparisonTouched: { yoy: false, mom: false },
      prior: emptyPeriod(),
      yoy: emptyPeriod(),
      mom: emptyPeriod()
    }
  },
  computed: {
    periodContract() { return reportPeriod(this.draft.task) },
    isRange() { return !!this.periodContract && this.draft.task.periodType === 'RANGE' },
    comparisonSlots() { return this.isMonthly ? ['yoy', 'mom'] : ['yoy'] },
    isMonthly() {
      return String((this.draft.task && this.draft.task.periodType) || '').toUpperCase() === 'MONTH'
    },
    yoyLabel() {
      const y = this.yoy.report_year
      const m = this.yoy.report_month
      return y && m ? ' ' + y + '年' + m + '月' : ''
    },
    momLabel() {
      const y = this.mom.report_year
      const m = this.mom.report_month
      return y && m ? ' ' + y + '年' + m + '月' : ''
    },
    busy() {
      return this.job && ['queued', 'processing'].includes(this.job.status)
    },
    canGenerateWord() {
      return this.validationOk && !this.busy && !this.comparisonLoading
    },
    canGeneratePdf() {
      return this.validationOk && this.pdfReady && !this.busy && !this.comparisonLoading
    },
    progress() {
      return Math.min(100, Math.max(0, Number(this.job && this.job.progress) || 0))
    },
    progressStatus() {
      if (!this.job) return undefined
      if (this.job.status === 'succeeded') return 'success'
      if (this.job.status === 'failed') return 'exception'
      return undefined
    },
    aiFallback() {
      if (!this.job || this.busy || this.job.status !== 'succeeded') return false
      const enabled = this.job.aiEnabled === true || this.job.aiEnabled === 1 || this.job.aiEnabled === '1'
      return enabled && Number(this.job.llmCallCount) < 0
    },
    stageText() {
      if (!this.job) return ''
      if (this.job.status === 'failed') return '生成失败'
      if (this.job.status === 'succeeded') return '生成完成'
      const p = this.progress
      if (this.job.status === 'queued' || p < 10) return '排队中'
      if (p < 40) return '正在准备数据'
      if (p < 70) return this.aiEnabled ? '正在调用 AI 撰写章节' : '正在生成 Word'
      if (p < 90) return '正在排版 Word'
      if (p < 100) return '正在转换 PDF'
      return '生成完成'
    }
  },
  created() {
    this.hydratePrior()
    if (this.periodContract && !this.isRange) this.loadComparisons()
    this.restoreLatest()
  },
  beforeUnmount() {
    if (this.timer) clearInterval(this.timer)
    this.llmForm.apiKey = ''
  },
  methods: {
    artifactName(extension) { return reportArtifactName(this.draft.task, extension) },
    onAiEnabledChange(enabled) {
      this.validationOk = false
      if (enabled && !this.llmSettingsLoaded) this.loadLlmSettings()
    },
    loadLlmSettings() {
      this.llmConfigLoading = true
      return getReportLlmConfig().then(res => {
        this.llmSettings = res.data || this.llmSettings
        this.llmForm.baseUrl = this.llmSettings.baseUrl || ''
        this.llmForm.model = this.llmSettings.model || ''
        this.llmForm.apiKey = this.llmSettings.apiKey || ''
        this.llmSettingsLoaded = true
      }).catch(() => {
        this.$message.error('AI 默认配置读取失败；启用 AI 前请重试')
      }).finally(() => { this.llmConfigLoading = false })
    },
    llmConfigPayload() {
      return { baseUrl: this.llmForm.baseUrl, model: this.llmForm.model, apiKey: this.llmForm.apiKey }
    },
    saveLlmDefault() {
      saveReportLlmConfigDefault(this.llmConfigPayload()).then(res => {
        this.llmSettings = res.data || this.llmSettings
        this.llmSettingsLoaded = true
        this.llmForm.baseUrl = this.llmSettings.baseUrl || ''
        this.llmForm.model = this.llmSettings.model || ''
        this.llmForm.apiKey = this.llmSettings.apiKey || ''
        this.validationOk = false
        this.$message.success('已更新全局 AI 默认配置')
      })
    },
    baselineValues(slot) { return this.isMonthly ? this[slot] : this.prior },
    savedBaseline(slot) {
      const prior = this.parse(this.draft.task.priorYearJson)
      const value = this.isMonthly ? prior[slot] : prior
      return value && value._comparison
    },
    optionsFor(slot) { return (this.comparisonOptions[slot] && this.comparisonOptions[slot].candidates) || [] },
    isTaskBaseline(slot) { return !!this.periodContract && this.comparisonChoice[slot] !== 'MANUAL' },
    loadComparisons() {
      this.comparisonLoading = true
      this.comparisonError = false
      return listComparisonCandidates(this.draft.task.id).then(res => {
        this.comparisonOptions = res.data || {}
        this.comparisonSlots.forEach(slot => {
          const saved = this.savedBaseline(slot)
          if (saved) this.comparisonChoice[slot] = saved.mode === 'TASK' ? String(saved.taskId) : 'MANUAL'
          else if (this.optionsFor(slot).length === 1) {
            this.comparisonChoice[slot] = String(this.optionsFor(slot)[0].taskId)
            this.comparisonChanged(slot)
          }
        })
      }).catch(() => { this.comparisonError = true; this.$message.error('对比候选加载失败，请重进本步骤后重试；已有对比数据已保留') }).finally(() => { this.comparisonLoading = false })
    },
    comparisonChanged(slot) {
      this.comparisonDirty = true; this.comparisonTouched[slot] = true; this.validationOk = false
      const option = this.optionsFor(slot).find(item => String(item.taskId) === this.comparisonChoice[slot])
      if (option) this.fillPeriod(this.baselineValues(slot), option.values)
      else if (this.comparisonChoice[slot] === 'NONE') this.fillPeriod(this.baselineValues(slot), {})
    },
    comparisonPayload(slot) {
      const choice = this.comparisonChoice[slot]
      if (choice === 'NONE') return { mode: 'NONE' }
      if (choice === 'MANUAL') return { ...this.baselineValues(slot), mode: 'MANUAL' }
      if (!this.comparisonTouched[slot] && this.savedBaseline(slot)) return { mode: 'KEEP' }
      const option = this.optionsFor(slot).find(item => String(item.taskId) === choice)
      return { mode: 'TASK', taskId: Number(choice), selectionHash: option && option.selectionHash }
    },
    parse(json) {
      if (!json) return {}
      if (typeof json === 'object') return json
      try { return JSON.parse(json) } catch (e) { return {} }
    },
    restoreLatest() {
      const local = this.draft && this.draft.latestJob
      if (local && (local.docxFileId || local.pdfFileId)) {
        this.job = local
      }
      getLatestGenerationJob(this.draft.task.id).then(res => {
        if (res.data && (res.data.docxFileId || res.data.pdfFileId)) {
          this.job = res.data
        }
      })
    },
    fillPeriod(target, src, fallbackYear, fallbackMonth) {
      const data = src || {}
      target.report_year = data.report_year || fallbackYear || ''
      target.report_month = data.report_month || fallbackMonth || ''
      target.total_emissions_tco2 = data.total_emissions_tco2 == null ? '' : data.total_emissions_tco2
      target.fuel_combustion_tco2 = data.fuel_combustion_tco2 == null ? '' : data.fuel_combustion_tco2
      target.electricity_emissions_tco2 = data.electricity_emissions_tco2 == null ? '' : data.electricity_emissions_tco2
      target.heat_emissions_tco2 = data.heat_emissions_tco2 == null ? '' : data.heat_emissions_tco2
    },
    hydratePrior() {
      const task = this.draft.task || {}
      const data = this.parse(task.priorYearJson)
      if (this.isMonthly) {
        const prev = previousMonth(task.reportYear, task.reportMonth)
        this.fillPeriod(this.yoy, data.yoy, task.reportYear ? task.reportYear - 1 : '', task.reportMonth)
        this.fillPeriod(this.mom, data.mom, prev.year, prev.month)
        return
      }
      this.fillPeriod(this.prior, data, task.reportYear ? task.reportYear - 1 : '', null)
    },
    savePrior() {
      if (this.comparisonLoading || this.comparisonError) return Promise.reject(new Error('对比候选尚未就绪'))
      const data = this.periodContract ? Object.fromEntries(this.comparisonSlots.map(slot => [slot, this.comparisonPayload(slot)])) : this.isMonthly ? { yoy: this.yoy, mom: this.mom } : this.prior
      return saveSection(this.draft.task.id, 'prior_year', {
        version: this.draft.task.version,
        data
      }).then(() => {
        this.comparisonDirty = false
        this.comparisonTouched = { yoy: false, mom: false }
        this.$message.success(this.isMonthly ? '已保存同比环比' : '已保存上年对比')
        this.$emit('saved')
      })
    },
    validate() {
      if (this.aiEnabled && !this.llmSettingsLoaded && !this.llmConfigLoading) return this.loadLlmSettings()
      if (this.aiEnabled && this.llmConfigLoading) { this.$message.warning('AI 默认配置仍在加载'); return Promise.resolve() }
      if (this.comparisonLoading || this.comparisonError) { this.$message.warning('请等待对比候选加载完成；加载失败时请重进本步骤'); return Promise.resolve() }
      const save = this.periodContract && !this.isRange && this.comparisonDirty ? this.savePrior() : Promise.resolve()
      return save.then(() => validateTask(this.draft.task.id, {
        aiEnabled: this.aiEnabled,
        llmConfig: this.aiEnabled ? this.llmConfigPayload() : undefined
      })).then(res => {
        const data = res.data || {}
        const must = data.mustFix || []
        const confirm = data.shouldConfirm || []
        this.issues = must.map(message => ({ severity: '必须修复', message }))
          .concat(confirm.map(message => ({ severity: '需要确认', message })))
        this.validationOk = !!data.ok
        this.pdfReady = data.pdfReady !== false
        if (data.ok) this.$message.success(confirm.length ? '校验通过，请查看需要确认的项' : '校验通过')
        else this.$message.warning(this.aiEnabled && data.llmReady === false ? 'AI 连通性校验失败，修正配置或关闭 AI 后重新校验' : '还有必须修复的问题，暂不能生成')
      })
    },
    generate(kind) {
      getFactorPlan(this.draft.task.id).then(res => {
        const plan = res.data || {}
        const missing = plan.missing || []
        if (!missing.length) {
          this.startGenerate(kind, false)
          return
        }
        const reason = plan.reason || '现用核算模板缺少因子'
        this.$confirm(
          reason + '：' + missing.join('、') + '。是否使用系统默认因子继续生成？',
          '缺少模板因子',
          { type: 'warning', confirmButtonText: '使用默认因子', cancelButtonText: '取消' }
        ).then(() => {
          this.startGenerate(kind, true)
        }).catch(() => {})
      })
    },
    startGenerate(kind, useDefaultFactors) {
      createGenerationJob(this.draft.task.id, {
        outputKind: kind,
        aiEnabled: this.aiEnabled,
        useDefaultFactors,
        llmConfig: this.aiEnabled ? this.llmConfigPayload() : undefined
      }).then(res => {
        this.job = res.data
        this.poll()
      })
    },
    poll() {
      if (this.timer) clearInterval(this.timer)
      this.timer = setInterval(() => {
        if (!this.job) return
        getGenerationJob(this.draft.task.id, this.job.id).then(res => {
          this.job = res.data
          if (this.job && ['succeeded', 'failed'].includes(this.job.status)) {
            clearInterval(this.timer)
          }
        })
      }, 1500)
    },
    download(id, filename) {
      downloadReportArtifact(id).then(blob => {
        if (!blob || (blob.type && blob.type.indexOf('json') !== -1)) {
          this.$message.error('下载失败')
          return
        }
        saveAs(blob, filename || '报告.docx')
      }).catch(() => {
        this.$message.error('下载失败')
      })
    }
  }
}
</script>
<style scoped>
.review-step { margin-top: 24px; }
.prior-form { max-width: 480px; margin-bottom: 16px; }
.month-compare { display: flex; flex-wrap: wrap; gap: 8px 32px; }
.llm-config { max-width: 680px; margin: 16px 0; }
.llm-config .el-form-item { margin-bottom: 12px; }
.llm-tip { color: #909399; font-size: 12px; line-height: 1.6; }
h4 { margin: 0 0 8px; }
h5 { margin: 0 0 8px; font-size: 13px; font-weight: 600; }
.gen-progress { margin-top: 20px; max-width: 480px; }
</style>
