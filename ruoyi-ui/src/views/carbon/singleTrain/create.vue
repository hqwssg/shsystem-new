<template>
  <div class="app-container" v-loading="loading">
    <h2>新建能量回收任务</h2>
    <el-form label-width="150px" style="max-width:1050px">
      <el-form-item label="数据版本"><el-select v-model="versionId" style="width:100%" @change="loadPreset"><el-option v-for="v in versions" :key="v.version_id" :label="v.version_name" :value="v.version_id" /></el-select></el-form-item>
      <el-form-item label="功能"><el-select v-model="runType" @change="changeType"><el-option v-for="(name,key) in taskNames" :key="key" :label="name" :value="key" /></el-select></el-form-item>
      <el-form-item v-if="!isEco" label="制动场景"><el-select v-model="keys" multiple :multiple-limit="runType==='validation'?0:1" style="width:100%" @change="changeScenario"><el-option v-for="s in scenarios" :key="s.key" :label="s.name" :value="s.key" /></el-select></el-form-item>
      <el-form-item v-if="runType!=='validation'" label="初始速度"><el-input-number v-model="speed" :min="speedMin" :max="speedMax" :step="1" /> km/h<p v-if="routeScenario" class="hint">真实线路需满足整个制动区段的再生条件和逐点限速，提交前由系统校验。</p><p v-else-if="!isEco" class="hint">当前制动窗口允许 {{ speedMin }}～{{ speedMax }} km/h。</p></el-form-item>
      <el-form-item label="储能初始电量"><el-input-number v-model="socPercent" :min="socMin" :max="socMax" :step="1" /> %<p v-if="!isEco" class="hint">接近满电场景采用其指定的初始电量；其他场景采用此值。</p></el-form-item>
      <template v-if="isEco">
        <el-form-item v-if="!eco.ready"><el-alert :title="eco.message || '当前版本不支持节能驾驶'" type="warning" :closable="false" /></el-form-item>
        <el-form-item label="列车"><el-select v-model="trainName"><el-option label="重车" value="Heavy" /><el-option label="空车" value="Empty" /></el-select></el-form-item>
        <el-form-item label="区段起止里程"><el-input-number v-model="ecoStart" :min="eco.minKm" :max="eco.maxKm" :precision="3" :step="0.1" /> 至 <el-input-number v-model="ecoEnd" :min="eco.minKm" :max="eco.maxKm" :precision="3" :step="0.1" /> km</el-form-item>
        <el-form-item label="目标运行时间"><el-input-number v-model="runtime" :min="1" :max="195" /> 秒<p class="hint">当前精细电气仿真每个方案最多200万步，请选择运行时间不超过195秒的短区段。</p></el-form-item>
        <el-form-item label="终点速度"><el-input-number v-model="terminalSpeed" :min="0" :max="80" /> km/h</el-form-item>
      </template>
      <el-form-item v-if="!isEco && keys.some(k=>k.startsWith('sR'))" label="线路起点里程"><el-input-number v-model="routeStart" :min="0" :step="1" /> km</el-form-item>
      <el-form-item><el-alert title="系统已采用默认算法配置。结果属于仿真，电气模型中的预设与占位参数由管理员维护。" type="info" :closable="false" /></el-form-item>
      <el-form-item><el-button type="primary" :disabled="!canSubmit" :loading="saving" @click="submit">提交任务</el-button><el-button @click="$router.push('/carbon/single-train')">返回列表</el-button></el-form-item>
    </el-form>
    <el-empty v-if="!versions.length" description="没有已发布且可运行的数据版本，请联系管理员维护" />
  </div>
