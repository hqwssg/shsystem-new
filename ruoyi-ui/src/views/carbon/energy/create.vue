<template>
  <div class="app-container energy-create">
    <div class="page-actions">
      <el-button :icon="$icon('el-icon-back')" size="small" @click="$router.push('/carbon/energy')">返回重空协同</el-button>
    </div>
    <el-form label-width="168px" size="small">
      <el-form-item label="数据版本">
        <el-select v-model="versionKey" filterable placeholder="请选择已发布版本" @change="onVersionChange" style="width: 460px">
          <el-option v-for="item in versions" :key="item.projectCode + '/' + item.versionCode"
            :label="versionLabel(item)"
            :value="item.projectCode + '/' + item.versionCode" />
        </el-select>
        <div v-if="!versions.length" class="el-form-item__error" style="position: static">当前部门没有已发布版本。演示数据已导入为 shuohuang_demo / v1，刷新本页即可看到。</div>
      </el-form-item>
      <el-form-item v-if="versionFileRows.length" label="数据说明">
        <el-table :data="versionFileRows" max-height="180" size="small">
          <el-table-column prop="displayPath" label="数据" min-width="160" />
          <el-table-column prop="hint" label="说明" min-width="280" />
        </el-table>
      </el-form-item>
      <el-form-item label="任务类型">
        <el-select v-model="form.runType" style="width: 280px" @change="onRunTypeChange">
          <el-option v-for="item in runTypes" :key="item.value" :label="item.label" :value="item.value" :title="item.tip" />
        </el-select>
      </el-form-item>

      <el-alert :title="typeHint" type="info" :closable="false" show-icon class="type-hint" />
      <el-alert :title="presetHint" :type="presetRunId ? 'success' : 'info'" :closable="false" class="type-hint" />

      <template v-if="form.runType === 'storage_planning'">
        <el-alert v-if="!planningReady" :title="planningIssues.join('；') || '当前版本储能规划数据尚未就绪，请在数据维护中补齐六张表。'" type="warning" :closable="false" class="type-hint" />
        <el-form-item label="规划策略"><el-select v-model="form.planningPolicyCode" :disabled="!planningReady"><el-option v-for="item in planningPolicyOptions" :key="item.code" :label="item.label" :value="item.code" /></el-select></el-form-item>
        <el-form-item label="场景集"><el-select v-model="form.scenarioSetCode" :disabled="!planningReady"><el-option v-for="item in scenarioSetOptions" :key="item.code" :label="item.label" :value="item.code" /></el-select></el-form-item>
        <el-form-item label="搜索方式"><el-select v-model="form.searchMode" @change="onUserEdit"><el-option label="粗搜索" value="coarse" /><el-option label="粗搜索后细化" value="coarse_to_fine" /><el-option label="完整离散搜索" value="exhaustive" /></el-select></el-form-item>
        <el-form-item v-if="form.searchMode !== 'exhaustive'" label="每维档位数"><el-input-number v-model="form.maxLevelsPerDimension" :min="2" :precision="0" @change="onUserEdit" /></el-form-item>
        <el-form-item label="结算步长（秒）"><el-input-number v-model="form.settlementStepS" :min="1" :precision="0" @change="onUserEdit" /></el-form-item>
        <el-form-item v-if="form.searchMode === 'coarse_to_fine'" label="细化候选数"><el-input-number v-model="form.refinementShortlistSize" :min="1" :precision="0" @change="onUserEdit" /></el-form-item>
      </template>

      <template v-if="needsTimetable">
        <el-form-item>
          <template #label><span  :title="fieldTip('timetableRelativePath')">运行图</span></template>
          <el-select v-if="timetableSelectOptions.length > 1" v-model="form.timetableRelativePath" placeholder="请选择运行图" style="width: 460px">
            <el-option
              v-for="item in timetableSelectOptions"
              :key="'tt-' + item.value"
              :label="item.label"
              :value="item.value" />
          </el-select>
          <span v-else-if="timetableSelectOptions.length === 1">{{ timetableSelectOptions[0].label }}</span>
          <div v-if="!timetableSelectOptions.length" class="form-hint">当前版本没有运行图。</div>
        </el-form-item>
      </template>

      <template v-if="form.runType === 'timetable_optimization'">
        <el-row>
          <el-col :span="8">
            <el-form-item>
              <template #label><span  :title="fieldTip('maxShiftMin')">最大平移(分)</span></template>
              <el-input-number v-model="form.maxShiftMin" :min="0" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item>
              <template #label><span  :title="fieldTip('maxDwellExtensionMin')">停站延长(分)</span></template>
              <el-input-number v-model="form.maxDwellExtensionMin" :min="0" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item>
              <template #label><span  :title="fieldTip('searchIntensity')">搜索力度</span></template>
              <el-select v-model="form.searchIntensity" style="width: 160px">
                <el-option label="快" value="quick" />
                <el-option label="标准" value="standard" />
                <el-option label="细" value="fine" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <div class="form-hint form-hint-block">时刻最多能动多少、停站最多能加多少；搜索力度只影响算多久。算法固定用进化搜索。</div>
      </template>

      <template v-if="form.runType === 'dispatch'">
        <el-row>
          <el-col :span="8">
            <el-form-item>
              <template #label><span  :title="fieldTip('heavyCount')">重车列数</span></template>
              <el-input-number v-model="form.heavyCount" :min="1" :max="40" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item>
              <template #label><span  :title="fieldTip('emptyCount')">空车列数</span></template>
              <el-input-number v-model="form.emptyCount" :min="1" :max="40" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item>
              <template #label><span  :title="fieldTip('searchIntensity')">搜索力度</span></template>
              <el-select v-model="form.searchIntensity" style="width: 160px">
                <el-option label="快" value="quick" />
                <el-option label="标准" value="standard" />
                <el-option label="细" value="fine" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item>
          <template #label><span  :title="fieldTip('objectivePriority')">优化目标</span></template>
          <el-select v-model="form.objectivePriority" style="width: 220px" @change="onUserEdit">
            <el-option label="节能优先" value="energy_first" />
            <el-option label="成本优先" value="cost_first" />
            <el-option label="均衡" value="balanced" />
          </el-select>
        </el-form-item>
        <div class="form-hint form-hint-block">重空列数决定排多少列车；搜索力度只影响算多久。储能按版本数据复用，发车间隔用算法默认。</div>
      </template>

      <template v-if="form.runType === 'rolling_rescheduling'">
        <el-form-item>
          <template #label><span  :title="fieldTip('searchIntensity')">搜索力度</span></template>
          <el-select v-model="form.searchIntensity" style="width: 160px">
            <el-option label="快" value="quick" />
            <el-option label="标准" value="standard" />
            <el-option label="细" value="fine" />
          </el-select>
          <span class="inline-hint">快：少试几套；标准：日常；细：更慢更仔细</span>
        </el-form-item>
        <el-form-item>
          <template #label><span  :title="fieldTip('rollingSource')">滚动状态来源</span></template>
          <el-radio-group v-model="form.rollingSource">
            <el-radio value="none">不附加</el-radio>
            <el-radio value="replay">历史扰动回放</el-radio>
            <el-radio value="devices">分设备当前状态</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.rollingSource === 'replay'">
          <template #label><span  :title="fieldTip('disturbanceHistoryRelativePath')">扰动回放</span></template>
          <el-select v-if="disturbanceSelectOptions.length > 1" v-model="form.disturbanceHistoryRelativePath" placeholder="请选择扰动回放" style="width: 460px">
            <el-option
              v-for="item in disturbanceSelectOptions"
              :key="'rp-' + item.value"
              :label="item.label"
              :value="item.value" />
          </el-select>
          <span v-else-if="disturbanceSelectOptions.length === 1">{{ disturbanceSelectOptions[0].label }}</span>
          <div v-if="!disturbanceSelectOptions.length" class="form-hint">当前版本没有扰动回放。</div>
        </el-form-item>
        <el-form-item v-if="form.rollingSource === 'devices'">
          <template #label><span  :title="fieldTip('storageDevices')">分设备状态</span></template>
          <el-table :data="form.storageDevices" size="small" border>
            <el-table-column min-width="220">
              <template #header><span :title="fieldTip('storageSectionId')">储能区间编号</span></template>
              <template #default="scope">
                <el-input v-model="scope.row.storage_section_id" placeholder="storage_section_1:K145-K164" />
              </template>
            </el-table-column>
            <el-table-column width="140">
              <template #header><span :title="fieldTip('socKwh')">当前电量 kWh</span></template>
              <template #default="scope">
                <el-input-number v-model="scope.row.soc_kwh" :min="0" :controls="false" style="width: 120px" />
              </template>
            </el-table-column>
            <el-table-column width="80">
              <template #header><span :title="fieldTip('available')">可用</span></template>
              <template #default="scope">
                <el-switch v-model="scope.row.available" />
              </template>
            </el-table-column>
            <el-table-column width="140">
              <template #header><span :title="fieldTip('maxChargePowerKw')">最大充电 kW</span></template>
              <template #default="scope">
                <el-input-number v-model="scope.row.max_charge_power_kw" :min="0" :controls="false" style="width: 120px" />
              </template>
            </el-table-column>
            <el-table-column width="140">
              <template #header><span :title="fieldTip('maxDischargePowerKw')">最大放电 kW</span></template>
              <template #default="scope">
                <el-input-number v-model="scope.row.max_discharge_power_kw" :min="0" :controls="false" style="width: 120px" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="70">
              <template #default="scope">
                <el-button link @click="removeDevice(scope.$index)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div style="margin-top: 8px">
            <el-button size="small" @click="addDevice">增加设备</el-button>
            <el-button size="small" @click="fillRollingDeviceDemo">填入演示两台储能</el-button>
          </div>
        </el-form-item>
      </template>

      <template v-if="form.runType === 'joint_parameter_robustness'">
        <el-form-item>
          <template #label><span  :title="fieldTip('parameterRangesRelativePath')">参数区间</span></template>
          <el-select v-if="parameterRangeSelectOptions.length > 1" v-model="form.parameterRangesRelativePath" placeholder="请选择参数区间" style="width: 460px">
            <el-option
              v-for="item in parameterRangeSelectOptions"
              :key="'rg-' + item.value"
              :label="item.label"
              :value="item.value" />
          </el-select>
          <span v-else-if="parameterRangeSelectOptions.length === 1">{{ parameterRangeSelectOptions[0].label }}</span>
          <div v-if="!parameterRangeSelectOptions.length" class="form-hint">当前版本没有联合参数区间。</div>
        </el-form-item>
        <el-row>
          <el-col :span="8">
            <el-form-item>
              <template #label><span  :title="fieldTip('heavyCount')">重车列数</span></template>
              <el-input-number v-model="form.heavyCount" :min="1" :max="40" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item>
              <template #label><span  :title="fieldTip('emptyCount')">空车列数</span></template>
              <el-input-number v-model="form.emptyCount" :min="1" :max="40" />
            </el-form-item>
          </el-col>
        </el-row>
        <div class="form-hint form-hint-block">在固定重空列数上扫描车重、储能等参数区间。发车间隔和结算步长用算法默认。</div>
      </template>

      <el-form-item>
        <el-button type="primary" :loading="saving" :disabled="form.runType === 'storage_planning' && (presetLoading || !planningReady)" @click="submit">提交任务</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>
