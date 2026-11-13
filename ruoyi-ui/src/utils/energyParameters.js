export const ENERGY_RUN_TYPES = [
  { value: 'storage_planning', label: '储能选址与定容规划', tip: '固定运行图，按候选站点和储能技术计算离散建设方案。需要完整的储能规划数据。' },
  { value: 'timetable_audit', label: '运行图审查', tip: '只评价当前运行图，不改时刻。选好版本后直接提交即可。' },
  { value: 'timetable_optimization', label: '运行图优化', tip: '在现有运行图上小幅平移或延长停站。只需设能动多少分钟和搜索力度。' },
  { value: 'dispatch', label: '重空调度', tip: '按重空列数重排发车顺序和储能使用。搜索力度决定算多久。' },
  { value: 'rolling_rescheduling', label: '滚动重调度', tip: '按已经发生的晚点或当前储能状态，再排一截近期计划。' },
  { value: 'joint_parameter_robustness', label: '联合参数稳健性', tip: '固定重空列数，扫描车重、储能等参数组合是否仍然可行。' }
]

export function energyRunTypeLabel(value) {
  const matched = ENERGY_RUN_TYPES.find(function(item) { return item.value === value })
  return matched ? matched.label : (value || '')
}

export function energyRunTypeTip(value) {
  const matched = ENERGY_RUN_TYPES.find(function(item) { return item.value === value })
  return matched ? matched.tip : ''
}

export const ENERGY_FIELD_TIPS = {
  timetableRelativePath: '这次计算用的列车到发时刻。版本里只有一张时直接显示，有多张时再选。',
  maxShiftMin: '每列车的到发时刻最多能提前或推后多少分钟。填 0 表示不平移。',
  maxDwellExtensionMin: '中间站停站最多能再加多少分钟。填 0 表示不延长停站。',
  searchIntensity: '只影响算多久，不改变允许改动的范围。快：少试几套；标准：日常使用；细：更慢、试得更仔细。',
  heavyCount: '这次要安排的重车列数。',
  emptyCount: '这次要安排的空车列数。',
  objectivePriority: '节能优先少耗电，成本优先少花钱，均衡两边一起看。',
  rollingSource: '不附加：只按现有计划重排。历史扰动回放：用已经发生的晚点或限速。分设备当前状态：按各储能现在的电量和功率。',
  disturbanceHistoryRelativePath: '选用哪一份已经发生的晚点、限速或储能状态记录。',
  storageDevices: '按每台储能填写现在的电量、是否可用，以及还能充、放多少功率。',
  storageSectionId: '储能区段编号，要和版本数据里的区段对应，例如 storage_section_1:K145-K164。',
  socKwh: '这台储能现在还剩多少电，单位是千瓦时。',
  available: '关掉表示这台储能当前不能参与充放电。',
  maxChargePowerKw: '这台储能当前允许的最大充电功率，单位是千瓦。',
  maxDischargePowerKw: '这台储能当前允许的最大放电功率，单位是千瓦。',
  parameterRangesRelativePath: '车重、储能等参数的上下限。系统按这些范围检查组合是否仍然可行。'
}

export function energyFieldTip(key) {
  return ENERGY_FIELD_TIPS[key] || ''
}

export const DEMO_STORAGE_DEVICES = [
  {
    storage_section_id: 'storage_section_1:K145-K164',
    soc_kwh: 2500,
    available: true,
    max_charge_power_kw: 5000,
    max_discharge_power_kw: 5000
  },
  {
    storage_section_id: 'storage_section_2:K164-K200.7',
    soc_kwh: 2500,
    available: false,
    max_charge_power_kw: 0,
    max_discharge_power_kw: 0
  }
]

