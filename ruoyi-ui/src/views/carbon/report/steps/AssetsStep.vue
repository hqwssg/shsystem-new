<template>
  <div class="assets-step">
    <el-alert
      title="用能设备默认来自企业档案；报告配图来自本公司档案，未确认的图片留空，可换成本报告的图。本页只改这一份报告，不会回写档案。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom:16px"
    />
    <h4>报告配图</h4>
    <el-alert
      title="封面 logo、组织机构图、机关所在地默认带入。换图只影响这一份报告。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom:8px"
    />
    <div class="image-slots">
      <div v-for="slot in imageSlots" :key="slot.role" class="image-card">
        <div class="image-title">{{ slot.label }}</div>
        <div class="image-preview">
          <img v-if="previews[slot.role]" :src="previews[slot.role]" :alt="slot.label" />
          <span v-else>{{ previewStatus(slot.role) }}</span>
        </div>
        <div class="image-meta">{{ customLabel(slot.role) }}</div>
        <div class="image-actions">
          <el-button size="small" type="primary" @click="pickImage(slot.role)">更换</el-button>
          <el-button size="small" :disabled="!isCustom(slot.role)" @click="resetImage(slot.role)">恢复默认</el-button>
        </div>
      </div>
    </div>
    <input ref="imageFile" type="file" accept="image/png,image/jpeg" style="display:none" @change="onImagePicked" />
    <h4>计量器具</h4>
    <el-table v-if="meters.length" :data="meters" size="small">
      <el-table-column prop="kind" label="类别" width="120" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="energy" label="能源种类" width="140" />
      <el-table-column prop="model" label="型号" width="120" />
      <el-table-column prop="sourceTable" label="来源表" min-width="220" />
    </el-table>
    <el-empty v-else description="当前报告还没有带入的计量表" />
    <h4>第7章监测设备</h4>
    <el-alert
      title="精度、量程和检定周期请按实际资料填写；未确认时留空。"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom:8px"
    />
    <el-alert v-if="monitoringImportNote" :title="monitoringImportNote" type="info" :closable="false" show-icon style="margin-bottom:8px" />
    <el-table :data="monitoring" size="small" max-height="520">
      <el-table-column type="index" label="行" width="45" />
      <el-table-column label="名称" min-width="140">
        <template #default="scope">
          <el-input v-model="scope.row.name" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="型号" width="120">
        <template #default="scope">
          <el-input v-model="scope.row.model" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="精度" width="100">
        <template #default="scope">
          <el-input v-model="scope.row.accuracy" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="量程" width="120">
        <template #default="scope">
          <el-input v-model="scope.row.measurementRange" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="安装位置" min-width="120">
        <template #default="scope">
          <el-input v-model="scope.row.location" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="检定周期" width="120">
        <template #default="scope">
          <el-input v-model="scope.row.calibrationFrequency" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="核对提示" min-width="220">
        <template #default="scope">
          <span :class="monitoringChecks[scope.$index].errors.length ? 'monitor-error' : 'monitor-warning'">{{ monitoringChecks[scope.$index].messages.join('；') }}</span>
        </template>
      </el-table-column>
      <el-table-column label="" width="70">
        <template #default="scope">
          <el-button link size="small" @click="monitoring.splice(scope.$index, 1)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-button size="small" style="margin-top:8px" @click="addMonitor">新增监测行</el-button>
    <excel-import-box
      :draft="draft"
      type="monitoring"
      title="导入监测设备"
      filename="监测设备.xlsx"
      hint="先读入页面供修改，不会立即保存。追加保留当前行并逐行追加；覆盖替换当前监测表。同名和重复行均保留。"
      @preview="previewMonitoring"
    />
    <h4>用能设备</h4>
    <el-alert title="档案默认设备可能来自历史报告，仅作参考。请核对本报告期的设备、数量和型号；原文未提供的数量保留空白。" type="info" :closable="false" style="margin-bottom:8px" />
    <el-alert v-if="equipmentImportNote" :title="equipmentImportNote" type="info" :closable="false" style="margin-bottom:8px" />
    <el-table :data="equipment" size="small" max-height="520">
      <el-table-column type="index" label="行" width="45" />
      <el-table-column label="名称" min-width="140">
        <template #default="scope">
          <el-input v-model="scope.row.name" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="类别" width="120">
        <template #default="scope">
          <el-input v-model="scope.row.category" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="数量" width="90">
        <template #default="scope">
          <el-input v-model="scope.row.quantity" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="单位" width="70">
        <template #default="scope">
          <el-input v-model="scope.row.unit" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="型号" width="120">
        <template #default="scope">
          <el-input v-model="scope.row.model" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="能源种类" width="100">
        <template #default="scope">
          <el-input v-model="scope.row.energyType" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="备注" min-width="160">
        <template #default="scope">
          <el-input v-model="scope.row.remark" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="核对提示" min-width="220">
        <template #default="scope"><span :class="equipmentChecks[scope.$index].errors.length ? 'monitor-error' : 'monitor-warning'">{{ equipmentChecks[scope.$index].messages.join('；') }}</span></template>
      </el-table-column>
      <el-table-column label="" width="70">
        <template #default="scope">
          <el-button link size="small" @click="equipment.splice(scope.$index, 1)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-button size="small" style="margin-top:8px" @click="addRow">新增一行</el-button>
    <el-button type="primary" size="small" style="margin-top:8px;margin-left:8px" @click="save">保存设备与监测</el-button>
    <excel-import-box
      :draft="draft"
      type="equipment"
      title="导入用能设备"
      filename="用能设备.xlsx"
      :current-rows="equipment"
      hint="先读入页面，不立即保存。追加保留当前全部行；覆盖替换用能设备列表。同名设备和重复行均保留。"
      @preview="previewEquipment"
    />
  </div>
