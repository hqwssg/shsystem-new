<template>
  <div class="page">
    <div class="page-card">
      <h2 class="page-title">新数据入库</h2>
      <p class="page-desc">
        手工录入月度活动数据。提交前须完成人工核实；确认入库后系统自动启动异常筛选，命中异常的数据进入人工审核流程，审核通过前不会正式启用。
      </p>
      <div class="tip-box">
        当前只录入活动数据，排放因子由系统按“组织 + 月份 + 品种”自动解析，不需要在每条数据中重复填写。
        如需校验因子版本，可在下方填写可选的因子版本号。
      </div>

      <el-form :model="form" label-width="96px" class="ingest-form">
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="组织" required>
              <el-select v-model="form.orgId" placeholder="请选择组织" style="width: 100%" @change="onOrgChange">
                <el-option v-for="o in orgs.filter(x => x.orgId !== 'SHL')" :key="o.orgId" :label="o.orgName" :value="o.orgId" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="月份" required>
              <el-date-picker
                v-model="form.period"
                type="month"
                value-format="YYYY-MM"
                placeholder="选择月份"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="数据品种" required>
              <el-select v-model="form.varId" placeholder="请选择品种" filterable style="width: 100%" @change="onVarChange">
                <el-option v-for="v in varOptions" :key="v.varId" :label="v.varName" :value="v.varId" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item :label="form.varId === 'ELEC_TOTAL' ? '电力总和' : '活动量'" required>
              <el-input-number v-model="form.value" :min="0" :precision="6" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="报表口径值">
              <el-input-number v-model="form.reportedValue" :min="0" :precision="6" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="单位">
              <el-input v-model="form.unit" placeholder="自动带出，可修改" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row v-if="showSplitFields" :gutter="16">
          <el-col :span="8">
            <el-form-item label="牵引电力" required>
              <el-input-number v-model="form.elecTrac" :min="0" :precision="6" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="辅助电力" required>
              <el-input-number v-model="form.elecAux" :min="0" :precision="6" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <div class="split-tip">机辆后续不再自动拆分，三项必须满足：电力总和 = 牵引 + 辅助</div>
          </el-col>
        </el-row>
        <el-row v-if="isNonJlgTotal">
          <el-col :span="24">
            <div class="split-tip">肃宁/原平无牵引电力：电力总和将全部作为辅助生产电力，系统自动补辅助电力记录。</div>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="16">
            <el-form-item label="因子版本">
              <el-input v-model="form.factorVersion" placeholder="可选；留空由系统解析，如需校验请填完整版本组合" clearable />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="提交人">
              <el-input v-model="form.operator" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item>
          <el-checkbox v-model="form.verified">数据已人工核实，确认进入入库流程</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Plus" @click="addRow">加入待入库列表</el-button>
          <el-button type="success" :icon="Upload" :disabled="!canSubmit" :loading="submitting" @click="submit(false)">
            确认入库并启动异常筛选
          </el-button>
          <el-button @click="resetForm">清空</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div class="page-card">
      <div class="table-toolbar">
        <div class="title">待入库数据</div>
        <div class="muted">共 {{ staging.length }} 条，审核前仅在本页暂存</div>
      </div>
      <el-table :data="staging" border stripe height="260" empty-text="请先录入并加入待入库列表">
        <el-table-column label="组织" width="140">
          <template #default="{ row }">{{ orgName(row.orgId) }}</template>
        </el-table-column>
        <el-table-column prop="period" label="月份" width="100" />
        <el-table-column label="数据品种" min-width="150">
          <template #default="{ row }">{{ varName(row.varId) }}</template>
        </el-table-column>
        <el-table-column label="活动量" width="150" align="right">
          <template #default="{ row }">{{ formatNumber(row.value) }}</template>
        </el-table-column>
        <el-table-column label="报表值" width="150" align="right">
          <template #default="{ row }">{{ formatNumber(row.reportedValue) }}</template>
        </el-table-column>
        <el-table-column prop="unit" label="单位" width="90" />
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ $index }">
            <el-button link type="danger" @click="staging.splice($index, 1)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="resultVisible" title="入库结果" width="520px">
      <el-result
        v-if="result"
        :icon="result.anomaly_count > 0 ? 'warning' : 'success'"
        :title="result.anomaly_count > 0 ? '已入库，存在待审核异常' : '入库成功'"
        :sub-title="`批次号：${result.batch_id || '—'}`"
      >
        <template #extra>
          <div class="result-tags">
            <el-tag type="success">有效记录 {{ result.row_count || 0 }} 条</el-tag>
            <el-tag v-if="result.anomaly_count" type="danger">待审核异常 {{ result.anomaly_count }} 条</el-tag>
            <el-tag v-if="result.watch_count" type="warning">关注级 {{ result.watch_count }} 条</el-tag>
          </div>
          <div class="result-actions">
            <el-button type="primary" @click="goReview">查看异常审核</el-button>
            <el-button @click="resultVisible = false">继续录入</el-button>
          </div>
        </template>
      </el-result>
    </el-dialog>

    <el-dialog v-model="overrideVisible" title="该月份已入库，确认覆盖？" width="560px">
      <el-alert
        title="同组织同月份已有活动数据。覆盖会重算排放，并把旧活动值、旧排放值、旧异常状态写入审计；旧的待审核异常会被关闭。"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 16px"
      />
      <el-form label-width="96px">
        <el-form-item label="覆盖原因" required>
          <el-input
            v-model="overrideReason"
            type="textarea"
            :rows="3"
            placeholder="请说明为什么需要覆盖，例如：原上报数据有误，按财务复核值更正"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="overrideVisible = false">取消</el-button>
        <el-button type="danger" :loading="submitting" @click="confirmOverride">确认覆盖</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Upload } from '@element-plus/icons-vue'