export const PARAMETER_FIELD_MAP = {
  planning_policy_code: 'planningPolicyCode', scenario_set_code: 'scenarioSetCode', search_mode: 'searchMode',
  max_levels_per_dimension: 'maxLevelsPerDimension', refinement_shortlist_size: 'refinementShortlistSize',
  timetable_relative_path: 'timetableRelativePath',
  parameter_ranges_relative_path: 'parameterRangesRelativePath',
  disturbance_history_relative_path: 'disturbanceHistoryRelativePath',
  energy_scenario: 'energyScenario',
  objective_mode: 'objectiveMode',
  objective_priority: 'objectivePriority',
  search_profile: 'searchProfile',
  search_method: 'searchMethod',
  population_size: 'populationSize',
  generations: 'generations',
  seed: 'seed',
  heavy_count: 'heavyCount',
  empty_count: 'emptyCount',
  baseline_phase_s: 'baselinePhaseS',
  baseline_heavy_headway_s: 'baselineHeavyHeadwayS',
  baseline_empty_headway_s: 'baselineEmptyHeadwayS',
  min_depart_gap_s: 'minDepartGapS',
  horizon_s: 'horizonS',
  execute_window_s: 'executeWindowS',
  settlement_step_s: 'settlementStepS',
  wasted_energy_penalty_per_kwh: 'wastedEnergyPenaltyPerKwh',
  search_min_headway_s: 'searchMinHeadwayS',
  search_max_headway_s: 'searchMaxHeadwayS',
  search_max_phase_s: 'searchMaxPhaseS',
  search_max_hold_s: 'searchMaxHoldS',
  search_max_storage_align_shift_s: 'searchMaxStorageAlignShiftS',
  empty_mass_tons: 'emptyMassTons',
  disable_storage_preset_search: 'disableStoragePresetSearch',
  disable_energy_observability: 'disableEnergyObservability',
  mode: 'mode',
  max_shift_min: 'maxShiftMin',
  step_min: 'stepMin',
  max_dwell_extension_min: 'maxDwellExtensionMin',
  max_candidates: 'maxCandidates',
  crossover_rate: 'crossoverRate',
  mutation_rate: 'mutationRate',
  max_safety_retries: 'maxSafetyRetries',
  manual_after_withheld: 'manualAfterWithheld',
  disable_safety_retry: 'disableSafetyRetry',
  disable_recovery: 'disableRecovery'
}

export function emptyStorageDevice() {
  return {
    storage_section_id: '',
    soc_kwh: 0,
    available: true,
    max_charge_power_kw: null,
    max_discharge_power_kw: null
  }
}

function cloneStorageDevices(rows) {
  return (rows || []).map(function(item) {
    return Object.assign({}, item)
  })
}

export const RUN_TYPE_DEFAULTS = {
  storage_planning: { planningPolicyCode: '', scenarioSetCode: '', searchMode: 'coarse', maxLevelsPerDimension: 2, settlementStepS: 60, refinementShortlistSize: 3 },
  timetable_audit: {
    timetableRelativePath: 'platform/运行图.xlsx',
    strictVisualizations: false
  },
  timetable_optimization: {
    timetableRelativePath: 'platform/运行图.xlsx',
    searchIntensity: 'standard',
    mode: 'nsga2',
    maxShiftMin: 30,
    stepMin: 5,
    maxDwellExtensionMin: 15,
    maxCandidates: 120,
    populationSize: 16,
    generations: 6,
    crossoverRate: 0.8,
    mutationRate: 0.12,
    seed: 42,
    strictVisualizations: false
  },
  dispatch: {
    energyScenario: 'storage_no_direct',
    objectiveMode: 'balanced',
    objectivePriority: 'energy_first',
    searchMethod: 'nsga2',
    searchIntensity: 'standard',
    searchProfile: 'standard',
    populationSize: 12,
    generations: 4,
    seed: 101,
    heavyCount: 3,
    emptyCount: 3,
    baselinePhaseS: 2600,
    baselineHeavyHeadwayS: 3300,
    baselineEmptyHeadwayS: 2700,
    minDepartGapS: 300,
    horizonS: 14400,
    executeWindowS: 1800,
    settlementStepS: 10,
    wastedEnergyPenaltyPerKwh: 0,
    searchMinHeadwayS: 2400,
    searchMaxHeadwayS: 4200,
    searchMaxPhaseS: 5400,
    searchMaxHoldS: 900,
    searchMaxStorageAlignShiftS: 1200,
    emptyMassTons: null,
    disableStoragePresetSearch: false,
    disableEnergyObservability: false
  },
  rolling_rescheduling: {
    searchIntensity: 'quick',
    populationSize: 2,
    generations: 1,
    seed: 20260907,
    maxSafetyRetries: 1,
    manualAfterWithheld: 2,
    disableSafetyRetry: false,
    disableRecovery: false,
    rollingSource: 'none',
    disturbanceHistoryRelativePath: '',
    storageDevices: [emptyStorageDevice()]
  },
  joint_parameter_robustness: {
    parameterRangesRelativePath: 'platform/联合参数区间.json',
    heavyCount: 2,
    emptyCount: 2,
    baselineHeavyHeadwayS: 3300,
    baselineEmptyHeadwayS: 3300,
    baselinePhaseS: 840,
    settlementStepS: 10
  }
}

export function createEmptyEnergyForm() {
  const form = {
    projectCode: '',
    versionCode: '',
    runType: 'timetable_audit',
    rollingSource: 'none',
    searchIntensity: 'standard',
    storageDevices: [emptyStorageDevice()]
  }
  Object.keys(RUN_TYPE_DEFAULTS).forEach(function(runType) {
    const defaults = RUN_TYPE_DEFAULTS[runType]
    Object.keys(defaults).forEach(function(key) {
      if (key === 'storageDevices') {
        return
      }
      if (!Object.prototype.hasOwnProperty.call(form, key)) {
        form[key] = defaults[key]
      }
    })
  })
  applyRunTypeDefaults(form)
  return form
}

