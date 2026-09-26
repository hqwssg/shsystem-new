<template>
  <span class="excel-import-box">
    <el-button size="mini" @click="downloadTemplate">下载模板</el-button>
    <el-button size="mini" type="primary" plain @click="open">导入 Excel</el-button>
    <el-dialog :title="title" :visible.sync="visible" width="420px" append-to-body @close="close">
      <el-radio-group v-model="mode" size="small" style="margin-bottom:12px">
        <el-radio-button label="append">追加</el-radio-button>
        <el-radio-button label="overwrite">覆盖</el-radio-button>
      </el-radio-group>
      <p class="hint">{{ hint }}</p>
      <input ref="file" type="file" accept=".xlsx,.xls" @change="onPicked">
      <span v-if="fileName" class="file-name">{{ fileName }}</span>
      <div slot="footer" class="dialog-footer">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="busy" :disabled="!file" @click="submit">确定导入</el-button>
      </div>
    </el-dialog>
  </span>
</template>
<script>
import { saveAs } from 'file-saver'
import { blobValidate } from '@/utils/ruoyi'
import { downloadExcelTemplate, importExcel } from '@/api/carbon/report'

export default {
  name: 'ExcelImportBox',
  props: {
    draft: { type: Object, required: true },
    type: { type: String, required: true },
    title: { type: String, default: '导入 Excel' },
    hint: { type: String, default: '追加保留已有行；覆盖替换本表（热力只覆盖面积/系数，不改 GJ）。' },
    filename: { type: String, default: 'template.xlsx' }
  },
  data() {
    return { visible: false, mode: 'append', file: null, fileName: '', busy: false }
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
      this.file = null
      this.fileName = ''
      this.busy = false
    },
    onPicked(event) {
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
      this.busy = true
      importExcel(task.id, this.type, this.file, this.mode, task.version).then(() => {
        this.$message.success(this.mode === 'overwrite' ? '已覆盖导入' : '已追加导入')
        this.visible = false
        this.$emit('imported')
      }).finally(() => {
        this.busy = false
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
