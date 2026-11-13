<template>
  <div class="activity-step">
    <el-button v-if="draft.task.calculationTemplateId" :loading="importing" @click="importSource" style="margin-bottom:12px">预览并重新带入核算数据</el-button>
    <el-alert v-if="preview && preview.cycleStart" :title="'实际核算期间：' + preview.cycleStart + ' 至 ' + preview.cycleEnd + '；可带入 ' + preview.lineCount + ' 条' + (preview.partialPeriod ? '；与报告期间不一致，不自动截取或分摊' : '')" type="info" :closable="false" style="margin-bottom:12px" />

    <p>燃料/电/热来自成功核算任务，自动字段只读。需要改数时使用「本报告覆盖」，来源原值不会被改写。</p>
    <el-alert v-if="sourceNotice" :title="sourceNotice" type="info" :closable="false" style="margin-bottom:12px" />
    <el-alert
      v-if="gaps.length"
      title="核算来源待核对项：被跳过的行和已带入的异常行在此列示"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom:12px"
    >
      <div v-for="(gap, index) in gaps" :key="index">{{ gap }}</div>
    </el-alert>
    <el-table :data="draft.fuels" size="small">
      <el-table-column prop="fuelType" label="燃料" width="120" />
      <el-table-column prop="facility" label="设施" />
      <el-table-column prop="sourceValue" label="来源值" width="100" />
      <el-table-column prop="sourceUnit" label="来源单位" width="100" />
      <el-table-column prop="normalizedValue" label="报告值" width="100" />
      <el-table-column prop="normalizedUnit" label="报告单位" width="100" />
      <el-table-column prop="dataOrigin" label="来源" width="110">
        <template #default="scope">
          <el-tag size="small" :type="scope.row.dataOrigin === 'AUTO' ? 'success' : 'warning'">{{ originLabel(scope.row.dataOrigin) }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
    <h4>外购电力</h4>
    <el-table :data="draft.electricity" size="small">
      <el-table-column prop="sourceName" label="计量点" />
      <el-table-column prop="normalizedValue" label="MWh" width="120" />
      <el-table-column prop="dataOrigin" label="来源" width="110">
        <template #default="scope">
          <el-tag size="small">{{ originLabel(scope.row.dataOrigin) }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
    <h4>外购热力</h4>
    <el-alert
      title="有核算面积（PH_HA，单位 m²）时会带入供暖面积和耗热量系数；核算已是 GJ 时两列为空，可手填。不填则第 3.3 表对应格留空。填写只进报告表，不改核算 GJ。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom:8px"
    />
    <el-alert v-if="heatImportNote" :title="heatImportNote" type="info" :closable="false" style="margin-bottom:8px" />
    <el-table :data="heat" size="small">
      <el-table-column prop="site" label="站点" />
      <el-table-column label="供暖面积 m²" width="150">
        <template #default="scope">
          <el-input v-model="scope.row.heatingAreaM2" size="small" placeholder="可手填" />
        </template>
      </el-table-column>
      <el-table-column label="耗热量系数" width="140">
        <template #default="scope">
          <el-input v-model="scope.row.heatCoefficient" size="small" placeholder="可手填" />
        </template>
      </el-table-column>
      <el-table-column prop="normalizedValue" label="GJ" width="120" />
      <el-table-column prop="dataOrigin" label="来源" width="110">
        <template #default="scope">
          <el-tag size="small">{{ originLabel(scope.row.dataOrigin) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="" width="110"><template #default="scope"><el-button v-if="!scope.row.id" link @click="heat.splice(scope.$index, 1)">移除新增行</el-button></template></el-table-column>
    </el-table>
    <el-button type="primary" size="small" style="margin-top:8px" @click="saveHeat">保存热力面积/系数</el-button>
    <excel-import-box
      :draft="draft"
      type="heat"
      title="导入热力面积/系数"
      filename="热力.xlsx"
      :current-rows="heat"
      hint="先预览后保存。追加逐字段补空；覆盖匹配站点的非空面积/系数，不清空其他值或更改GJ。同名多条无法定位时提示核对。新站点GJ为空。"
      @preview="previewHeat"
    />
    <h4>工作量（选填）</h4><p v-if="reportPeriod(draft.task)">如需计算排放强度，请填写 {{ periodLabel(draft.task) }} 的工作量，与排放量统计期间一致。</p>
    <el-alert
      title="工作量可以不填，仍可生成报告；未填时不补 0，也不计算排放强度。填写时请使用本报告期间的实际数量和单位。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom:8px"
    />
    <el-alert v-if="workloadImportNote" :title="workloadImportNote" type="info" :closable="false" style="margin-bottom:8px" />
    <el-table :data="workload" size="small">
      <el-table-column type="index" label="行" width="45" />
      <el-table-column label="名称" min-width="180">
        <template #default="scope">
          <el-input v-model="scope.row.name" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="数量" width="140">
        <template #default="scope">
          <el-input v-model="scope.row.quantity" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="单位" width="100">
        <template #default="scope">
          <el-input v-model="scope.row.unit" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="核对提示" min-width="200"><template #default="scope">{{ workloadChecks[scope.$index].messages.join('；') }}</template></el-table-column>
      <el-table-column label="" width="70">
        <template #default="scope">
          <el-button link size="small" @click="workload.splice(scope.$index, 1)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-button size="small" style="margin-top:8px" @click="addWorkload">新增一行</el-button>
    <el-button type="primary" size="small" style="margin-top:8px;margin-left:8px" @click="saveWorkload">保存工作量</el-button>
    <excel-import-box
      :draft="draft"
      type="workload"
      title="导入工作量"
      filename="工作量.xlsx"
      :current-rows="workload"
      hint="先预览后保存。追加补同名同单位指标的空数量；不同数量或单位冲突时提示核对，不累加。覆盖替换工作量表。无正数量的Excel行会列出忽略说明。"
      @preview="previewWorkload"
    />
    <p v-if="draft.missingWorkload" class="workload-note">工作量未填不影响报告生成；报告将说明未提供工作量，不计算排放强度。</p>
  </div>
</template>
<script>
import { reportPeriod, reportPeriodLabel } from '@/utils/reportPeriod'
import { saveSection, getDeptProfile, prefillPreview, prefillCommit } from '@/api/carbon/report'
import ExcelImportBox from './ExcelImportBox'
import { reportRowChecks, numberValue } from './reportImport'
export default {
  name: 'ActivityStep',
  components: { ExcelImportBox },
  props: { draft: { type: Object, required: true } },
  data() {
    return { workload: [], heat: [], heatBaseline: '', heatImportNote: '', workloadImportNote: '', gaps: [], sourceNotice: '', preview: null, importing: false }
  },
  computed: {
    workloadChecks() { return reportRowChecks(this.workload, 'workload') }
  },
  watch: {
    'draft.heat'(rows) {
      if (JSON.stringify(this.heat) === this.heatBaseline) this.hydrateHeat(rows)
    }
  },
  created() {
    this.hydrateHeat(this.draft.heat)
    this.hydrateWorkload()
    this.loadGaps()
  },
  methods: {
    hydrateHeat(rows) {
      this.heat = (rows || []).map(row => ({ ...row }))
      this.heatBaseline = JSON.stringify(this.heat)
    },
    previewHeat(result) {
      this.heat = result.rows
      this.heatImportNote = '已读取' + result.importedCount + '行，尚未保存；保留原核算GJ，新站点GJ为空。'
    },
    previewWorkload(result) {
      this.workload = result.rows
      this.workloadImportNote = '已读取' + result.importedCount + '行，尚未保存；同名同单位同数量合并为一个指标，不累加。' + (result.notices || []).join('；')
    },
    reportPeriod,
    periodLabel: reportPeriodLabel,
    loadGaps() {
      const task = this.draft.task || {}
      const id = task.id
      if (!id || !task.calculationTemplateId) return
      let metadata = {}
      try { metadata = typeof task.metadataJson === 'string' ? JSON.parse(task.metadataJson) : (task.metadataJson || {}) } catch (e) { metadata = {} }
      if (!metadata._report_subject) {
        this.sourceNotice = '历史报告按已保存数据展示；如需重新带入，请新建报告并选择已配置的主体和成功任务。'
        return
      }
      prefillPreview(id, {}).then(res => {
        const data = res.data || {}
        this.preview = data
        this.gaps = Array.isArray(data.gaps) ? data.gaps : []
      }).catch(() => {
        this.gaps = []
      })
    },
    async importSource() {
      if (this.importing) return
      if (JSON.stringify(this.heat) !== this.heatBaseline) {
        this.$message.warning('请先保存或撤销热力面积/系数修改，再重新带入核算数据')
        return
      }
      this.importing = true
      try {
        const response = await prefillPreview(this.draft.task.id, {})
        const preview = response.data || {}
        this.preview = preview
        this.gaps = preview.gaps || []
        if (!preview.lineCount) { this.$message.warning('没有可带入数据，已有填报保持不变'); return }
        await this.$confirm('将带入' + preview.lineCount + '条活动数据，替换本报告已有活动行。核算期间：' + preview.cycleStart + '至' + preview.cycleEnd + '。' +
          (preview.partialPeriod ? '期间不一致，不自动截取或分摊。' : '') + this.gaps.join('；'), '核对带入预览', { type: 'warning' })
        await prefillCommit(this.draft.task.id, { calculationTemplateId: this.draft.task.calculationTemplateId, version: preview.reportVersion, previewHash: preview.previewHash, acceptPartial: true })
        this.$message.success('已带入可用明细；待核对项仍需处理')
        this.$emit('saved')
      } catch (error) {
        if (error !== 'cancel' && error !== 'close') this.$message.warning('带入未完成，已有填报保持不变')
      } finally { this.importing = false }
    },
    originLabel(origin) {
      if (origin === 'AUTO') return '自动带入'
      if (origin === 'OVERRIDE') return '本报告覆盖'
      if (origin === 'IMPORT') return '导入'
      return '手工'
    },
    parseList(raw) {
      if (!raw) return []
      if (Array.isArray(raw)) return raw
      if (typeof raw === 'string') {
        try {
          const parsed = JSON.parse(raw)
          return Array.isArray(parsed) ? parsed : []
        } catch (e) {
          return []
        }
      }
      return []
    },
    hydrateWorkload() {
      const saved = this.draft.workload || []
      if (saved.length) {
        this.workload = saved.map(row => ({
          name: row.name || '',
          quantity: row.quantity == null ? '' : row.quantity,
          unit: row.unit || ''
        }))
        return
      }
      const deptId = this.draft.task && this.draft.task.deptId
      if (!deptId) {
        this.workload = []
        return
      }
      getDeptProfile(deptId).then(res => {
        if (this.workload.length || this.workloadImportNote) return
        const profile = res.data || {}
        this.workload = this.parseList(profile.defaultWorkloadJson).map(row => ({
          name: row.name || '',
          quantity: '',
          unit: row.unit || ''
        }))
      }).catch(() => {})
    },
    addWorkload() {
      this.workload.push({ name: '', quantity: '', unit: '' })
    },
    saveWorkload() {
      const invalid = this.workloadChecks.findIndex(check => check.errors.length)
      if (invalid !== -1) {
        this.$message.error('工作量第' + (invalid + 1) + '行：' + this.workloadChecks[invalid].errors.join('；'))
        return
      }
      saveSection(this.draft.task.id, 'workload', {
        version: this.draft.task.version,
        data: { workload: this.workload.map(row => ({ ...row, quantity: numberValue(row.quantity, '数量') })).filter(row => row.name.trim() && Number(row.quantity) > 0) }
      }).then(() => {
        this.workloadImportNote = ''
        this.$message.success('已保存；无正数量的工作量行未写入')
        this.$emit('saved')
      })
    },
    saveHeat() {
      const checks = reportRowChecks(this.heat, 'heat')
      const invalid = checks.findIndex(check => check.errors.length)
      if (invalid !== -1) {
        this.$message.error('热力第' + (invalid + 1) + '行：' + checks[invalid].errors.join('；'))
        return
      }
      const savedHeat = JSON.stringify(this.heat)
      saveSection(this.draft.task.id, 'heat', {
        version: this.draft.task.version,
        data: {
          heat: this.heat.map(row => ({
            id: row.id,
            site: row.site,
            heatingAreaM2: numberValue(row.heatingAreaM2, '供暖面积'),
            heatCoefficient: numberValue(row.heatCoefficient, '耗热量系数')
          }))
        }
      }).then(() => {
        this.heatBaseline = savedHeat
        this.heatImportNote = ''
        this.$message.success('已保存热力面积/系数')
        this.$emit('saved')
      })
    }
  }
}
</script>
<style scoped>
.activity-step { margin-top: 24px; }
h4 { margin: 16px 0 8px; }
.gap { color: #e6a23c; margin-top: 12px; }
.workload-note { color: #606266; margin-top: 12px; }
</style>