</template>
<script>
import { versionApi, preset, createRun, taskNames } from '@/api/carbon/singleTrain'
import { scenarioName } from '@/utils/singleTrainScenarios'
import { requestResult } from '@/utils/singleTrainRequests'
export default {
  name: 'CarbonSingleTrainCreate', data: () => ({ versions: [], versionId: '', runType: 'simulation', eco: {}, trainName: 'Heavy', ecoStart: 108, ecoEnd: 108.2, runtime: 40, terminalSpeed: 0, keys: [], scenarios: [], loading: false, saving: false, ready: false, speed: 36, socPercent: 50, socMin: 10, socMax: 90, routeStart: 0, taskNames, requestKey: '', versionsRequest: 0, versionsLoading: false, versionsLoaded: false, presetRequest: 0, presetVersion: '', viewActive: true, disposed: false }),
  computed: {
    isEco() { return this.runType === 'eco_driving' },
    chosenScenario() { return this.scenarios.find(s => s.key === this.keys[0]) },
    routeScenario() { return !this.isEco && this.keys.some(k => k.startsWith('sR')) },
    speedMin() { if (this.isEco) return 0; return this.chosenScenario && this.chosenScenario.speedMinKmh != null ? this.chosenScenario.speedMinKmh : 5.4 },
    speedMax() { if (this.isEco) return 80; return this.chosenScenario && this.chosenScenario.speedMaxKmh != null ? this.chosenScenario.speedMaxKmh : 80 },
    canSubmit() { return this.viewActive && this.ready && !this.loading && !this.saving && this.presetVersion === this.versionId && (this.isEco ? this.eco.ready && Number.isFinite(this.ecoStart) && Number.isFinite(this.ecoEnd) && this.ecoStart >= this.eco.minKm && this.ecoEnd <= this.eco.maxKm && this.ecoStart < this.ecoEnd && Number.isFinite(this.runtime) && this.runtime > 0 && this.runtime <= 195 && Number.isFinite(this.terminalSpeed) && this.terminalSpeed >= 0 && this.terminalSpeed <= 80 : this.keys.length > 0 && this.keys.every(k => this.scenarios.some(s => s.key === k))) && (this.runType === 'validation' || (Number.isFinite(this.speed) && this.speedMin <= this.speed && this.speed <= this.speedMax)) && Number.isFinite(this.socPercent) && this.socMin <= this.socPercent && this.socPercent <= this.socMax }
  },
  created() { this.loadVersions() },
  activated() { this.viewActive = true; if (!this.versionsLoaded) this.loadVersions(); else if (this.versionId && !this.ready && !this.loading) this.loadPreset() },
  deactivated() { this.viewActive = false; this.presetRequest++; this.versionsRequest++; this.versionsLoading = false; this.loading = false },
  beforeUnmount() { this.disposed = true; this.viewActive = false; this.presetRequest++; this.versionsRequest++ },
  methods: {
    async loadVersions() { if (this.versionsLoading) return; const request = ++this.versionsRequest; this.versionsLoading = true; const result = await requestResult(versionApi().list()); if (this.disposed || !this.viewActive || request !== this.versionsRequest) return; this.versionsLoading = false; if (!result.ok) return; this.versionsLoaded = true; this.versions = result.response.data.filter(v => v.status === 'published' && v.readiness.ready); if (this.versions.length) { this.versionId = this.versions[0].version_id; await this.loadPreset() } },
    async loadPreset() { const request = ++this.presetRequest; const version = this.versionId; this.loading = true; this.ready = false; this.presetVersion = ''; this.requestKey = ''; const result = await requestResult(preset(version)); if (this.disposed || !this.viewActive || request !== this.presetRequest || version !== this.versionId) return; this.loading = false; if (!result.ok) return; const p = result.response.data; this.eco = p.ecoDriving || {}; if (this.eco.ready) { this.ecoStart = this.eco.routeStartKm; this.ecoEnd = this.eco.routeEndKm; this.runtime = this.eco.targetRuntimeS; this.terminalSpeed = this.eco.terminalSpeedKmh } this.scenarios = p.scenarios.map(s => ({ ...s, name: scenarioName(s.key) })); this.socPercent = p.socInitial * 100; this.socMin = p.socMin * 100; this.socMax = p.socMax * 100; this.changeType(); this.presetVersion = version; this.ready = p.readiness.ready },
    changeType() { if (this.isEco) { this.speed = this.eco.initialSpeedKmh || 36; this.requestKey = ''; return } this.keys = this.runType === 'validation' ? this.scenarios.slice(0, 2).map(s => s.key) : this.scenarios.slice(0, 1).map(s => s.key); this.changeScenario() },
    changeScenario() { const key = this.keys[0] || ''; this.speed = key.startsWith('s2') || key.startsWith('s5') ? 18 : key.startsWith('sR') ? 30 : 36; this.requestKey = '' },
    async submit() { if (!this.canSubmit) return; this.saving = true; try { const parameters = this.isEco ? { trainName: this.trainName, routeStartKm: this.ecoStart, routeEndKm: this.ecoEnd, terminalSpeedKmh: this.terminalSpeed, targetRuntimeS: this.runtime, initialSoc: this.socPercent / 100 } : { scenarioKeys: [...this.keys], initialSoc: this.socPercent / 100 }; if (this.runType !== 'validation') parameters.initialSpeedKmh = this.speed; if (!this.isEco && this.routeScenario) parameters.routeStartKm = this.routeStart; const key = JSON.stringify({ versionId: this.versionId, runType: this.runType, parameters }); if (!this.requestKey || this.requestKey.body !== key) this.requestKey = { body: key, id: window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : Date.now() + '-' + Math.random().toString(16).slice(2) }; const result = await requestResult(createRun({ versionId: this.versionId, runType: this.runType, parameters, idempotencyKey: this.requestKey.id })); if (result.ok && !this.disposed && this.viewActive) this.$router.push('/carbon/single-train/runs/' + result.response.data.run_id) } finally { this.saving = false } }
  }
}
</script>
<style scoped>.hint{color:#909399}</style>