export const SEARCH_INTENSITY_PRESETS = {
  timetable_optimization: {
    quick: { populationSize: 8, generations: 3 },
    standard: { populationSize: 16, generations: 6 },
    fine: { populationSize: 30, generations: 10 }
  },
  dispatch: {
    quick: { populationSize: 4, generations: 1, searchProfile: 'quick' },
    standard: { populationSize: 12, generations: 4, searchProfile: 'standard' },
    fine: { populationSize: 24, generations: 8, searchProfile: 'large' }
  },
  rolling_rescheduling: {
    quick: { populationSize: 2, generations: 1 },
    standard: { populationSize: 4, generations: 2 },
    fine: { populationSize: 8, generations: 4 }
  }
}

const SOLVER_OVERLAY_SKIP = {
  population_size: true,
  generations: true,
  seed: true,
  crossover_rate: true,
  mutation_rate: true,
  mode: true,
  step_min: true,
  max_candidates: true,
  search_profile: true,
  search_method: true,
  energy_scenario: true,
  objective_mode: true,
  settlement_step_s: true,
  baseline_phase_s: true,
  baseline_heavy_headway_s: true,
  baseline_empty_headway_s: true,
  min_depart_gap_s: true,
  horizon_s: true,
  execute_window_s: true,
  wasted_energy_penalty_per_kwh: true,
  search_min_headway_s: true,
  search_max_headway_s: true,
  search_max_phase_s: true,
  search_max_hold_s: true,
  search_max_storage_align_shift_s: true,
  disable_storage_preset_search: true,
  disable_energy_observability: true,
  max_safety_retries: true,
  manual_after_withheld: true,
  disable_safety_retry: true,
  disable_recovery: true
}

export function searchIntensityValues(form) {
  const runType = form && form.runType
  const intensity = (form && form.searchIntensity) || 'standard'
  const byType = SEARCH_INTENSITY_PRESETS[runType] || {}
  return byType[intensity] || byType.standard || {}
}

export function applySearchIntensity(form) {
  const values = searchIntensityValues(form)
  Object.keys(values).forEach(function(key) {
    form[key] = values[key]
  })
  return form
}

export function applyRunTypeDefaults(form) {
  const defaults = RUN_TYPE_DEFAULTS[form.runType] || {}
  Object.keys(defaults).forEach(function(key) {
    const value = defaults[key]
    form[key] = Array.isArray(value) ? cloneStorageDevices(value) : value
  })
  applySearchIntensity(form)
  return form
}

export const TIMETABLE_FILE_HINTS = ['运行图', 'running_diagram', 'timetable.csv', 'timetable.xlsx']
export const DISTURBANCE_FILE_HINTS = ['滚动扰动', 'historical_disturbance', 'disturbance_replay']
export const PARAMETER_RANGE_FILE_HINTS = ['联合参数', 'joint_parameter_ranges']

function normalizeVersionPaths(paths) {
  return (paths || []).map(function(item) {
    return String(item || '').replace(/\\/g, '/')
  }).filter(Boolean)
}

export function basenameVersionPath(path) {
  const parts = String(path || '').replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || String(path || '')
}

export function stripVersionFileExtension(name) {
  return String(name || '').replace(/\.(xlsx|xls|csv|json)$/i, '')
}

export const DATA_STATUS_LABELS = {
  official: '正式',
  derived_from_official: '由正式派生',
  planning_placeholder: '规划占位',
  synthetic: '合成'
}

export function versionDisplayName(item) {
  const stored = String((item && item.versionName) || '').trim()
  const code = String((item && item.versionCode) || '').trim()
  if (stored && stored !== code) {
    return stored
  }
  const match = code.match(/^v(\d+)$/i)
  if (match) {
    return '第' + Number(match[1]) + '版'
  }
  return stored || code
}

export function versionOptionLabel(item) {
  const project = String((item && (item.projectName || item.projectCode)) || '').trim()
  const version = versionDisplayName(item)
  const status = DATA_STATUS_LABELS[(item && item.dataStatus)] || (item && item.dataStatus) || ''
  if (status) {
    return project + ' / ' + version + '（' + status + '）'
  }
  return project + ' / ' + version
}

export function versionFileDisplayName(path) {
  return stripVersionFileExtension(basenameVersionPath(path))
}