import { ingestActivity } from '../api'
import { useMeta } from '../utils/meta'
import { formatNumber } from '../utils/dict'

const router = useRouter()
const { orgs, vars, orgName, varName, varUnit, varsForOrg } = useMeta()
const staging = ref([])
const submitting = ref(false)
const resultVisible = ref(false)
const result = ref(null)
const overrideVisible = ref(false)
const overrideReason = ref('')

const form = reactive({
  orgId: 'JLG',
  period: '2026-01',
  varId: 'ELEC_TOTAL',
  value: 150000,
  reportedValue: null,
  unit: 'MWh',
  elecTrac: null,
  elecAux: null,
  factorVersion: '',
  operator: 'platform',
  verified: false
})

const canSubmit = computed(() => form.verified && staging.value.length > 0 && !submitting.value)
const varOptions = computed(() => varsForOrg(form.orgId))
const showSplitFields = computed(() => form.orgId === 'JLG' && form.varId === 'ELEC_TOTAL')
const isNonJlgTotal = computed(() => ['SNF', 'YPF'].includes(form.orgId) && form.varId === 'ELEC_TOTAL')

const onOrgChange = () => {
  if (!varOptions.value.some((x) => x.varId === form.varId)) {
    form.varId = 'ELEC_TOTAL'
    form.unit = varUnit('ELEC_TOTAL')
  }
  form.elecTrac = null
  form.elecAux = null
}

const onVarChange = (value) => {
  form.unit = varUnit(value)
  form.elecTrac = null
  form.elecAux = null
}

const addRow = () => {
  if (!form.orgId || !form.period || !form.varId) {
    ElMessage.warning('请先选择组织、月份和数据品种')
    return
  }
  if (form.value === null || form.value === undefined || Number(form.value) < 0) {
    ElMessage.warning('请填写有效的活动量')
    return
  }
  const unit = form.unit || varUnit(form.varId)
  if (showSplitFields.value) {
    if (form.elecTrac === null || form.elecTrac === undefined
      || form.elecAux === null || form.elecAux === undefined) {
      ElMessage.warning('机辆电力数据必须同时填写牵引电力和辅助生产电力')
      return
    }
    const total = Number(form.value)
    const sum = Number(form.elecTrac) + Number(form.elecAux)
    if (Math.abs(total - sum) > Math.max(1, Math.abs(total) * 0.001)) {
      ElMessage.warning(`电力不闭合：电力总和 ${total}，牵引+辅助 ${sum}`)
      return
    }
    staging.value.push(
      { orgId: form.orgId, period: form.period, varId: 'ELEC_TOTAL', value: form.value, reportedValue: form.reportedValue, unit },
      { orgId: form.orgId, period: form.period, varId: 'ELEC_TRAC', value: form.elecTrac, reportedValue: null, unit },
      { orgId: form.orgId, period: form.period, varId: 'ELEC_AUX', value: form.elecAux, reportedValue: null, unit }
    )
  } else if (isNonJlgTotal.value) {
    staging.value.push(
      { orgId: form.orgId, period: form.period, varId: 'ELEC_TOTAL', value: form.value, reportedValue: form.reportedValue, unit },
      { orgId: form.orgId, period: form.period, varId: 'ELEC_AUX', value: form.value, reportedValue: form.reportedValue, unit }
    )
  } else {
    staging.value.push({
      orgId: form.orgId,
      period: form.period,
      varId: form.varId,
      value: form.value,
      reportedValue: form.reportedValue,
      unit
    })
  }
  ElMessage.success('已加入待入库列表')
}

const submit = async (override = false) => {
  if (!form.verified) {
    ElMessage.warning('请先勾选“数据已人工核实”')
    return
  }
  if (!staging.value.length) {
    ElMessage.warning('待入库列表为空')
    return
  }
  if (override && !overrideReason.value.trim()) {
    ElMessage.warning('覆盖入库必须填写覆盖原因')
    return
  }
  submitting.value = true
  try {
    const data = await ingestActivity({
      idempotencyKey: `PLT-${form.orgId}-${form.period}-${Date.now()}`,
      operator: form.operator || 'platform',
      runAnomaly: true,
      factorVersion: form.factorVersion || undefined,
      override,
      overrideReason: override ? overrideReason.value.trim() : undefined,
      records: staging.value
    })
    overrideVisible.value = false
    result.value = data
    resultVisible.value = true
    staging.value = []
    overrideReason.value = ''
  } catch (error) {
    const status = error?.response?.status
    const message = error?.response?.data?.message || ''
    if (!override && status === 409 && message.includes('已入库')) {
      overrideVisible.value = true
    }
  } finally {
    submitting.value = false
  }
}

const confirmOverride = () => submit(true)

const resetForm = () => {
  staging.value = []
  form.verified = false
  form.value = null
  form.reportedValue = null
  form.factorVersion = ''
  overrideVisible.value = false
  overrideReason.value = ''
}

const goReview = () => {
  resultVisible.value = false
  router.push('/anomaly/review')
}
</script>

<style scoped>
.ingest-form {
  margin-top: 6px;
}

.result-tags {
  display: flex;
  gap: 10px;
  justify-content: center;
  margin-bottom: 18px;
}

.result-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
}

.split-tip {
  padding: 8px 12px;
  background: #fff8e6;
  border: 1px solid #f3dfb0;
  border-radius: 6px;
  color: #8a6d3b;
  font-size: 12px;
  line-height: 1.6;
}
</style>
