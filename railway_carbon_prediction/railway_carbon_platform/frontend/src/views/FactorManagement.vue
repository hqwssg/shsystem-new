<template>
  <div class="page">
    <div class="page-card">
      <h2 class="page-title">碳排放因子管理</h2>
      <p class="page-desc">
        维护各品种的排放因子及生效期。因子按版本管理，历史已使用版本不覆盖；修改因子后，后续月度计算会自动使用新版本，并在排放结果中保存因子快照。
      </p>
      <div class="filter-row">
        <el-select v-model="varId" placeholder="全部品种" clearable filterable style="width: 220px" @change="load">
          <el-option v-for="v in vars" :key="v.varId" :label="v.varName" :value="v.varId" />
        </el-select>
        <el-button type="primary" :icon="Plus" @click="openDialog">新增因子版本</el-button>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="page-card">
      <el-table :data="rows" v-loading="loading" border stripe height="460">
        <el-table-column label="品种" min-width="140">
          <template #default="{ row }">{{ row.varName || varName(row.varId) }}</template>
        </el-table-column>
        <el-table-column label="因子值" width="140" align="right">
          <template #default="{ row }">{{ Number(row.factorValue).toFixed(8) }}</template>
        </el-table-column>
        <el-table-column prop="factorUnit" label="单位" width="120" />
        <el-table-column prop="factorVersion" label="版本" min-width="140">
          <template #default="{ row }"><span class="mono">{{ row.factorVersion }}</span></template>
        </el-table-column>
        <el-table-column prop="effectiveFrom" label="生效日期" width="115" />
        <el-table-column label="失效日期" width="115">
          <template #default="{ row }">{{ row.effectiveTo || '长期有效' }}</template>
        </el-table-column>
        <el-table-column label="口径切换" width="95" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.caliberChange" type="warning" size="small">是</el-tag>
            <span v-else>否</span>
          </template>
        </el-table-column>
        <el-table-column prop="factorSource" label="来源" min-width="170" show-overflow-tooltip />
        <el-table-column prop="policyBasis" label="政策/台账依据" min-width="220" show-overflow-tooltip />
      </el-table>
    </div>

    <div class="page-card">
      <div class="table-toolbar">
        <div class="title">供热面积折算系数 / 口径规则</div>
        <el-button type="primary" :icon="Plus" size="small" @click="openRuleDialog">新增口径规则</el-button>
      </div>
      <el-table :data="ruleRows" border stripe>
        <el-table-column label="适用组织" width="150">
          <template #default="{ row }">{{ row.orgId === 'ALL' ? '全部组织' : (row.orgName || row.orgId) }}</template>
        </el-table-column>
        <el-table-column label="规则类型" width="150">
          <template #default="{ row }">{{ row.ruleType === 'heat_area_factor' ? '供热面积系数' : '电网因子' }}</template>
        </el-table-column>
        <el-table-column label="规则值" width="150" align="right">
          <template #default="{ row }">{{ Number(row.ruleValue).toFixed(8) }}</template>
        </el-table-column>
        <el-table-column prop="unit" label="单位" width="110" />
        <el-table-column prop="ruleVersion" label="版本" min-width="150">
          <template #default="{ row }"><span class="mono">{{ row.ruleVersion }}</span></template>
        </el-table-column>
        <el-table-column prop="effectiveFrom" label="生效日期" width="120" />
        <el-table-column label="失效日期" width="120">
          <template #default="{ row }">{{ row.effectiveTo || '长期有效' }}</template>
        </el-table-column>
        <el-table-column prop="source" label="来源" min-width="200" show-overflow-tooltip />
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" title="新增排放因子版本" width="560px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="数据品种" required>
          <el-select v-model="form.varId" filterable style="width: 100%">
            <el-option v-for="v in vars" :key="v.varId" :label="v.varName" :value="v.varId" />
          </el-select>
        </el-form-item>
        <el-form-item label="因子值" required>
          <el-input-number v-model="form.factorValue" :min="0" :precision="8" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="单位" required>
          <el-input v-model="form.factorUnit" placeholder="如 tCO2/MWh" />
        </el-form-item>
        <el-form-item label="版本号" required>
          <el-input v-model="form.factorVersion" placeholder="如 EF-ELEC-2026" />
        </el-form-item>
        <el-form-item label="生效日期" required>
          <el-date-picker v-model="form.effectiveFrom" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="失效日期">
          <el-date-picker v-model="form.effectiveTo" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="口径切换">
          <el-switch v-model="form.caliberChange" />
        </el-form-item>
        <el-form-item label="来源">
          <el-input v-model="form.factorSource" placeholder="如 全国电网平均因子" />
        </el-form-item>
        <el-form-item label="政策依据">
          <el-input v-model="form.policyBasis" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="ruleDialogVisible" title="新增口径规则" width="560px">
      <el-form :model="ruleForm" label-width="100px">
        <el-form-item label="规则编码" required>
          <el-input v-model="ruleForm.ruleId" placeholder="如 SNF-HEAT-2026" />
        </el-form-item>
        <el-form-item label="适用组织" required>
          <el-select v-model="ruleForm.orgId" style="width: 100%">
            <el-option label="全部组织" value="ALL" />
            <el-option v-for="o in orgs" :key="o.orgId" :label="o.orgName" :value="o.orgId" />
          </el-select>
        </el-form-item>
        <el-form-item label="规则类型" required>
          <el-select v-model="ruleForm.ruleType" style="width: 100%">
            <el-option label="供热面积系数" value="heat_area_factor" />
            <el-option label="电网因子" value="grid_factor" />
          </el-select>
        </el-form-item>
        <el-form-item label="规则值" required>
          <el-input-number v-model="ruleForm.ruleValue" :min="0" :precision="8" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="单位" required>
          <el-input v-model="ruleForm.unit" placeholder="GJ/m2 或 tCO2/MWh" />
        </el-form-item>
        <el-form-item label="版本号" required>
          <el-input v-model="ruleForm.ruleVersion" placeholder="如 CAL-SNF-2026" />
        </el-form-item>
        <el-form-item label="生效日期" required>
          <el-date-picker v-model="ruleForm.effectiveFrom" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="失效日期">
          <el-date-picker v-model="ruleForm.effectiveTo" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="来源">
          <el-input v-model="ruleForm.source" placeholder="协议/文件" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="ruleForm.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="ruleSaving" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { getCaliberRules, getFactors, saveCaliberRule, saveFactor } from '../api'