export function versionFileOptionLabel(path, matchedPaths) {
  const name = versionFileDisplayName(path)
  const sameKind = (matchedPaths || []).filter(function(item) {
    return versionFileDisplayName(item) === name
  })
  if (sameKind.length > 1) {
    return name + '（' + stripVersionFileExtension(basenameVersionPath(path)) + '）'
  }
  return name
}

export function versionFileOptions(paths) {
  const list = normalizeVersionPaths(paths)
  return list.map(function(value) {
    return {
      value: value,
      label: versionFileOptionLabel(value, list)
    }
  })
}

export function isTimetableFilePath(path) {
  const posix = String(path || '').replace(/\\/g, '/')
  const lower = posix.toLowerCase()
  const file = basenameVersionPath(posix).toLowerCase()
  if (lower.indexOf('running_diagram') >= 0 || file.indexOf('运行图') >= 0 || file === 'timetable.csv' || file === 'timetable.xlsx') {
    return true
  }
  const slash = posix.lastIndexOf('/')
  const parent = slash >= 0 ? posix.slice(0, slash) : ''
  return parent === 'platform' && file.endsWith('.xlsx')
}

const VERSION_FILE_HINTS = {
  '运行图': '各列车沿途到发时刻',
  '时刻表': '各列车沿途到发时刻',
  running_diagram: '各列车沿途到发时刻',
  timetable: '各列车沿途到发时刻',
  '滚动扰动回放': '晚点、限速和储能当前状态',
  historical_disturbance_replay: '晚点、限速和储能当前状态',
  '联合参数区间': '车重、储能等参数的扫描范围',
  joint_parameter_ranges: '车重、储能等参数的扫描范围',
  '列车参数': '重车、空车质量和牵引制动',
  trains: '重车、空车质量和牵引制动',
  '车站': '车站名称和里程位置',
  stations: '车站名称和里程位置',
  '车站主数据': '线路图中的车站主表',
  pdf_station_master: '线路图中的车站主表',
  '车站_范围外': '未纳入本线模型的车站',
  pdf_station_out_of_scope: '未纳入本线模型的车站',
  '区间': '区间起终点、坡度和限速',
  segments: '区间起终点、坡度和限速',
  '坡度': '沿线坡度变化',
  gradients: '沿线坡度变化',
  '曲线': '曲线半径和弯道位置',
  curves: '曲线半径和弯道位置',
  '线路参数': '全线长度、最高速度等线路概况',
  route_metadata: '全线长度、最高速度等线路概况',
  '储能参数': '储能容量、效率和充放功率',
  battery: '储能容量、效率和充放功率',
  '储能区段': '储能安装的起终点里程',
  energy_transfer_zones: '储能安装的起终点里程',
  '储能设备': '各储能设备的额定参数',
  storage_devices: '各储能设备的额定参数',
  storage_candidate_sites: '储能候选站点与供电臂接入范围',
  '储能候选站点': '储能候选站点与供电臂接入范围',
  storage_technologies: '储能技术参数与经济成本',
  '储能技术': '储能技术参数与经济成本',
  storage_site_technology_options: '站点与技术的允许配置',
  '储能站点技术配置': '站点与技术的允许配置',
  storage_planning_scenarios: '规划场景集与固定运行图',
  '储能规划场景': '规划场景集与固定运行图',
  storage_planning_policy: '规划策略与投资预算',
  '储能规划策略': '规划策略与投资预算',
  '供电臂': '供电臂起终点和电气能力',
  power_arm_intervals: '供电臂起终点和电气能力',
  '闭塞': '信号闭塞分区位置和能力',
  signaling_blocks: '信号闭塞分区位置和能力',
  '车站能力': '车站股道和咽喉能同时占用的列数',
  station_resources: '车站股道和咽喉能同时占用的列数',
  '资源规则': '车站占用时间等资源规则',
  resource_config: '车站占用时间等资源规则',
  '追踪间隔': '两列车之间的最小间隔',
  headway_constraints: '两列车之间的最小间隔',
  '技术作业时分': '车站装车、对位等作业时间',
  technical_operation_times: '车站装车、对位等作业时间',
  '技术作业时分_范围外': '未纳入本线模型的作业时分',
  technical_operation_times_out_of_scope: '未纳入本线模型的作业时分',
  '作业适用范围': '作业时分适用的车型和方向',
  station_operation_assignments: '作业时分适用的车型和方向',
  '作业条件': '运行作业条件配置',
  operating_conditions: '运行作业条件配置',
  '编组模式': '列车编组方式',
  train_formation_modes_2025: '列车编组方式',
  '能量标定': '能耗计算标定系数',
  energy_calibration_factors: '能耗计算标定系数',
  '电表标定样本': '电表标定原始样本',
  smart_meter_calibration_samples: '电表标定原始样本',
  '电表标定摘要': '电表标定结果摘要',
  smart_meter_calibration_samples_summary: '电表标定结果摘要',
  '电表区间样本': '电表区间用电样本',
  smart_meter_representative_interval_samples: '电表区间用电样本',
  '构建摘要': '本版本数据如何生成的摘要',
  build_summary: '本版本数据如何生成的摘要',
  DATASET_README: '本版本数据的文字说明'
}

