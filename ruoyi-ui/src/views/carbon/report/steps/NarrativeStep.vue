<template>
  <div class="narrative-step">
    <el-alert
      title="默认来自本分公司档案。保存说明只改这一份报告；「写入档案默认」才会改以后新报告的预填。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom:16px"
    />
    <el-tabs v-model="activeTab">
      <el-tab-pane name="natural_gas">
        <template v-slot:label>天然气<span v-if="!hasNaturalGas" class="tab-miss">本报告无此项活动</span></template>
        <el-alert
          v-if="!hasNaturalGas"
          title="本报告活动数据里没有天然气，一般不必填。如档案已有说明，可核对后保留。"
          type="info"
          :closable="false"
          class="tab-empty-alert"
        />
        <el-form label-width="168px" size="small">
          <el-form-item label="用在哪里">
            <el-input type="textarea" :rows="2" v-model="form.natural_gas.usage" placeholder="例如：食堂灶具" />
            <p class="field-hint">写入第 3 章天然气用途</p>
          </el-form-item>
          <el-form-item label="怎么计量">
            <el-input v-model="form.natural_gas.metering_method" placeholder="例如：由流量计连续计量" />
            <p class="field-hint">流量计、台账还是估算</p>
          </el-form-item>
          <el-form-item label="看哪本台账">
            <el-input v-model="form.natural_gas.source_documents_text" placeholder="例如：沿线各站食堂天然气统计表，多个用逗号分隔" />
            <p class="field-hint">原始统计表或台账名称</p>
          </el-form-item>
          <el-form-item label="单位怎么写">
            <el-input v-model="form.natural_gas.unit_note" placeholder="例如：单位为 m3" />
            <p class="field-hint">报告里如何表述消耗量单位</p>
          </el-form-item>
          <el-form-item label="有没有折标况">
            <el-input type="textarea" :rows="2" v-model="form.natural_gas.standard_condition_note" placeholder="例如：未计量温度和压力时，按接近标况、不另做折标计算" />
            <p class="field-hint">未计量温度、压力时如何处理</p>
          </el-form-item>
          <el-form-item v-if="!isRange" :label="isMonthly ? '和去年同月、上月比有无变化' : '和上年比有无变化'">
            <el-input
              v-model="form.natural_gas.change_note"
              :placeholder="isMonthly ? '例如：报告期内天然气消耗较去年同月基本稳定' : '例如：报告期内天然气消耗较上年基本稳定'"
            />
            <p class="field-hint">{{ isMonthly ? '用量同比、环比有无明显变化' : '用量同比有无明显变化' }}</p>
          </el-form-item>
        </el-form>
        <div class="preview-box">
          <div class="preview-title">快照说明预览</div>
          <p>{{ naturalGasPreview }}</p>
        </div>
      </el-tab-pane>
      <el-tab-pane name="liquid_fuel">
        <template v-slot:label>汽柴油<span v-if="!hasLiquidFuel" class="tab-miss">本报告无此项活动</span></template>
        <el-alert
          v-if="!hasLiquidFuel"
          title="本报告活动数据里没有汽油或柴油，一般不必填。如档案已有说明，可核对后保留。"
          type="info"
          :closable="false"
          class="tab-empty-alert"
        />
        <el-form label-width="168px" size="small">
          <el-form-item label="用在哪里">
            <el-input type="textarea" :rows="2" v-model="form.liquid_fuel.usage" placeholder="例如：公务车使用汽油，生产车辆和轨道作业车使用柴油" />
            <p class="field-hint">写入第 3 章汽柴油用途</p>
          </el-form-item>
          <el-form-item label="怎么计量">
            <el-input v-model="form.liquid_fuel.metering_method" placeholder="例如：由加油站或加油车的流量计每次计量" />
            <p class="field-hint">加油记录、流量计还是估算</p>
          </el-form-item>
          <el-form-item label="看哪本台账">
            <el-input v-model="form.liquid_fuel.source_documents_text" placeholder="例如：汽车汽油和柴油消耗统计表，多个用逗号分隔" />
            <p class="field-hint">原始统计表或台账名称</p>
          </el-form-item>
        </el-form>
        <div class="preview-box">
          <div class="preview-title">快照说明预览</div>
          <p>{{ liquidFuelPreview }}</p>
        </div>
      </el-tab-pane>
      <el-tab-pane name="electricity">
        <template v-slot:label>电力<span v-if="!hasElectricity" class="tab-miss">本报告无此项活动</span></template>
        <el-alert
          v-if="!hasElectricity"
          title="本报告活动数据里没有外购电力，一般不必填。如档案已有说明，可核对后保留。"
          type="info"
          :closable="false"
          class="tab-empty-alert"
        />
        <el-form label-width="168px" size="small">
          <el-form-item label="有没有绿电">
            <el-input v-model="form.electricity.non_fossil_power_note" placeholder="例如：报告期内未购入非化石能源电力" />
            <p class="field-hint">绿电、非化石电力有无采购</p>
          </el-form-item>
          <el-form-item label="电从哪来">
            <el-input v-model="form.electricity.grid_source" placeholder="例如：国网冀北电力有限公司" />
            <p class="field-hint">电网或供电单位</p>
          </el-form-item>
          <el-form-item label="看哪本台账">
            <el-input v-model="form.electricity.source_documents_text" placeholder="例如：电费结算单，多个用逗号分隔" />
            <p class="field-hint">电费结算单或电表台账名称</p>
          </el-form-item>
          <el-form-item label="结算口径">
            <el-input type="textarea" :rows="2" v-model="form.electricity.settlement_note" placeholder="例如：按供电公司电费结算单统计净购入电量" />
            <p class="field-hint">电量如何统计、是否净购入</p>
          </el-form-item>
        </el-form>
        <div class="preview-box">
          <div class="preview-title">快照说明预览</div>
          <p>{{ electricityPreview }}</p>
        </div>
      </el-tab-pane>
      <el-tab-pane name="heat">
        <template v-slot:label>热力<span v-if="!hasHeat" class="tab-miss">本报告无此项活动</span></template>
        <el-alert
          v-if="!hasHeat"
          title="本报告活动数据里没有外购热力，一般不必填。如档案已有说明，可核对后保留。"
          type="info"
          :closable="false"
          class="tab-empty-alert"
        />
        <el-form label-width="168px" size="small">
          <el-form-item label="供热协议">
            <el-input v-model="form.heat.contract_note" placeholder="例如：与地方热力公司签订供热协议" />
            <p class="field-hint">是否外购、和谁签协议</p>
          </el-form-item>
          <el-form-item label="怎么缴费">
            <el-input v-model="form.heat.payment_method" placeholder="例如：按供热面积缴费" />
            <p class="field-hint">按面积、热表还是一口价</p>
          </el-form-item>
          <el-form-item label="没有热表时怎么估">
            <el-input v-model="form.heat.estimation_method" placeholder="例如：按供热面积和热耗系数估算" />
            <p class="field-hint">无热表时的估算方法</p>
          </el-form-item>
          <el-form-item label="是否转供他人">
            <el-input v-model="form.heat.no_resale_note" placeholder="例如：外购热力未转供其他单位" />
            <p class="field-hint">有无转供或转售</p>
          </el-form-item>
          <el-form-item label="看哪本台账">
            <el-input v-model="form.heat.source_documents_text" placeholder="例如：供热缴费通知单，多个用逗号分隔" />
            <p class="field-hint">缴费单或热力台账名称</p>
          </el-form-item>
        </el-form>
        <div class="preview-box">
          <div class="preview-title">快照说明预览</div>
          <p>{{ heatPreview }}</p>
        </div>
      </el-tab-pane>
    </el-tabs>
    <el-button type="primary" size="small" @click="save">保存说明</el-button>
    <el-button size="small" style="margin-left:8px" @click="saveAsDefault">写入档案默认</el-button>
  </div>
