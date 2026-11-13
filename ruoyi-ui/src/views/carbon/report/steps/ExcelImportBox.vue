<template>
  <span class="excel-import-box">
    <el-button size="small" @click="downloadTemplate">下载模板</el-button>
    <el-button size="small" type="primary" plain @click="open">导入 Excel</el-button>
    <el-dialog :title="title" v-model:model-value="visible" width="420px" append-to-body @close="close">
      <el-radio-group v-model="mode" size="small" style="margin-bottom:12px">
        <el-radio-button value="append">追加</el-radio-button>
        <el-radio-button value="overwrite">覆盖</el-radio-button>
      </el-radio-group>
      <p class="hint">{{ hint }}</p>
      <input ref="file" type="file" accept=".xlsx,.xls" @change="onPicked">
      <span v-if="fileName" class="file-name">{{ fileName }}</span>
      <template #footer><div  class="dialog-footer">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="busy" :disabled="!file" @click="submit">确定导入</el-button>
      </div></template>
    </el-dialog>
  </span>
</template>
<script>
import { saveAs } from 'file-saver'
import { blobValidate } from '@/utils/ruoyi'
import { downloadExcelTemplate } from '@/api/carbon/report'
import { readMonitoringFile } from './monitoringImport'
import { readReportFile, mergeReportRows } from './reportImport'

export default {
  name: 'ExcelImportBox',
  props: {
    draft: { type: Object, required: true },
    type: { type: String, required: true },
    title: { type: String, default: '导入 Excel' },
    hint: { type: String, default: '追加保留已有行；覆盖替换本表（热力只覆盖面积/系数，不改 GJ）。' },
    filename: { type: String, default: 'template.xlsx' },
    currentRows: { type: Array, default: () => [] }
  },
  data() {
    return { visible: false, mode: 'append', file: null, fileName: '', busy: false, previewRequest: 0 }
  },
  methods: {
    open() {
      this.mode = 'append'
      this.file = null
      this.fileName = ''
      this.visible = true
      this.$nextTick(() => {
        if (this.$refs.file) this.$refs.file.value = ''
      })
    },
    close() {
      this.previewRequest++
      this.file = null
      this.fileName = ''
      this.busy = false
    },
    onPicked(event) {
      this.previewRequest++
      this.busy = false
      const picked = event.target.files && event.target.files[0]
      this.file = picked || null
      this.fileName = picked ? picked.name : ''
    },
    downloadTemplate() {
      const id = this.draft.task && this.draft.task.id
      if (!id) return
      downloadExcelTemplate(id, this.type).then(async data => {
        const ok = blobValidate(data)
        if (!ok) {
          this.$message.error('下载模板失败')
          return
        }
        saveAs(new Blob([data]), this.filename)
      })
    },
    submit() {
      const task = this.draft.task || {}
      if (!this.file || !task.id) return
      const request = ++this.previewRequest
      const mode = this.mode
      this.busy = true
      const read = this.type === 'monitoring' ? readMonitoringFile(this.file) : readReportFile(this.file, this.type)
      read.then(result => {
        if (request !== this.previewRequest) return
        const rows = this.type === 'monitoring' ? result.rows : mergeReportRows(this.currentRows, result.rows, this.type, mode)
        this.$emit('preview', { ...result, rows, mode })
        this.$message.success('已读入页面，尚未保存，可修改或删除后保存')
        this.visible = false
      }).catch(error => {
        if (request === this.previewRequest) this.$message.error(error.message || '读取Excel失败')
      }).finally(() => {
        if (request === this.previewRequest) this.busy = false
      })
    }
  }
}
</script>
<style scoped>
.excel-import-box { margin-left: 8px; }
.hint { color: #909399; font-size: 12px; margin: 0 0 12px; line-height: 1.5; }
.file-name { margin-left: 8px; color: #606266; font-size: 12px; }
</style>