export function versionFileHint(path) {
  const posix = String(path || '').replace(/\\/g, '/')
  const stem = stripVersionFileExtension(basenameVersionPath(posix))
  if (VERSION_FILE_HINTS[stem]) {
    return VERSION_FILE_HINTS[stem]
  }
  if (VERSION_FILE_HINTS[stem.toLowerCase()]) {
    return VERSION_FILE_HINTS[stem.toLowerCase()]
  }
  if (stem.indexOf('DATASET_README') >= 0 || stem.toLowerCase().indexOf('dataset_readme') >= 0) {
    return VERSION_FILE_HINTS.DATASET_README
  }
  if (isTimetableFilePath(posix)) {
    return VERSION_FILE_HINTS['运行图']
  }
  return '该版本中的补充数据'
}

const CORE_VERSION_FILE_STEMS = {
  '列车参数': true,
  trains: true,
  '车站': true,
  stations: true,
  '区间': true,
  segments: true,
  '坡度': true,
  gradients: true,
  '曲线': true,
  curves: true,
  '线路参数': true,
  route_metadata: true,
  '储能参数': true,
  battery: true,
  '储能区段': true,
  energy_transfer_zones: true,
  '储能设备': true,
  storage_devices: true,
  '供电臂': true,
  power_arm_intervals: true,
  '闭塞': true,
  signaling_blocks: true,
  '车站能力': true,
  station_resources: true,
  '资源规则': true,
  resource_config: true,
  '追踪间隔': true,
  headway_constraints: true,
  '技术作业时分': true,
  technical_operation_times: true,
  '作业适用范围': true,
  station_operation_assignments: true,
  '作业条件': true,
  operating_conditions: true,
  '编组模式': true,
  train_formation_modes_2025: true
}

function pathHasHint(path, hints) {
  const lower = String(path || '').replace(/\\/g, '/').toLowerCase()
  return (hints || []).some(function(key) {
    return lower.indexOf(String(key).toLowerCase()) >= 0
  })
}

export function isDisturbanceFilePath(path) {
  return pathHasHint(path, DISTURBANCE_FILE_HINTS)
}

export function isParameterRangeFilePath(path) {
  return pathHasHint(path, PARAMETER_RANGE_FILE_HINTS)
}

export function isCoreSolverFilePath(path) {
  const stem = stripVersionFileExtension(basenameVersionPath(path))
  return !!(CORE_VERSION_FILE_STEMS[stem] || CORE_VERSION_FILE_STEMS[stem.toLowerCase()])
}

export function versionFileUsedByRun(path, runType, rollingSource) {
  if (/储能候选站点|储能技术|储能站点技术配置|储能规划场景|储能规划策略|storage_candidate_sites|storage_technologies|storage_site_technology_options|storage_planning_scenarios|storage_planning_policy/.test(path)) return runType === 'storage_planning'
  if (runType === 'storage_planning' && isTimetableFilePath(path)) return true
  if (isTimetableFilePath(path)) {
    return runType === 'timetable_audit' || runType === 'timetable_optimization'
  }
  if (isDisturbanceFilePath(path)) {
    return runType === 'rolling_rescheduling' && rollingSource === 'replay'
  }
  if (isParameterRangeFilePath(path)) {
    return runType === 'joint_parameter_robustness'
  }
  return isCoreSolverFilePath(path)
}

export function matchVersionFiles(paths, keywords) {
  const list = normalizeVersionPaths(paths)
  const keys = (keywords || []).map(function(item) {
    return String(item).toLowerCase()
  }).filter(Boolean)
  return list.filter(function(path) {
    const lower = path.toLowerCase()
    return keys.some(function(key) {
      return lower.indexOf(key) >= 0
    })
  })
}

export function timetableFilePathsFrom(paths) {
  return normalizeVersionPaths(paths).filter(isTimetableFilePath)
}

export function pickVersionFile(paths, keywords, fallback) {
  const list = normalizeVersionPaths(paths)
  for (let i = 0; i < (keywords || []).length; i++) {
    const key = String(keywords[i]).toLowerCase()
    const hit = list.find(function(path) {
      return path.toLowerCase().indexOf(key) >= 0
    })
    if (hit) {
      return hit
    }
  }
  return fallback
}

export function pickTimetableFile(paths, fallback) {
  const matched = timetableFilePathsFrom(paths)
  const preferred = pickVersionFile(matched, TIMETABLE_FILE_HINTS, '')
  return preferred || matched[0] || fallback
}