</template>
<script>
import { saveSection, getDeptProfile, uploadReportImage, resetReportImage, fetchReportImageBlob } from '@/api/carbon/report'
import ExcelImportBox from './ExcelImportBox'
import { monitoringWarnings, mergeMonitoringRows } from './monitoringImport'
import { reportRowChecks } from './reportImport'

const KNOWN_MODELS = {
  '肃宁天然气计量表': 'LWQ-50',
  '肃宁柴油计量表': 'LC-40',
  '肃宁外购电表': 'DTZ341',
  '肃宁外购热表': 'RLB-80'
}

const IMAGE_SLOTS = [
  { role: 'cover_logo', label: '封面 Logo' },
  { role: 'org_chart', label: '组织机构图' },
  { role: 'office_location', label: '机关所在地' }
]

export default {
  name: 'AssetsStep',
  components: { ExcelImportBox },
  props: { draft: { type: Object, required: true } },
  data() {
    return { equipment: [], monitoring: [], monitoringImportNote: '', equipmentImportNote: '', previews: {}, imageState: {}, pendingRole: '', imageSlots: IMAGE_SLOTS }
  },
  computed: {
    equipmentChecks() { return reportRowChecks(this.equipment, 'equipment') },
    monitoringChecks() {
      return monitoringWarnings(this.monitoring)
    },
    meters() {
      const seen = {}
      const rows = []
      const push = (key, row) => {
        if (seen[key]) return
        seen[key] = true
        rows.push(row)
      }
      ;(this.draft.fuels || []).forEach(item => {
        const name = item.facility || item.sourceName || ''
        push('fuel:' + name + ':' + (item.fuelType || ''), {
          kind: '化石燃料',
          name: name || '未命名燃料计量表',
          energy: this.fuelLabel(item.fuelType),
          model: KNOWN_MODELS[name] || '',
          sourceTable: 'emission_fossil_fuel_meter_info'
        })
      })
      ;(this.draft.electricity || []).forEach(item => {
        const name = item.sourceName || item.facility || ''
        push('el:' + name, {
          kind: '外购电力',
          name: name || '未命名电表',
          energy: '电力',
          model: KNOWN_MODELS[name] || '',
          sourceTable: 'emission_meter_info'
        })
      })
      ;(this.draft.heat || []).forEach(item => {
        const name = item.site || item.sourceName || item.facility || ''
        push('heat:' + name, {
          kind: '外购热力',
          name: name || '未命名热表',
          energy: '热力',
          model: KNOWN_MODELS[name] || '',
          sourceTable: 'emission_purchased_heat_meter_info'
        })
      })
      return rows
    }
  },
  created() {
    this.hydrate()
    this.loadPreviews()
  },
  beforeUnmount() {
    Object.keys(this.previews).forEach(role => {
      if (this.previews[role]) URL.revokeObjectURL(this.previews[role])
    })
  },
  watch: {
    'draft.images': {
      handler() {
        this.loadPreviews()
      }
    }
  },
  methods: {
    customFile(role) {
      const images = (this.draft && this.draft.images) || []
      return images.find(item => item && item.role === role && item.id) || null
    },
    isCustom(role) {
      return !!this.customFile(role)
    },
    customLabel(role) {
      return this.isCustom(role) ? '本报告已替换' : '使用默认图'
    },
    revokePreview(role) {
      if (this.previews[role]) {
        URL.revokeObjectURL(this.previews[role])
        (this.previews)[role] = ''
      }
    },
    previewStatus(role) {
      if (this.imageState[role] === 'missing') {
        return this.isCustom(role) ? '图片不存在' : '未配置默认图'
      }
      return '加载中…'
    },
    previewUrl(role) {
      const file = this.customFile(role)
      if (file && file.id) {
        return '/carbon/report/artifacts/' + file.id + '/download'
      }
      return '/carbon/report/default-images/' + role + '?deptId=' + this.draft.task.deptId
    },
    loadPreviews() {
      IMAGE_SLOTS.forEach(slot => {
        (this.imageState)[slot.role] = 'loading'
        fetchReportImageBlob(this.previewUrl(slot.role)).then(blob => {
          if (!blob || blob.size === 0 || (blob.type && blob.type.indexOf('json') !== -1)) {
            this.revokePreview(slot.role)
            (this.imageState)[slot.role] = 'missing'
            return
          }
          this.revokePreview(slot.role)
          (this.previews)[slot.role] = URL.createObjectURL(blob)
          (this.imageState)[slot.role] = 'ready'
        }).catch(() => {
          this.revokePreview(slot.role)
          (this.imageState)[slot.role] = 'missing'
        })
      })
    },
    pickImage(role) {
      this.pendingRole = role
      this.$refs.imageFile.value = ''
      this.$refs.imageFile.click()
    },
    onImagePicked(event) {
      const file = event.target.files && event.target.files[0]
      const role = this.pendingRole
      this.pendingRole = ''
      event.target.value = ''
      if (!file || !role) return
      const name = (file.name || '').toLowerCase()
      if (!name.endsWith('.png') && !name.endsWith('.jpg') && !name.endsWith('.jpeg')) {
        this.$message.error('只支持 PNG 或 JPEG 图片')
        return
      }
      uploadReportImage(this.draft.task.id, role, file).then(() => {
        this.$message.success('已更换')
        this.$emit('saved')
      })
    },
    resetImage(role) {
      resetReportImage(this.draft.task.id, role).then(() => {
        this.$message.success('已恢复默认')
        this.$emit('saved')
      })
    },
    emptyRow() {
      return { name: '', category: '', quantity: '', unit: '', model: '', energyType: '', remark: '' }
    },
    emptyMonitor() {
      return {
        name: '',
        model: '',
        accuracy: '',
        measurementRange: '',
        location: '',
        calibrationFrequency: '',
        sourceTable: '',
        sourceId: ''
      }
    },
    normalize(row) {
      return {
        name: row.name || '',
        category: row.category || '',
        quantity: row.quantity == null ? '' : row.quantity,
        unit: row.unit || '',
        model: row.model || '',
        energyType: row.energyType || row.energy_type || '',
        remark: row.remark || ''
      }
    },
    normalizeMonitor(row) {
      return {
        name: row.name || '',
        model: row.model || '',
        accuracy: row.accuracy == null ? '' : String(row.accuracy),
        measurementRange: row.measurementRange || row.measurement_range || '',
        location: row.location || '',
        calibrationFrequency: row.calibrationFrequency || row.calibration_frequency || '',
        sourceTable: row.sourceTable || row.source_table || '',
        sourceId: row.sourceId || row.source_id || ''
      }
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
    suggestedMonitoring() {
      return this.meters.map(meter => ({
        name: meter.name,
        model: meter.model || '',
        accuracy: '',
        measurementRange: '',
        location: '',
        calibrationFrequency: '',
        sourceTable: meter.sourceTable || '',
        sourceId: ''
      }))
    },
    hydrate() {
      const savedEq = this.draft.equipment || []
      if (savedEq.length) {
        this.equipment = savedEq.map(row => this.normalize(row))
      } else {
        const task = this.draft.task || {}
        if (task.deptId) {
          getDeptProfile(task.deptId).then(res => {
            if (this.equipment.length || this.equipmentImportNote) return
            const profile = res.data || {}
            this.equipment = this.parseList(profile.defaultEquipmentJson).map(row => this.normalize(row))
          }).catch(() => {})
        } else {
          this.equipment = []
        }
      }
      const savedMon = this.draft.monitoring || []
      if (savedMon.length) {
        this.monitoring = savedMon.map(row => this.normalizeMonitor(row))
      } else {
        this.monitoring = this.suggestedMonitoring()
      }
    },
    addRow() {
      this.equipment.push(this.emptyRow())
    },
    addMonitor() {
      this.monitoring.push(this.emptyMonitor())
    },
    previewEquipment(result) {
      this.equipment = result.rows
      this.equipmentImportNote = '已读入' + result.importedCount + '行，尚未保存；同名和重复行均保留，请核对后保存。'
    },
    previewMonitoring(result) {
      this.monitoring = mergeMonitoringRows(this.monitoring, result.rows, result.mode)
      this.monitoringImportNote = '已读入' + result.rows.length + '行，尚未保存；请核对后点击“保存设备与监测”，离开页面前请先保存。'
        + (result.mergedContinuationRows ? '已合并' + result.mergedContinuationRows + '行合并单元格续写内容。' : '')
    },
    save() {
      const invalidEquipment = this.equipmentChecks.findIndex(check => check.errors.length)
      if (invalidEquipment !== -1) {
        this.$message.error('用能设备第' + (invalidEquipment + 1) + '行：' + this.equipmentChecks[invalidEquipment].errors.join('；'))
        return
      }
      const invalid = this.monitoringChecks.findIndex(check => check.errors.length)
      if (invalid !== -1) {
        this.$message.error('监测设备第' + (invalid + 1) + '行：' + this.monitoringChecks[invalid].errors.join('；'))
        return
      }
      saveSection(this.draft.task.id, 'assets', {
        version: this.draft.task.version,
        data: { equipment: this.equipment, monitoring: this.monitoring }
      }).then(() => {
        this.monitoringImportNote = ''
        this.equipmentImportNote = ''
        this.$message.success('已保存')
        this.$emit('saved')
      })
    },
    fuelLabel(type) {
      if (type === 'natural_gas') return '天然气'
      if (type === 'gasoline') return '汽油'
      if (type === 'diesel') return '柴油'
      return type || ''
    }
  }
}
</script>
<style scoped>
.assets-step { margin-top: 24px; max-width: 1100px; }
.monitor-warning { color: #b88230; }
.monitor-error { color: #f56c6c; }
h4 { margin: 16px 0 8px; }
.image-slots { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.image-card { width: 240px; border: 1px solid #ebeef5; border-radius: 4px; padding: 12px; background: #fff; }
.image-title { font-weight: 600; margin-bottom: 8px; }
.image-preview { height: 140px; display: flex; align-items: center; justify-content: center; background: #f5f7fa; overflow: hidden; }
.image-preview img { max-width: 100%; max-height: 140px; object-fit: contain; }
.image-meta { color: #909399; font-size: 12px; margin: 8px 0; }
.image-actions { display: flex; gap: 8px; }
</style>