import { useMeta } from '../utils/meta'

const { orgs, vars, varName } = useMeta()
const rows = ref([])
const ruleRows = ref([])
const varId = ref('')
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const ruleDialogVisible = ref(false)
const ruleSaving = ref(false)

const form = reactive({
  varId: 'ELEC_TOTAL',
  factorValue: 0.5306,
  factorUnit: 'tCO2/MWh',
  factorVersion: 'EF-ELEC-2026',
  effectiveFrom: '2026-01-01',
  effectiveTo: null,
  caliberChange: false,
  factorSource: '全国电网平均因子',
  policyBasis: ''
})

const load = async () => {
  loading.value = true
  try {
    rows.value = await getFactors({ varId: varId.value || undefined })
  } finally {
    loading.value = false
  }
}

const loadRules = async () => {
  ruleRows.value = await getCaliberRules({ ruleType: 'heat_area_factor' })
}

const openDialog = () => {
  form.varId = varId.value || 'ELEC_TOTAL'
  form.factorValue = 0
  form.factorUnit = ''
  form.factorVersion = ''
  form.effectiveFrom = ''
  form.effectiveTo = null
  form.caliberChange = false
  form.factorSource = ''
  form.policyBasis = ''
  dialogVisible.value = true
}

const save = async () => {
  if (!form.varId || !form.factorVersion || !form.effectiveFrom || form.factorValue === null) {
    ElMessage.warning('请填写品种、因子值、版本号和生效日期')
    return
  }
  saving.value = true
  try {
    await saveFactor({ ...form })
    ElMessage.success('因子已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

const ruleForm = reactive({
  ruleId: '',
  orgId: 'SNF',
  ruleType: 'heat_area_factor',
  ruleValue: 0.38,
  unit: 'GJ/m2',
  ruleVersion: 'CAL-SNF-2026',
  effectiveFrom: '',
  effectiveTo: null,
  source: '企业供热协议',
  note: ''
})

const openRuleDialog = () => {
  Object.assign(ruleForm, {
    ruleId: '',
    orgId: 'SNF',
    ruleType: 'heat_area_factor',
    ruleValue: 0,
    unit: 'GJ/m2',
    ruleVersion: '',
    effectiveFrom: '',
    effectiveTo: null,
    source: '企业供热协议',
    note: ''
  })
  ruleDialogVisible.value = true
}

const saveRule = async () => {
  if (!ruleForm.ruleId || !ruleForm.ruleVersion || !ruleForm.effectiveFrom || ruleForm.ruleValue === null) {
    ElMessage.warning('请填写规则编码、版本、生效日期和规则值')
    return
  }
  ruleSaving.value = true
  try {
    await saveCaliberRule({ ...ruleForm })
    ElMessage.success('口径规则已保存')
    ruleDialogVisible.value = false
    await loadRules()
  } finally {
    ruleSaving.value = false
  }
}

onMounted(async () => {
  await Promise.all([load(), loadRules()])
})
</script>