export function applyVersionFileHints(form, paths) {
  if (form.runType === 'timetable_audit' || form.runType === 'timetable_optimization') {
    form.timetableRelativePath = pickTimetableFile(paths, form.timetableRelativePath)
  }
  if (form.runType === 'joint_parameter_robustness') {
    form.parameterRangesRelativePath = pickVersionFile(
      paths,
      PARAMETER_RANGE_FILE_HINTS,
      form.parameterRangesRelativePath
    )
  }
  if (form.runType === 'rolling_rescheduling') {
    const replay = pickVersionFile(paths, DISTURBANCE_FILE_HINTS, '')
    if (replay) {
      form.disturbanceHistoryRelativePath = replay
    }
  }
  return form
}

export function coerceFormFilePaths(form, paths) {
  const list = normalizeVersionPaths(paths)
  if (form.runType === 'timetable_audit' || form.runType === 'timetable_optimization') {
    const current = String(form.timetableRelativePath || '').replace(/\\/g, '/')
    if (list.indexOf(current) < 0) {
      form.timetableRelativePath = pickTimetableFile(list, form.timetableRelativePath)
    }
  }
  if (form.runType === 'joint_parameter_robustness') {
    const current = String(form.parameterRangesRelativePath || '').replace(/\\/g, '/')
    if (list.indexOf(current) < 0) {
      form.parameterRangesRelativePath = pickVersionFile(list, PARAMETER_RANGE_FILE_HINTS, form.parameterRangesRelativePath)
    }
  }
  if (form.runType === 'rolling_rescheduling') {
    const current = String(form.disturbanceHistoryRelativePath || '').replace(/\\/g, '/')
    if (current && list.indexOf(current) < 0) {
      const replay = pickVersionFile(list, DISTURBANCE_FILE_HINTS, '')
      if (replay) {
        form.disturbanceHistoryRelativePath = replay
      }
    }
  }
  return form
}

export function normalizeStorageDevices(rows) {
  return (rows || []).map(function(row) {
    return {
      storage_section_id: String(row.storage_section_id || row.storageSectionId || '').trim(),
      soc_kwh: Number(row.soc_kwh != null ? row.soc_kwh : row.socKwh),
      available: row.available === true || row.available === 1 || row.available === '1',
      max_charge_power_kw: row.max_charge_power_kw != null ? Number(row.max_charge_power_kw) : (row.maxChargePowerKw != null ? Number(row.maxChargePowerKw) : null),
      max_discharge_power_kw: row.max_discharge_power_kw != null ? Number(row.max_discharge_power_kw) : (row.maxDischargePowerKw != null ? Number(row.maxDischargePowerKw) : null)
    }
  }).filter(function(item) {
    return item.storage_section_id
  })
}

export function applyStorageDevices(form, rows) {
  const devices = normalizeStorageDevices(rows)
  form.storageDevices = devices.length ? devices : [emptyStorageDevice()]
  return form
}

export function applyParameterOverlay(form, parameters) {
  if (!parameters || typeof parameters !== 'object') {
    return form
  }
  Object.keys(PARAMETER_FIELD_MAP).forEach(function(key) {
    if (!Object.prototype.hasOwnProperty.call(parameters, key) || parameters[key] == null) {
      return
    }
    if (key === 'empty_mass_tons' || SOLVER_OVERLAY_SKIP[key]) {
      return
    }
    form[PARAMETER_FIELD_MAP[key]] = parameters[key]
  })
  if (Array.isArray(parameters.storage_devices) && parameters.storage_devices.length) {
    applyStorageDevices(form, parameters.storage_devices)
    form.rollingSource = 'devices'
  } else if (parameters.disturbance_history_relative_path) {
    form.rollingSource = 'replay'
  }
  return form
}

function setIfFilled(target, key, value) {
  if (value === null || value === undefined || value === '') {
    return
  }
  target[key] = value
}

function setEmptyMassOverride(target, value) {
  if (value === null || value === undefined || value === '') {
    return
  }
  const numeric = Number(value)
  // 数字框曾把空值收成 0/1；演示空车允许区间是 2160–4320 t。
  if (!Number.isFinite(numeric) || numeric < 1000) {
    return
  }
  target.empty_mass_tons = numeric
}

function setBoolIfTrue(target, key, value) {
  if (value === true) {
    target[key] = true
  }
}

