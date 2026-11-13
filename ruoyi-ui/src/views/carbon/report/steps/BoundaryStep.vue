<template>
  <div class="boundary-step">
    <el-alert
      title="组织边界、核算方法和排除说明默认来自企业档案，本页只改这一份报告，不会回写档案。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom:16px"
    />
    <el-form label-width="140px" size="small">
      <el-form-item label="组织边界说明">
        <el-input type="textarea" :rows="6" v-model="form.boundary_description" placeholder="由企业档案带入，可按本年差异修改" />
      </el-form-item>
      <el-form-item label="核算方法">
        <el-input type="textarea" :rows="3" v-model="form.accounting_method" placeholder="由企业档案带入" />
      </el-form-item>
      <el-form-item label="不纳入核算">
        <el-input type="textarea" :rows="3" v-model="form.fuel_boundary_exclusion" placeholder="例如机车归属机辆分公司，不计入本报告" />
      </el-form-item>
      <el-form-item label="排放源类别">
        <el-checkbox-group v-model="form.emission_sources">
          <el-checkbox value="化石燃料燃烧">化石燃料燃烧</el-checkbox>
          <el-checkbox value="净购入电力">净购入电力</el-checkbox>
          <el-checkbox value="净购入热力">净购入热力</el-checkbox>
        </el-checkbox-group>
      </el-form-item>
      <el-form-item label="核算来源待核对项" v-if="gaps.length">
        <el-alert
          title="归属或格式有问题的行会跳过；已带入的异常行仍须核对，正式生成前会拦截"
          type="warning"
          :closable="false"
          show-icon
        >
          <div v-for="(gap, index) in gaps" :key="index">{{ gap }}</div>
        </el-alert>
      </el-form-item>
      <el-form-item label="排放源明细">
        <el-button size="small" @click="suggestRows">按活动数据生成建议行</el-button>
        <el-table :data="form.emission_source_rows" size="small" style="margin-top:8px">
          <el-table-column label="类别" width="160">
            <template #default="scope">
              <el-select v-model="scope.row.category" size="small" placeholder="类别">
                <el-option label="化石燃料燃烧" value="化石燃料燃烧" />
                <el-option label="净购入电力" value="净购入电力" />
                <el-option label="净购入热力" value="净购入热力" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="设施">
            <template #default="scope">
              <el-input v-model="scope.row.facility" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="位置">
            <template #default="scope">
              <el-input v-model="scope.row.location" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="排放源">
            <template #default="scope">
              <el-input v-model="scope.row.source" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="" width="70">
            <template #default="scope">
              <el-button link size="small" @click="form.emission_source_rows.splice(scope.$index, 1)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button size="small" style="margin-top:8px" @click="addRow">新增一行</el-button>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="save">保存边界</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>
<script>
import { saveSection, getDeptProfile, prefillPreview } from '@/api/carbon/report'

const DEFAULT_METHOD = '依据陆上交通运输企业温室气体排放核算方法与报告指南进行核算。'