</template>
<script>
import { saveSection, getDeptProfile, saveDeptActivityProse } from '@/api/carbon/report'

function emptySection() {
  return { usage: '', metering_method: '', source_documents_text: '', unit_note: '', standard_condition_note: '', change_note: '', non_fossil_power_note: '', grid_source: '', settlement_note: '', contract_note: '', payment_method: '', estimation_method: '', no_resale_note: '' }
}

const EMPTY_PREVIEW = '还没有填写，保存后快照里这一段为空'

export default {
  name: 'NarrativeStep',
  props: { draft: { type: Object, required: true } },
  data() {
    return {
      activeTab: 'natural_gas',
      form: {
        natural_gas: emptySection(),
        liquid_fuel: emptySection(),
        electricity: emptySection(),
        heat: emptySection()
      }
    }
  },
  computed: {
    isRange() { return String((this.draft.task && this.draft.task.periodType) || '') === 'RANGE' },
    fuels() {
      return (this.draft && this.draft.fuels) || []
    },
    hasNaturalGas() {
      return this.fuels.some(item => item.fuelType === 'natural_gas')
    },
    hasLiquidFuel() {
      return this.fuels.some(item => item.fuelType === 'gasoline' || item.fuelType === 'diesel')
    },
    hasElectricity() {
      return ((this.draft && this.draft.electricity) || []).length > 0
    },
    hasHeat() {
      return ((this.draft && this.draft.heat) || []).length > 0
    },
    isMonthly() {
      return String((this.draft.task && this.draft.task.periodType) || '').toUpperCase() === 'MONTH'
    },
    naturalGasPreview() {
      const row = this.form.natural_gas
      return this.joinPreview([
        row.usage,
        row.metering_method,
        row.source_documents_text,
        row.unit_note,
        row.standard_condition_note,
        row.change_note
      ])
    },
    liquidFuelPreview() {
      const row = this.form.liquid_fuel
      return this.joinPreview([row.usage, row.metering_method, row.source_documents_text])
    },
    electricityPreview() {
      const row = this.form.electricity
      return this.joinPreview([
        row.non_fossil_power_note,
        row.grid_source,
        row.source_documents_text,
        row.settlement_note
      ])
    },
    heatPreview() {
      const row = this.form.heat
      return this.joinPreview([
        row.contract_note,
        row.payment_method,
        row.estimation_method,
        row.no_resale_note,
        row.source_documents_text
      ])
    }
  },
  created() {
    this.hydrate()
    this.activeTab = this.firstActiveTab()
  },
  methods: {
    firstActiveTab() {
      if (this.hasNaturalGas) return 'natural_gas'
      if (this.hasLiquidFuel) return 'liquid_fuel'
      if (this.hasElectricity) return 'electricity'
      if (this.hasHeat) return 'heat'
      return 'natural_gas'
    },
    joinPreview(parts) {
      const filled = (parts || []).map(item => String(item || '').trim()).filter(Boolean)
      if (!filled.length) return EMPTY_PREVIEW
      return filled.map(item => (/[。；，.!?！？]$/.test(item) ? item : item + '。')).join('')
    },
    parse(json) {
      if (!json) return {}
      if (typeof json === 'object') return json
      try { return JSON.parse(json) } catch (e) { return {} }
    },
    docsText(list) {
      if (Array.isArray(list)) return list.join('，')
      if (typeof list === 'string') return list
      return ''
    },
    docsList(text) {
      return String(text || '').split(/[,，]/).map(s => s.trim()).filter(Boolean)
    },
    applyProse(raw, onlyEmpty) {
      const data = this.parse(raw)
      const assign = (key, fields) => {
        const src = data[key] || {}
        fields.forEach(field => {
          const next = src[field] || ''
          if (onlyEmpty) {
            if (!String(this.form[key][field] || '').trim() && next) {
              this.form[key][field] = next
            }
          } else {
            this.form[key][field] = next
          }
        })
        const docs = this.docsText(src.source_documents)
        if (onlyEmpty) {
          if (!String(this.form[key].source_documents_text || '').trim() && docs) {
            this.form[key].source_documents_text = docs
          }
        } else {
          this.form[key].source_documents_text = docs
        }
      }
      assign('natural_gas', ['usage', 'metering_method', 'unit_note', 'standard_condition_note', 'change_note'])
      assign('liquid_fuel', ['usage', 'metering_method'])
      assign('electricity', ['non_fossil_power_note', 'grid_source', 'settlement_note'])
      assign('heat', ['contract_note', 'payment_method', 'estimation_method', 'no_resale_note'])
    },
    hydrate() {
      this.applyProse(this.draft.task && this.draft.task.activityProseJson, false)
      const deptId = this.draft.task && this.draft.task.deptId
      if (!deptId) return
      getDeptProfile(deptId).then(res => {
        const profile = res.data || {}
        this.applyProse(profile.defaultActivityProseJson, true)
      }).catch(() => {})
    },
    payload() {
      return {
        natural_gas: {
          usage: this.form.natural_gas.usage,
          metering_method: this.form.natural_gas.metering_method,
          unit_note: this.form.natural_gas.unit_note,
          standard_condition_note: this.form.natural_gas.standard_condition_note,
          change_note: this.form.natural_gas.change_note,
          source_documents: this.docsList(this.form.natural_gas.source_documents_text)
        },
        liquid_fuel: {
          usage: this.form.liquid_fuel.usage,
          metering_method: this.form.liquid_fuel.metering_method,
          source_documents: this.docsList(this.form.liquid_fuel.source_documents_text)
        },
        electricity: {
          non_fossil_power_note: this.form.electricity.non_fossil_power_note,
          grid_source: this.form.electricity.grid_source,
          settlement_note: this.form.electricity.settlement_note,
          source_documents: this.docsList(this.form.electricity.source_documents_text)
        },
        heat: {
          contract_note: this.form.heat.contract_note,
          payment_method: this.form.heat.payment_method,
          estimation_method: this.form.heat.estimation_method,
          no_resale_note: this.form.heat.no_resale_note,
          source_documents: this.docsList(this.form.heat.source_documents_text)
        }
      }
    },
    saveReport() {
      return saveSection(this.draft.task.id, 'narrative', {
        version: this.draft.task.version,
        data: this.payload()
      }).then(res => {
        const task = res.data || {}
        if (task.version != null && this.draft.task) {
          this.draft.task.version = task.version
        }
        return res
      })
    },
    save() {
      this.saveReport().then(() => {
        this.$message.success('已保存本报告说明')
        this.$emit('saved')
      })
    },
    saveAsDefault() {
      const deptId = this.draft.task && this.draft.task.deptId
      if (!deptId) {
        this.$message.error('无法写入档案：缺少部门')
        return
      }
      this.$confirm('将覆盖本分公司档案默认，以后新建报告会带上当前说明。确定？', '写入档案默认', {
        type: 'warning',
        confirmButtonText: '写入档案',
        cancelButtonText: '取消'
      }).then(() => {
        return this.saveReport()
      }).then(() => {
        return saveDeptActivityProse(deptId, this.payload())
      }).then(() => {
        this.$message.success('已保存本报告，并写入档案默认')
        this.$emit('saved')
      }).catch(err => {
        if (err === 'cancel' || err === 'close') return
      })
    }
  }
}
</script>
<style scoped>
.narrative-step { margin-top: 24px; max-width: 860px; }
.tab-miss { margin-left: 6px; color: #909399; font-size: 12px; font-weight: 400; }
.tab-empty-alert { margin-bottom: 12px; }
.field-hint { margin: 4px 0 0; color: #909399; font-size: 12px; line-height: 1.4; }
.preview-box {
  margin: 8px 0 16px;
  padding: 12px 14px;
  background: #f5f7fa;
  border-radius: 4px;
  color: #606266;
  font-size: 13px;
  line-height: 1.7;
}
.preview-title { font-weight: 600; color: #303133; margin-bottom: 6px; }
.preview-box p { margin: 0; white-space: pre-wrap; }
</style>