function normalizeDevice(row) {
  if (!row || !String(row.storage_section_id || '').trim()) {
    return null
  }
  const device = {
    storage_section_id: String(row.storage_section_id).trim(),
    soc_kwh: Number(row.soc_kwh),
    available: row.available !== false
  }
  if (row.max_charge_power_kw !== null && row.max_charge_power_kw !== undefined && row.max_charge_power_kw !== '') {
    device.max_charge_power_kw = Number(row.max_charge_power_kw)
  }
  if (row.max_discharge_power_kw !== null && row.max_discharge_power_kw !== undefined && row.max_discharge_power_kw !== '') {
    device.max_discharge_power_kw = Number(row.max_discharge_power_kw)
  }
  return device
}

export function buildEnergyParameters(form) {
  const parameters = {}
  const runType = form.runType
  if (runType === 'timetable_audit' || runType === 'timetable_optimization') {
    parameters.timetable_relative_path = String(form.timetableRelativePath || '').trim()
  }
  if (runType === 'timetable_optimization') {
    const intensity = searchIntensityValues(form)
    setIfFilled(parameters, 'mode', form.mode || 'nsga2')
    setIfFilled(parameters, 'population_size', intensity.populationSize)
    setIfFilled(parameters, 'generations', intensity.generations)
    setIfFilled(parameters, 'seed', form.seed)
    setIfFilled(parameters, 'max_shift_min', form.maxShiftMin)
    setIfFilled(parameters, 'step_min', form.stepMin)
    setIfFilled(parameters, 'max_dwell_extension_min', form.maxDwellExtensionMin)
    setIfFilled(parameters, 'max_candidates', form.maxCandidates)
    setIfFilled(parameters, 'crossover_rate', form.crossoverRate)
    setIfFilled(parameters, 'mutation_rate', form.mutationRate)
  }
  if (runType === 'dispatch') {
    const intensity = searchIntensityValues(form)
    parameters.energy_scenario = form.energyScenario || 'storage_no_direct'
    setIfFilled(parameters, 'objective_mode', form.objectiveMode)
    setIfFilled(parameters, 'objective_priority', form.objectivePriority)
    setIfFilled(parameters, 'search_profile', intensity.searchProfile || form.searchProfile)
    setIfFilled(parameters, 'search_method', form.searchMethod)
    setIfFilled(parameters, 'population_size', intensity.populationSize)
    setIfFilled(parameters, 'generations', intensity.generations)
    setIfFilled(parameters, 'seed', form.seed)
    setIfFilled(parameters, 'heavy_count', form.heavyCount)
    setIfFilled(parameters, 'empty_count', form.emptyCount)
    setIfFilled(parameters, 'baseline_phase_s', form.baselinePhaseS)
    setIfFilled(parameters, 'baseline_heavy_headway_s', form.baselineHeavyHeadwayS)
    setIfFilled(parameters, 'baseline_empty_headway_s', form.baselineEmptyHeadwayS)
    setIfFilled(parameters, 'min_depart_gap_s', form.minDepartGapS)
    setIfFilled(parameters, 'horizon_s', form.horizonS)
    setIfFilled(parameters, 'execute_window_s', form.executeWindowS)
    setIfFilled(parameters, 'settlement_step_s', form.settlementStepS)
    setIfFilled(parameters, 'wasted_energy_penalty_per_kwh', form.wastedEnergyPenaltyPerKwh)
    setIfFilled(parameters, 'search_min_headway_s', form.searchMinHeadwayS)
    setIfFilled(parameters, 'search_max_headway_s', form.searchMaxHeadwayS)
    setIfFilled(parameters, 'search_max_phase_s', form.searchMaxPhaseS)
    setIfFilled(parameters, 'search_max_hold_s', form.searchMaxHoldS)
    setIfFilled(parameters, 'search_max_storage_align_shift_s', form.searchMaxStorageAlignShiftS)
    setEmptyMassOverride(parameters, form.emptyMassTons)
    setBoolIfTrue(parameters, 'disable_storage_preset_search', form.disableStoragePresetSearch)
    setBoolIfTrue(parameters, 'disable_energy_observability', form.disableEnergyObservability)
  }
  if (runType === 'rolling_rescheduling') {
    const intensity = searchIntensityValues(form)
    setIfFilled(parameters, 'population_size', intensity.populationSize)
    setIfFilled(parameters, 'generations', intensity.generations)
    setIfFilled(parameters, 'seed', form.seed)
    setIfFilled(parameters, 'max_safety_retries', form.maxSafetyRetries)
    setIfFilled(parameters, 'manual_after_withheld', form.manualAfterWithheld)
    setBoolIfTrue(parameters, 'disable_safety_retry', form.disableSafetyRetry)
    setBoolIfTrue(parameters, 'disable_recovery', form.disableRecovery)
    if (form.rollingSource === 'replay') {
      const replayPath = String(form.disturbanceHistoryRelativePath || '').trim()
      if (replayPath) {
        parameters.disturbance_history_relative_path = replayPath
      }
    }
    if (form.rollingSource === 'devices') {
      parameters.storage_devices = (form.storageDevices || []).map(normalizeDevice).filter(Boolean)
    }
  }
  if (runType === 'joint_parameter_robustness') {
    parameters.parameter_ranges_relative_path = String(form.parameterRangesRelativePath || '').trim()
    setIfFilled(parameters, 'heavy_count', form.heavyCount)
    setIfFilled(parameters, 'empty_count', form.emptyCount)
    setIfFilled(parameters, 'baseline_heavy_headway_s', form.baselineHeavyHeadwayS)
    setIfFilled(parameters, 'baseline_empty_headway_s', form.baselineEmptyHeadwayS)
    setIfFilled(parameters, 'baseline_phase_s', form.baselinePhaseS)
    setIfFilled(parameters, 'settlement_step_s', form.settlementStepS)
  }
  if (runType === 'storage_planning') {
    parameters.planning_policy_code = String(form.planningPolicyCode || '').trim()
    parameters.scenario_set_code = String(form.scenarioSetCode || '').trim()
    parameters.search_mode = form.searchMode
    parameters.settlement_step_s = form.settlementStepS
    if (form.searchMode !== 'exhaustive') parameters.max_levels_per_dimension = form.maxLevelsPerDimension
    if (form.searchMode === 'coarse_to_fine') parameters.refinement_shortlist_size = form.refinementShortlistSize
  }
  return parameters
}

