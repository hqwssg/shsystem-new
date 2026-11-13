<template>
  <div class="app-container" v-if="item">
    <h2>{{ taskNames[item.run_type] }} <el-tag>{{ statusNames[item.status] }}</el-tag></h2>
    <p>{{ item.versionName }} · {{ item.completed_cases }} / {{ item.total_cases }} 个案例</p>
    <el-progress :percentage="item.total_cases?Math.round(100*item.completed_cases/item.total_cases):0" />
    <p v-if="item.current_case">当前：{{ item.current_case }}</p>
    <el-alert :title="item.disclaimer" type="info" :closable="false" style="margin:18px 0" />
    <el-alert v-if="item.error_message" :title="item.error_message" type="error" :closable="false" />
    <el-button @click="load">刷新</el-button><el-button @click="$router.push('/carbon/single-train')">返回列表</el-button>
    <el-button v-if="active" v-hasPermi="['carbon:singleTrain:cancel']" type="danger" :loading="cancelling" @click="cancel">取消任务</el-button>
    <h3>案例指标</h3>
    <p class="hint">步长按各案例记录：新任务使用 0.0001 秒；历史任务保留原计算口径。</p>
    <el-table :data="item.cases">
      <el-table-column label="制动场景" min-width="210"><template #default="s">{{ scenarioName(s.row.scenario_key) }}</template></el-table-column>
      <el-table-column prop="controller_name" label="控制器" min-width="200" />
      <el-table-column label="计算步长（秒）" width="140"><template #default="s">{{ s.row.metrics.simulation_dt_s == null ? '历史记录未标注' : s.row.metrics.simulation_dt_s }}</template></el-table-column>
      <el-table-column v-if="isEco" label="运行时间（s）" width="150"><template #default="s">{{ number(s.row.metrics.runtime_s,2) }}</template></el-table-column>
      <el-table-column v-if="isEco" label="牵引能耗（kWh）" width="165"><template #default="s">{{ number(s.row.metrics.traction_energy_kwh) }}</template></el-table-column>
      <el-table-column v-if="isEco" label="区段净能耗（kWh）" width="175"><template #default="s">{{ number(s.row.metrics.section_net_energy_kwh) }}</template></el-table-column>
      <el-table-column label="吸收电量（kWh）" width="150"><template #default="s">{{ number(s.row.metrics.captured_energy_kWh) }}</template></el-table-column>
      <el-table-column label="储能增加量（kWh）" width="165"><template #default="s">{{ number(s.row.metrics.storage_energy_kWh) }}</template></el-table-column>
      <el-table-column label="净再生回收（kWh）" width="165"><template #default="s">{{ number(s.row.metrics.storage_net_of_grid_import_energy_kWh) }}</template></el-table-column>
      <el-table-column label="回网（kWh）" width="130"><template #default="s">{{ number(s.row.metrics.grid_export_energy_kWh) }}</template></el-table-column>
      <el-table-column label="期末电量" width="110"><template #default="s">{{ number(s.row.metrics.soc_final*100,2) }} %</template></el-table-column>
      <el-table-column label="校验 / 排名资格" min-width="210"><template #default="s"><span v-if="s.row.status==='failed'">执行失败：{{ s.row.error_message }}</span><span v-else-if="s.row.metrics.physical_violation || s.row.metrics.closure_failure" class="error">未通过：{{ (s.row.metrics.violation_reasons || []).map(violationName).join('、') }} {{ s.row.metrics.closure_failure?'能量闭合':'' }}</span><span v-else-if="isEco && !s.row.metrics.trajectory_feasible" class="error">轨迹未通过：{{ (s.row.metrics.constraint_violations || []).join('、') }}</span><span v-else>{{ s.row.eligible?'通过，可参与比较':'通过，仅作参照' }}</span></template></el-table-column>
      <el-table-column label="操作" width="100"><template #default="s"><el-button v-if="s.row.status==='completed'" link @click="selectCase(s.row)">详情曲线</el-button></template></el-table-column>
    </el-table>
    <el-empty v-if="!item.cases.length" :description="active?'案例计算中，完成后将展示指标和曲线':'没有已完成案例，请查看任务错误原因'" />
    <div v-if="selected">
      <h3>{{ scenarioName(selected.scenario_key) }} / {{ selected.controller_name }}</h3>
      <p v-if="comparison">{{ comparison }}</p>
      <el-descriptions :column="detailColumns" border>
        <el-descriptions-item label="摩擦制动电量（kWh）">{{ number(selected.metrics.friction_braking_energy_kWh) }}</el-descriptions-item>
        <el-descriptions-item label="变流器损耗（kWh）">{{ number(selected.metrics.converter_loss_energy_kWh) }}</el-descriptions-item>
        <el-descriptions-item label="储能损耗（kWh）">{{ number(selected.metrics.storage_loss_energy_kWh) }}</el-descriptions-item>
        <el-descriptions-item label="输出电压峰值（V）">{{ number(selected.metrics.output_voltage_peak_v,2) }}</el-descriptions-item>
        <el-descriptions-item label="电感电流峰值（A）">{{ number(selected.metrics.inductor_current_peak_a,2) }}</el-descriptions-item>
        <el-descriptions-item label="能量闭合相对残差">{{ typeof selected.metrics.closure_relative_residual==='number' ? selected.metrics.closure_relative_residual.toExponential(3) : '不适用' }}</el-descriptions-item>
      </el-descriptions>
      <p class="hint">净再生回收已扣除电网回吸；历史案例缺少该指标时显示“未记录”，不使用吸收电量替代。</p>
      <el-alert v-for="(note, index) in selected.audit.notes || []" :key="index" :title="note" type="info" :closable="false" style="margin:8px 0" />
      <el-radio-group v-model="chartKind" style="margin:20px 0" @change="draw"><el-radio-button value="voltage">电压</el-radio-button><el-radio-button value="current">电流</el-radio-button><el-radio-button value="soc">储能电量</el-radio-button><el-radio-button value="power">吸收功率</el-radio-button><el-radio-button v-if="isEco" value="speed">运行速度</el-radio-button></el-radio-group>
      <div ref="chart" v-loading="chartLoading" style="height:390px" />
      <p v-if="curve" class="hint">预览 {{ curve.displayPoints }} 点，完整记录 {{ curve.totalPoints }} 点；指标和校验按完整记录计算。</p>
      <el-collapse>
        <el-collapse-item title="全部指标及计算口径">
          <el-table :data="metricRows" size="small"><el-table-column prop="label" label="指标" min-width="220" /><el-table-column prop="value" label="数值" min-width="140" /><el-table-column prop="description" label="说明" min-width="300" /></el-table>
        </el-collapse-item>
        <el-collapse-item title="物理约束与算法审计详情"><pre>{{ JSON.stringify(selected.audit, null, 2) }}</pre></el-collapse-item>
      </el-collapse>
    </div>
    <h3>结果文件</h3><p class="hint">NPZ 是完整压缩曲线；CSV 可用于表格分析；运行清单包含输入快照和算法摘要。</p>
    <el-button v-for="a in item.artifacts" :key="a.artifact_id" v-hasPermi="['carbon:singleTrain:download']" :disabled="downloading" size="small" style="margin:5px" @click="downloadFile(a)">{{ artifactName(a) }}</el-button>
  </div>
