<template>
  <el-dialog title="公司报告数据来源配置" :model-value="visible" width="680px" :close-on-click-modal="false" @close="$emit('update:visible', false)">
    <p>新核算任务按公司归属查询，无需选择主体节点。此处维护表计归属编码；历史节点仅用于兼容尚未确认公司归属的旧任务。已有报告保留原数据来源。</p>
    <el-form label-width="120px" size="small" :disabled="saving">
      <el-form-item label="报告公司">
        <el-select v-model="form.deptId" filterable style="width:100%" @change="selectDepartment">
          <el-option v-for="item in subjects" :key="item.deptId" :value="item.deptId" :label="item.deptName + '（' + item.deptId + '）'" />
        </el-select>
      </el-form-item>
      <el-form-item label="历史节点（选填）">
        <el-select v-model="form.subjectNodeId" clearable filterable :loading="loading" :disabled="loading || failed" style="width:100%">
          <el-option v-for="item in nodes" :key="item.subjectNodeId" :value="item.subjectNodeId" :label="item.subjectName + '（节点' + item.subjectNodeId + '，' + item.templateName + '）'" />
        </el-select>
      </el-form-item>
      <el-form-item label="表计归属编码">
        <el-input v-model.trim="form.energyAllocation" maxlength="64" placeholder="必须与表计的部门归属编码一致" />
        <p>现有分公司编码：肃宁 suring、原平 yuanping、机辆 jilong。不能仅按节点名称推测或更改表计归属。</p>
      </el-form-item>
    </el-form>
    <el-alert v-if="failed" title="主体节点加载失败，请关闭后重试" type="error" :closable="false" />
    <template #footer><span >
      <el-button :disabled="saving" @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="loading || failed || !form.deptId || !form.energyAllocation" @click="save">保存配置</el-button>
    </span></template>
  </el-dialog>
</template>
<script>
import { listReportSubjectNodes, saveReportSubject } from '@/api/carbon/report'
export default {
  props: { visible: Boolean, subjects: { type: Array, default: () => [] } },
  data() {
    return { form: { deptId: null, subjectNodeId: null, energyAllocation: '' }, nodes: [], loading: false, failed: false, saving: false, requestId: 0 }
  },
  watch: {
    visible(value) {
      this.requestId++
      if (value) this.loadNodes()
    }
  },
  beforeUnmount() { this.requestId++ },
  methods: {
    selectDepartment() {
      const item = this.subjects.find(row => row.deptId === this.form.deptId) || {}
      this.form.subjectNodeId = item.subjectNodeId || null
      this.form.energyAllocation = item.energyAllocation || ''
    },
    loadNodes() {
      const id = this.requestId
      this.loading = true
      this.failed = false
      this.nodes = []
      return listReportSubjectNodes().then(res => {
        if (id === this.requestId) this.nodes = res.data || []
      }).catch(() => {
        if (id === this.requestId) this.failed = true
      }).finally(() => { if (id === this.requestId) this.loading = false })
    },
    save() {
      this.saving = true
      return saveReportSubject(this.form.deptId, { subjectNodeId: this.form.subjectNodeId, energyAllocation: this.form.energyAllocation }).then(() => {
        this.$message.success('公司数据来源已保存，已有报告保持原数据来源')
        this.$emit('saved')
        this.$emit('update:visible', false)
      }).catch(() => {}).finally(() => { this.saving = false })
    }
  }
}
</script>