export function validateEnergyForm(form) {
  if (form.runType === 'storage_planning') {
    if (!form.planningPolicyCode || !form.scenarioSetCode) return '请先补齐版本规划数据并选择策略、场景集'
    if (!['coarse', 'coarse_to_fine', 'exhaustive'].includes(form.searchMode)) return '请选择合法搜索方式'
    if (!Number.isInteger(Number(form.settlementStepS)) || Number(form.settlementStepS) <= 0) return '结算步长必须为正整数'
    if (form.searchMode !== 'exhaustive' && (!Number.isInteger(Number(form.maxLevelsPerDimension)) || Number(form.maxLevelsPerDimension) < 2)) return '每维档位数至少为2'
    if (form.searchMode === 'coarse_to_fine' && (!Number.isInteger(Number(form.refinementShortlistSize)) || Number(form.refinementShortlistSize) < 1)) return '细化候选数必须为正整数'
  }
  if (!form.projectCode || !form.versionCode) {
    return '请选择数据版本'
  }
  if ((form.runType === 'timetable_audit' || form.runType === 'timetable_optimization') && !String(form.timetableRelativePath || '').trim()) {
    return '请填写运行图相对路径'
  }
  if (form.runType === 'joint_parameter_robustness' && !String(form.parameterRangesRelativePath || '').trim()) {
    return '请填写参数区间文件'
  }
  if (form.runType === 'rolling_rescheduling' && form.rollingSource === 'replay' && !String(form.disturbanceHistoryRelativePath || '').trim()) {
    return '请填写扰动回放文件'
  }
  if (form.runType === 'rolling_rescheduling' && form.rollingSource === 'devices') {
    const devices = (form.storageDevices || []).map(normalizeDevice).filter(Boolean)
    if (!devices.length) {
      return '请至少填写一台储能设备'
    }
    const seen = {}
    for (let i = 0; i < devices.length; i++) {
      const id = devices[i].storage_section_id
      if (seen[id]) {
        return '储能区间编号不能重复'
      }
      seen[id] = true
      if (!Number.isFinite(devices[i].soc_kwh) || devices[i].soc_kwh < 0) {
        return '每台设备都要填写非负当前电量'
      }
    }
  }
  return ''
}

export function applyDispatchDemo(form) {
  form.runType = 'dispatch'
  applyRunTypeDefaults(form)
}

export function applyTimetableDemo(form) {
  form.runType = form.runType === 'timetable_audit' ? 'timetable_audit' : 'timetable_optimization'
  applyRunTypeDefaults(form)
}

export function applyRollingDeviceDemo(form) {
  form.runType = 'rolling_rescheduling'
  applyRunTypeDefaults(form)
  form.rollingSource = 'devices'
  form.storageDevices = cloneStorageDevices(DEMO_STORAGE_DEVICES)
}

export function applyRollingReplayDemo(form) {
  form.runType = 'rolling_rescheduling'
  applyRunTypeDefaults(form)
  form.rollingSource = 'replay'
  form.disturbanceHistoryRelativePath = form.disturbanceHistoryRelativePath || 'platform/historical_disturbance_replay_case_001.json'
}

export function applyJointDemo(form) {
  form.runType = 'joint_parameter_robustness'
  applyRunTypeDefaults(form)
}
