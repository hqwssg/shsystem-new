<template>
  <div v-loading="loading" class="storage-planning-results">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="decision">
      <el-alert :title="conclusion" :type="decision.decision === 'no_feasible_plan' ? 'warning' : 'success'" :description="decision.decisionReason" :closable="false" show-icon />
      <el-alert v-if="!truth(decision.formalEngineeringConclusionAllowed)" title="规划敏感性结论，不能作为正式工程结论" type="warning" :closable="false" show-icon />
      <el-alert v-if="!truth(decision.completeForDeclaredDomain)" title="搜索未完整结束，结论仅针对已评价候选" type="warning" :closable="false" show-icon />
      <p>结论等级：{{ levelLabel }}　数据状态：{{ dataStatus }}　搜索：{{ truth(decision.completeForDeclaredDomain) ? '声明范围内已完成' : '未完整完成' }}</p>
      <p v-if="result.referenceOnly">无可行方案。下方基线仅供参考，不作为推荐建设方案。</p>
      <el-descriptions v-if="result.selectedPlan" :title="result.referenceOnly ? '参考方案' : '当前查看方案'" border :column="3" size="small">
        <el-descriptions-item label="方案编码">{{ result.selectedPlan.sourcePlanCode }}</el-descriptions-item>
        <el-descriptions-item label="投资（元）">{{ number(result.selectedPlan.capexCny) }}</el-descriptions-item>
        <el-descriptions-item label="年总成本（元）">{{ number(result.selectedPlan.annualTotalCostCny) }}</el-descriptions-item>
        <el-descriptions-item label="年节约（元）">{{ number(result.selectedPlan.annualSavingVsNoBuildCny) }}</el-descriptions-item>
        <el-descriptions-item label="总容量（kWh）">{{ number(result.selectedPlan.totalCapacityKwh) }}</el-descriptions-item>
        <el-descriptions-item label="充电/放电功率（kW）">{{ number(result.selectedPlan.totalChargePowerKw) }} / {{ number(result.selectedPlan.totalDischargePowerKw) }}</el-descriptions-item>
      </el-descriptions>
      <h4>候选方案与淘汰原因</h4>
      <el-table :data="result.plans || []" border size="small" @row-click="choosePlan">
        <el-table-column prop="rank" label="排名" width="60" />
        <el-table-column prop="sourcePlanCode" label="方案" min-width="130" />
        <el-table-column label="推荐" width="70"><template #default="scope">{{ truth(scope.row.selected) && !result.referenceOnly ? '是' : '否' }}</template></el-table-column>
        <el-table-column prop="siteCodes" label="站点" min-width="120" />
        <el-table-column prop="totalCapacityKwh" label="容量kWh" />
        <el-table-column prop="capexCny" label="投资元" />
        <el-table-column prop="annualTotalCostCny" label="年成本元" />
        <el-table-column prop="annualSavingVsNoBuildCny" label="年节约元" />
        <el-table-column label="淘汰原因" min-width="200"><template #default="scope">{{ rejectionLabel(scope.row.rejectionReasons) }}</template></el-table-column>
        <el-table-column label="查看" width="70"><template #default="scope"><el-button link @click.stop="choosePlan(scope.row)">详情</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="pageNum" :page-size="20" :total="Number(result.total || 0)" layout="total, prev, pager, next" @current-change="load" />
      <h4>逐站设备配置</h4>
      <el-table :data="result.devices || []" size="small" border>
        <el-table-column prop="siteCode" label="站点" /><el-table-column prop="technologyCode" label="技术" />
        <el-table-column prop="capacityKwh" label="容量kWh" /><el-table-column prop="chargePowerKw" label="充电功率kW" />
        <el-table-column prop="dischargePowerKw" label="放电功率kW" /><el-table-column prop="capexCny" label="投资元" />
      </el-table>
      <h4>逐场景对比</h4>
      <el-table :data="scenarioRows" size="small" border>
        <el-table-column prop="scenarioCode" label="场景" />
        <el-table-column label="可行"><template #default="scope">{{ truth(scope.row.feasible) ? '是' : '否' }}</template></el-table-column>
        <el-table-column prop="baselineGridKwh" label="基线购电kWh" />
        <el-table-column prop="gridKwh" label="当前购电kWh" /><el-table-column prop="wastedKwh" label="弃能kWh" />
        <el-table-column prop="storageChargeKwh" label="储能充电kWh" /><el-table-column prop="storageDischargeKwh" label="储能放电kWh" />
        <el-table-column prop="finalSocKwh" label="期末电量kWh" /><el-table-column prop="annualOperatingCostCny" label="年运行成本元" />
      </el-table>
    </template>
  </div>
</template>
<script>
import { getStoragePlanning } from '@/api/carbon/energy'
export default {
  name: 'StoragePlanningResults',
  props: { runId: { type: String, required: true } },
  data() { return { loading: false, result: {}, pageNum: 1, planId: '', token: 0, error: '' } },
  computed: {
    decision() { return this.result.decision },
    conclusion() { return { recommend_build: '建议建设储能', keep_no_build: '建议不建设储能', no_feasible_plan: '无可行方案' }[this.decision.decision] || '规划结论待确认' },
    levelLabel() { return { formal_engineering: '正式来源输入（仍需工程复核）', engineering_candidate: '工程候选（需工程复核）', planning_sensitivity: '规划敏感性', diagnostic_only: '样例诊断' }[this.decision.recommendationLevel] || this.decision.recommendationLevel },
    dataStatus() { return (this.decision.details && (this.decision.details.inputDataStatusCodes || this.decision.details.dataStatuses) || []).map(value => ({ official: '正式数据', derived_from_official: '正式推导数据', planning_placeholder: '规划占位数据', synthetic: '样例数据' }[value] || value)).join('、') || (this.truth(this.decision.formalEngineeringConclusionAllowed) ? '正式数据或正式推导数据' : '含样例或规划占位数据') },
    scenarioRows() { return (this.result.scenarioResults || []).map(row => ({ ...row, baselineGridKwh: ((this.result.baselineScenarioResults || []).find(base => base.scenarioCode === row.scenarioCode) || {}).gridKwh })) }
  },
  watch: { runId: { immediate: true, handler() { this.pageNum = 1; this.planId = ''; this.load() } } },
  methods: {
    rejectionLabel(value) { return String(value || '').split(';').filter(Boolean).map(reason => ({ over_budget: '超出投资预算', core_scenario_infeasible: '核心场景不可行', grid_reduction_below_threshold: '购电削减未达到阈值', annual_saving_below_threshold: '年节约未达到阈值' }[reason] || reason)).join('；') },
    truth(value) { return value === true || value === 1 || value === '1' || value === 'true' },
    number(value) { return value == null ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) },
    choosePlan(row) { this.planId = row.storagePlanId; this.load() },
    load() {
      const token = ++this.token
      this.loading = true
      this.error = ''
      return getStoragePlanning(this.runId, { pageNum: this.pageNum, pageSize: 20, planId: this.planId || undefined }).then(res => {
        if (token !== this.token) return
        this.result = res.data || {}
      }).catch(() => { if (token === this.token) this.error = '读取规划结果失败，请刷新重试。' }).finally(() => { if (token === this.token) this.loading = false })
    }
  }
}
</script>
<style scoped>
.storage-planning-results { margin: 20px 0; }
.el-alert { margin-bottom: 12px; }
.el-pagination { margin-top: 12px; }
</style>