<script>
import { createRun, listVersions, listVersionFiles, getParameterPreset } from '@/api/carbon/energy'
import {
  applyParameterOverlay,
  applyRollingDeviceDemo,
  applyRunTypeDefaults,
  applyStorageDevices,
  applyVersionFileHints,
  coerceFormFilePaths,
  buildEnergyParameters,
  createEmptyEnergyForm,
  DISTURBANCE_FILE_HINTS,
  emptyStorageDevice,
  matchVersionFiles,
  PARAMETER_RANGE_FILE_HINTS,
  timetableFilePathsFrom,
  validateEnergyForm,
  ENERGY_RUN_TYPES,
  energyFieldTip,
  energyRunTypeTip,
  versionFileDisplayName,
  versionFileHint,
  versionFileOptions,
  versionFileUsedByRun,
  versionOptionLabel
} from '@/utils/energyParameters'

export default {
  name: 'CarbonEnergyCreate',
  data() {
    return {
      saving: false,
      versions: [],
      files: [],
      versionKey: '',
      form: createEmptyEnergyForm(),
      presetRunId: '',
      presetQueuedAt: '',
      planningReady: false, planningIssues: [], planningPolicyOptions: [], scenarioSetOptions: [],
      presetLoading: false,
      presetToken: 0,
      userEdited: false
    }
  },
  computed: {
    needsTimetable() {
      return this.form.runType === 'timetable_audit' || this.form.runType === 'timetable_optimization'
    },
    filePaths() {
      return (this.files || []).map(item => item.relativePath).filter(Boolean)
    },
    versionFileRows() {
      const runType = this.form.runType
      const rollingSource = this.form.rollingSource
      return (this.files || []).filter(item => versionFileUsedByRun(item.relativePath, runType, rollingSource)).map(item => ({
        relativePath: item.relativePath,
        displayPath: versionFileDisplayName(item.relativePath),
        hint: versionFileHint(item.relativePath)
      }))
    },
    timetableFilePaths() {
      return timetableFilePathsFrom(this.filePaths)
    },
    disturbanceFilePaths() {
      return matchVersionFiles(this.filePaths, DISTURBANCE_FILE_HINTS)
    },
    parameterRangeFilePaths() {
      return matchVersionFiles(this.filePaths, PARAMETER_RANGE_FILE_HINTS)
    },
    timetableSelectOptions() {
      return versionFileOptions(this.timetableFilePaths)
    },
    disturbanceSelectOptions() {
      return versionFileOptions(this.disturbanceFilePaths)
    },
    parameterRangeSelectOptions() {
      return versionFileOptions(this.parameterRangeFilePaths)
    },
    runTypes() {
      return ENERGY_RUN_TYPES
    },
    typeHint() {
      return energyRunTypeTip(this.form.runType)
    },
    presetHint() {
      if (this.presetLoading) {
        return '正在读取该版本已有值和算法默认…'
      }
      if (this.presetRunId) {
        return '已填入算法默认，并套用上次任务 ' + this.presetRunId + '（' + (this.presetQueuedAt || '-') + '）。改数字即覆盖，不必重填全部。'
      }
      if (this.form.projectCode) {
        return '已填入算法默认，并套用当前数据版本里能找到的文件/储能。改数字即覆盖。'
      }
      return '已填入该任务的算法默认。先选数据版本，再自动套用版本文件和上次同类型任务。'
    }
  },
  created() {
    listVersions().then(res => {
      this.versions = res.data || []
    }).catch(() => this.$message.error('加载数据版本失败'))
    this.reloadPreset(false)
  },
  methods: {
    versionLabel(item) {
      return versionOptionLabel(item)
    },
    fieldTip(key) {
      return energyFieldTip(key)
    },
    onVersionChange(value) {
      const slash = value.indexOf('/')
      this.form.projectCode = value.slice(0, slash)
      this.form.versionCode = value.slice(slash + 1)
      this.reloadPreset(true)
    },
    onRunTypeChange() {
      this.reloadPreset(true)
    },
    onUserEdit() {
      this.userEdited = true
    },
    reloadPreset(useLastRun) {
      const token = this.presetToken + 1
      this.presetToken = token
      this.userEdited = false
      applyRunTypeDefaults(this.form)
      this.planningReady = false
      this.planningIssues = []
      this.planningPolicyOptions = []
      this.scenarioSetOptions = []
      this.presetRunId = ''
      this.presetQueuedAt = ''
      if (!this.form.projectCode || !this.form.versionCode) {
        return
      }
      this.presetLoading = true
      listVersionFiles({ projectCode: this.form.projectCode, versionCode: this.form.versionCode }).then(res => {
        if (token !== this.presetToken) {
          return
        }
        this.files = res.data || []
        applyVersionFileHints(this.form, this.filePaths)
        return getParameterPreset({
          projectCode: this.form.projectCode,
          versionCode: this.form.versionCode,
          runType: this.form.runType
        })
      }).then(res => {
        if (!res || token !== this.presetToken) {
          return
        }
        const preset = res.data || {}
        applyStorageDevices(this.form, preset.storageDevices || [])
        if (useLastRun && preset.lastParameters && !this.userEdited) {
          applyParameterOverlay(this.form, preset.lastParameters)
          this.presetRunId = preset.lastRunId || ''
          this.presetQueuedAt = preset.lastQueuedAt || ''
        }
        this.planningReady = !!preset.planningReady
        this.planningIssues = preset.planningIssues || []
        this.planningPolicyOptions = preset.planningPolicyOptions || []
        this.scenarioSetOptions = preset.scenarioSetOptions || []
        if (!this.planningPolicyOptions.some(item => item.code === this.form.planningPolicyCode)) this.form.planningPolicyCode = (this.planningPolicyOptions[0] || {}).code || ''
        if (!this.scenarioSetOptions.some(item => item.code === this.form.scenarioSetCode)) this.form.scenarioSetCode = (this.scenarioSetOptions[0] || {}).code || ''
        coerceFormFilePaths(this.form, this.filePaths)
        this.form.emptyMassTons = undefined
      }).catch(() => {
        if (token !== this.presetToken) {
          return
        }
        this.files = this.files || []
        applyVersionFileHints(this.form, this.filePaths)
      }).finally(() => {
        if (token === this.presetToken) {
          this.presetLoading = false
        }
      })
    },
    addDevice() {
      this.form.storageDevices.push(emptyStorageDevice())
    },
    removeDevice(index) {
      this.form.storageDevices.splice(index, 1)
      if (!this.form.storageDevices.length) {
        this.form.storageDevices.push(emptyStorageDevice())
      }
    },
    fillRollingDeviceDemo() {
      applyRollingDeviceDemo(this.form)
    },
    submit() {
      if (this.form.runType === 'storage_planning' && (this.presetLoading || !this.planningReady)) {
        this.$message.error(this.planningIssues.join('；') || '请补齐规划数据后提交')
        return
      }
      const error = validateEnergyForm(this.form)
      if (error) {
        this.$message.error(error)
        return
      }
      const parameters = buildEnergyParameters(this.form)
      this.saving = true
      const loading = this.$loading({
        lock: true,
        text: '正在提交任务并开始计算…',
        spinner: 'el-icon-loading',
        background: 'rgba(255, 255, 255, 0.72)'
      })
      createRun({
        projectCode: this.form.projectCode,
        versionCode: this.form.versionCode,
        runType: this.form.runType,
        parameters,
        idempotencyKey: Date.now() + '-' + this.form.runType
      }).then(res => {
        const runId = (res.data && (res.data.run_id || res.data.runId)) || ''
        if (!runId) {
          this.$message.error('未返回任务编号')
          return
        }
        this.$message.success('已提交，正在计算')
        this.$router.push('/carbon/energy/runs/' + runId)
      }).catch(() => {
        this.$message.error('提交任务失败')
      }).finally(() => {
        this.saving = false
        loading.close()
      })
    }
  }
}
</script>
<style scoped>
.type-hint {
  margin: 0 0 16px 168px;
  width: calc(100% - 168px);
}
.form-hint,
.inline-hint {
  color: #909399;
  font-size: 12px;
  line-height: 1.4;
}
.inline-hint {
  margin-left: 8px;
}
.form-hint-block {
  margin: -4px 0 16px 168px;
}
</style>