export default {
  name: 'BoundaryStep',
  props: { draft: { type: Object, required: true } },
  data() {
    return {
      form: {
        boundary_description: '',
        accounting_method: '',
        fuel_boundary_exclusion: '',
        emission_sources: [],
        emission_source_rows: []
      },
      gaps: []
    }
  },
  created() {
    this.hydrate()
    this.loadGaps()
  },
  methods: {
    loadGaps() {
      const id = this.draft.task && this.draft.task.id
      if (!id) return
      const frozen = this.parse(this.draft.task.metadataJson)._source_snapshot || {}
      this.gaps = Array.isArray(frozen.gaps) ? frozen.gaps.slice() : this.gaps
      return prefillPreview(id, {}).then(res => {
        const data = res.data || {}
        this.gaps = Array.isArray(data.gaps) ? data.gaps : []
      }).catch(() => {
        const message = '核算来源预览失败，已保留已保存的核对项；请重试后确认'
        if (!this.gaps.includes(message)) this.gaps.push(message)
      })
    },
    parse(json) {
      if (!json) return {}
      if (typeof json === 'object') return json
      try { return JSON.parse(json) } catch (e) { return {} }
    },
    hydrate() {
      const task = this.draft.task || {}
      const boundary = this.parse(task.organizationBoundaryJson)
      const notes = this.parse(task.emissionBoundaryNotesJson)
      this.form.boundary_description = boundary.boundary_description || ''
      this.form.accounting_method = boundary.accounting_method || ''
      this.form.fuel_boundary_exclusion = notes.fuel_boundary_exclusion || ''
      this.form.emission_sources = Array.isArray(boundary.emission_sources)
        ? boundary.emission_sources.slice()
        : this.suggestedSources()
      this.form.emission_source_rows = Array.isArray(boundary.emission_source_rows)
        ? boundary.emission_source_rows.map(row => Object.assign({
          category: '', facility: '', location: '', source: ''
        }, row))
        : []
      const needProfile = !this.form.boundary_description || !this.form.accounting_method || !this.form.fuel_boundary_exclusion
      if (!needProfile || !task.deptId) {
        if (!this.form.accounting_method) {
          this.form.accounting_method = DEFAULT_METHOD
        }
        return
      }
      getDeptProfile(task.deptId).then(res => {
        const profile = res.data || {}
        if (!this.form.boundary_description) {
          this.form.boundary_description = profile.defaultOrgBoundary || ''
        }
        if (!this.form.accounting_method) {
          this.form.accounting_method = profile.defaultAccountingMethod || DEFAULT_METHOD
        }
        if (!this.form.fuel_boundary_exclusion) {
          this.form.fuel_boundary_exclusion = profile.defaultExclusionNote || ''
        }
      }).catch(() => {
        if (!this.form.accounting_method) {
          this.form.accounting_method = DEFAULT_METHOD
        }
      })
    },
    suggestedSources() {
      const sources = []
      if ((this.draft.fuels || []).length) sources.push('化石燃料燃烧')
      if ((this.draft.electricity || []).length) sources.push('净购入电力')
      if ((this.draft.heat || []).length) sources.push('净购入热力')
      return sources
    },
    fuelSource(type) {
      if (type === 'natural_gas') return '天然气'
      if (type === 'gasoline') return '汽油'
      if (type === 'diesel') return '柴油'
      return type || ''
    },
    suggestRows() {
      const rows = []
      ;(this.draft.fuels || []).forEach(row => {
        rows.push({
          category: '化石燃料燃烧',
          facility: row.facility || row.sourceName || '',
          location: row.facility || '运营边界内',
          source: this.fuelSource(row.fuelType)
        })
      })
      ;(this.draft.electricity || []).forEach(row => {
        rows.push({
          category: '净购入电力',
          facility: row.sourceName || '外购电力计量点',
          location: '运营边界内',
          source: '外购电力'
        })
      })
      ;(this.draft.heat || []).forEach(row => {
        rows.push({
          category: '净购入热力',
          facility: row.site || row.facility || row.sourceName || '供暖站点',
          location: row.site || '运营边界内',
          source: '外购热力'
        })
      })
      if (!rows.length) {
        this.$message.warning('暂无可用于生成建议行的活动数据，已有排放源明细已保留')
        return
      }
      this.form.emission_source_rows = rows
      this.form.emission_sources = this.suggestedSources()
    },
    addRow() {
      this.form.emission_source_rows.push({ category: '', facility: '', location: '', source: '' })
    },
    save() {
      saveSection(this.draft.task.id, 'boundary', {
        version: this.draft.task.version,
        data: {
          boundary_description: this.form.boundary_description,
          accounting_method: this.form.accounting_method,
          fuel_boundary_exclusion: this.form.fuel_boundary_exclusion,
          emission_sources: this.form.emission_sources,
          emission_source_rows: this.form.emission_source_rows
        }
      }).then(() => {
        this.$message.success('已保存')
        this.$emit('saved')
      })
    }
  }
}
</script>
<style scoped>
.boundary-step { margin-top: 24px; max-width: 960px; }
</style>