</template>
<script>
import * as echarts from 'echarts'
import { saveAs } from 'file-saver'
import { run, cancelRun, trace, download, taskNames, statusNames } from '@/api/carbon/singleTrain'
import { scenarioName } from '@/utils/singleTrainScenarios'
import { requestResult } from '@/utils/singleTrainRequests'
export default {
  name: 'CarbonSingleTrainRun', data: () => ({ item: null, selected: null, curve: null, chartKind: 'voltage', chartLoading: false, taskNames, statusNames, detailColumns: window.innerWidth < 900 ? 1 : 3, chartRequest: 0, runRequest: 0, loadPending: false, cancelling: false, downloading: false, viewActive: true, disposed: false }),
  computed: {
    isEco() { return this.item && this.item.run_type === 'eco_driving' },
    active() { return this.item && ['queued', 'running'].includes(this.item.status) },
    metricRows() { if (!this.selected) return []; return Object.entries(this.selected.metrics).map(([key, value]) => { const field = (this.item.metricFields || {})[key] || [key, '']; return { label: field[0], description: field[1], value: typeof value === 'number' ? this.number(value, 6) : value == null ? '未记录' : typeof value === 'object' ? JSON.stringify(value) : String(value) } }) },
    comparison() { if (this.isEco) { const rows = this.item.cases; const a = rows.find(c => c.controller_key === 'baseline'); const b = rows.find(c => c.controller_key === 'optimized'); if (!a || !b) return '对比方案计算中。'; if (!a.eligible || !b.eligible || ![a, b].every(c => Number.isFinite(c.metrics.section_net_energy_kwh))) return '存在未通过轨迹或电气校验的方案，仅展示仿真结果，不生成节能结论。'; return '优化操纵比经验操纵的区段净能耗减少 ' + this.number(a.metrics.section_net_energy_kwh - b.metrics.section_net_energy_kwh) + ' kWh；净能耗为牵引能耗扣除净再生回收。' } if (!this.selected || this.selected.controller_key !== 'rhonn_nsmc') return ''; if (this.item.run_type === 'simulation') return '收益对比请使用“控制器对比”功能。'; const main = this.selected; if (!main.eligible) return '主算法未通过结果校验，本案例不进行收益排名。'; const key = 'storage_net_of_grid_import_energy_kWh'; if (!Number.isFinite(main.metrics[key]) || !Number.isFinite(main.metrics.simulation_dt_s)) return '历史案例未记录净再生回收口径或计算步长，不进行收益排名。'; const others = this.item.cases.filter(c => c.scenario_key === main.scenario_key && c.eligible && c.controller_key !== 'rhonn_nsmc' && Number.isFinite(c.metrics[key]) && c.metrics.simulation_dt_s === main.metrics.simulation_dt_s && c.metrics.metric_schema_version === main.metrics.metric_schema_version); if (!others.length) return '没有同口径、同步长且通过校验的基准控制器。'; const best = others.reduce((a, b) => a.metrics[key] >= b.metrics[key] ? a : b); return '与同场景最佳合格基准（' + best.controller_name + '）相比，净再生回收差值为 ' + this.number(main.metrics[key] - best.metrics[key]) + ' kWh。' }
  },
  created() { this.load(); this.timer = setInterval(() => { if (this.viewActive && this.active) this.load() }, 4000) },
  activated() { this.viewActive = true; if (!this.item) this.load() },
  deactivated() { this.viewActive = false; this.runRequest++; this.chartRequest++; this.loadPending = false; this.chartLoading = false; if (!this.curve) this.selected = null },
  beforeUnmount() { this.disposed = true; this.viewActive = false; this.runRequest++; this.chartRequest++; clearInterval(this.timer); if (this.chart) this.chart.dispose(); window.removeEventListener('resize', this.resize) },
  methods: {
    scenarioName,
    violationName(key) { return ({ input_voltage: '输入电压越限', output_voltage: '输出电压越限', inductor_current: '电感电流越限', output_current: '输出电流越限', input_current: '输入电流越限', input_power: '输入功率越限', soc: '储能电量越限', duty_T1: '第一路控制量越限', duty_T2: '第二路控制量越限' })[key] || key },
    async load() { if (this.loadPending || !this.viewActive || this.disposed) return; const request = ++this.runRequest; const id = this.$route.params.runId; this.loadPending = true; const result = await requestResult(run(id)); if (this.disposed || !this.viewActive || request !== this.runRequest || id !== this.$route.params.runId) return; this.loadPending = false; if (!result.ok) return; this.item = result.response.data; if (!this.selected && this.item.cases.some(c => c.status === 'completed')) await this.selectCase(this.item.cases.find(c => c.controller_key === 'rhonn_nsmc' && c.status === 'completed') || this.item.cases.find(c => c.status === 'completed')) },
    number(v, digits = 4) { return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '未记录' },
    async cancel() { if (this.cancelling || !this.active) return; const id = this.item.run_id; this.cancelling = true; try { const result = await requestResult(cancelRun(id)); if (result.ok && !this.disposed && this.viewActive && this.item.run_id === id) this.item = result.response.data } finally { this.cancelling = false } },
    async selectCase(c) { if (!this.viewActive || this.disposed || !this.item || !this.item.cases.some(row => row.case_id === c.case_id)) return; const request = ++this.chartRequest; const runId = this.item.run_id; const caseId = c.case_id; this.selected = c; this.curve = null; this.chartLoading = true; if (this.chart) this.chart.clear(); const result = await requestResult(trace(caseId)); const current = () => !this.disposed && this.viewActive && request === this.chartRequest && this.item.run_id === runId && this.selected && this.selected.case_id === caseId; if (!current()) return; this.chartLoading = false; if (!result.ok) return; this.curve = result.response.data; await this.$nextTick(); if (current()) this.draw() },
    draw() { if (!this.curve || !this.$refs.chart) return; if (!this.chart) { this.chart = echarts.init(this.$refs.chart); window.addEventListener('resize', this.resize) } const fields = { voltage: [['output_voltage_v', '储能侧电压'], ['input_voltage_v', '输入电压']], current: [['inductor_current_a', '电感电流']], soc: [['soc', '储能电量']], power: [['accepted_power_w', '吸收功率']], speed: [['speed_mps', '运行速度']] }[this.chartKind]; const unit = { voltage: 'V', current: 'A', soc: '%', power: 'kW', speed: 'km/h' }[this.chartKind]; this.chart.setOption({ tooltip: { trigger: 'axis' }, legend: {}, xAxis: { type: 'value', name: '时间（s）' }, yAxis: { type: 'value', name: unit, scale: true }, series: fields.filter(([key]) => this.curve.series[key]).map(([key, name]) => ({ name, type: 'line', showSymbol: false, data: this.curve.series.time_s.map((time, i) => [time, this.curve.series[key][i] * (key === 'speed_mps' ? 3.6 : key === 'soc' ? 100 : key === 'accepted_power_w' ? 0.001 : 1)]) })) }, true) },
    resize() { this.detailColumns = window.innerWidth < 900 ? 1 : 3; if (this.chart) this.chart.resize() },
    artifactName(a) { const c = this.item.cases.find(c => c.case_id === a.case_id); return c ? scenarioName(c.scenario_key) + ' / ' + c.controller_name + ' .' + a.kind : a.relative_path === 'manifest.json' ? '运行清单' : a.relative_path.split('/').pop() },
    async downloadFile(a) { if (this.downloading) return; this.downloading = true; try { const result = await requestResult(download(a.artifact_id)); if (result.ok && !this.disposed && this.viewActive) saveAs(result.response, a.relative_path) } finally { this.downloading = false } }
  }
}
</script>
<style scoped>.hint{color:#909399}.error{color:#f56c6c}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>
