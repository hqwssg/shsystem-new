const FILE_NAMES = {
  'audit_issues.csv': '审查问题清单',
  'audit_summary.json': '运行图审查总览',
  'TIMETABLE_ENERGY_AUDIT_REPORT.md': '运行图审查报告',
  'optimization_suggestions.csv': '优化调整建议',
  'timetable_running_arcs.csv': '列车运行弧明细',
  'timetable_energy_time_slices.csv': '能量时间片明细',
  'timetable_power_arm_settlement.csv': '供电臂能量结算',
  'energy_events.csv': '能量事件明细',
  'scenario_summary.csv': '能量场景对比',
  'validation_issues.csv': '运行图校验问题',
  'timetable_nodes_draft.csv': '运行图节点草稿',
  'timetable_arcs_draft.csv': '运行图弧段草稿',
  'visualization_diagnostics.json': '示意图生成状态',
  'optimizer_summary.json': '运行图优化总览',
  'TIMETABLE_OPTIMIZATION_REPORT.md': '运行图优化报告',
  'candidate_summary.csv': '候选方案总表',
  'candidate_scenario_scores.csv': '候选方案场景得分',
  'candidate_energy_issues.csv': '候选方案能量问题',
  'candidate_explanations.csv': '候选方案解释',
  'pareto_candidates.csv': '帕累托候选方案',
  'pareto_candidates.json': '帕累托候选方案数据',
  'generation_log.csv': '优化迭代日志',
  'final_population.csv': '最终搜索种群',
  'summary.json': '调度结果总览',
  'DISPATCH_CASE_REPORT.md': '重空调度报告',
  'HEAVY_EMPTY_NETWORK_REPORT.md': '重空网络优化报告',
  'kpi_summary.csv': '能量指标汇总',
  'kpi_comparison.csv': '基线与优化指标对比',
  'energy_timeline.csv': '能量时间线',
  'energy_time_slices.csv': '能量时间片',
  'baseline_schedule.csv': '基线发车方案',
  'optimized_schedule.csv': '优化后发车方案',
  'ranked_candidates.csv': '候选方案排序',
  'resource_conflicts.csv': '资源冲突明细',
  'flow_continuity_events.csv': '车流连续事件',
  'flow_continuity_violations.csv': '车流连续违规',
  'time_space_nodes.csv': '时空网络节点',
  'time_space_arcs.csv': '时空网络弧段',
  'time_space_paths.csv': '时空网络路径',
  'power_arm_energy_settlement.csv': '供电臂能量结算',
  'search_space_diagnostics.json': '搜索空间诊断',
  'selected_plan_scenario_diagnostics.csv': '入选方案场景诊断',
  'core_robust_nominal_comparison.csv': '核心稳健与名义对比',
  'robust_nominal_comparison.csv': '稳健与名义对比',
  'energy_scenario_comparison.csv': '能量场景对比表',
  'energy_scenario_comparison.json': '能量场景对比数据',
  'AUTO_ENERGY_SCENARIO_REPORT.md': '自动能量场景报告',
  'timetable.png': '运行图示意图',
  'timetable_profile.png': '运行图示意',
  'energy_flow_baseline.png': '基线能量流图',
  'energy_flow_optimized.png': '优化能量流图',
  'soc_curve.png': '储能电量变化图',
  'cost_comparison.png': '成本对比图',
  'resource_conflict_timeline.png': '资源冲突时间线',
  'scenario_energy_comparison.png': '场景能量对比图',
  'power_arm_energy_timeline.png': '供电臂能量时间线',
  'top_power_arm_energy.png': '供电臂能量排名',
  'pareto_front.png': '帕累托前沿图',
  'candidate_adjustments.png': '候选调整示意图',
  'scenario_score_comparison.png': '候选场景得分对比',
  'OPTIMIZATION_ATTRIBUTION_REPORT.md': '收益归因报告',
  'optimization_attribution_summary.json': '收益归因总览',
  'optimization_kpi_attribution.csv': '指标改善归因',
  'optimization_candidate_decisions.csv': '候选方案取舍说明',
  'optimization_candidate_funnel.csv': '候选筛选漏斗',
  'optimization_bottlenecks.csv': '瓶颈分析',
  'optimization_dimension_attribution.csv': '分维度变化说明',
  'benchmark_summary.json': '滚动重调度总览',
  'SYNTHETIC_ROLLING_RESCHEDULING_REPORT.md': '滚动重调度报告',
  'HISTORICAL_DISTURBANCE_REPLAY_REPORT.md': '扰动回放报告',
  'rolling_cycles.csv': '滚动各轮结果',
  'rolling_state_timeline.png': '滚动状态时间线',
  'recovery_conflicts.csv': '恢复冲突明细',
  'recovery_conflict_chains.csv': '恢复冲突链',
  'recovery_adjustable_trains.csv': '可调整列车清单',
  'recovery_adjustment_candidates.csv': '恢复调整候选',
  'recovery_conflict_analysis.json': '恢复冲突分析',
  'recovery_repair_decisions.csv': '恢复修复决策',
  'recovery_repair_scenarios.csv': '恢复修复场景',
  'recovery_repair_results.json': '恢复修复结果',
  'exact_recovery_decisions.csv': '精确恢复决策',
  'exact_recovery_results.json': '精确恢复结果',
  'disturbance_replay_manifest.json': '扰动回放清单',
  'disturbance_replay_cycles.csv': '扰动回放各轮结果',
  'joint_robustness_summary.json': '联合稳健性总览',
  'JOINT_PARAMETER_ROBUSTNESS_REPORT.md': '联合参数稳健性报告',
  'joint_parameter_scenarios.csv': '联合参数场景',
  'joint_robustness_results.csv': '联合稳健性结果',
  'database_worker_command.json': '本次计算命令记录',
  'solver_resource_report.json': '求解资源与超时记录'
}

const FOLDER_NAMES = {
  figures: '示意图',
  candidate_timetables: '候选运行图'
}

const OPERATOR_ARTIFACT_FILES = {
  'audit_issues.csv': true,
  'audit_summary.json': true,
  'TIMETABLE_ENERGY_AUDIT_REPORT.md': true,
  'optimization_suggestions.csv': true,
  'validation_issues.csv': true,
  'optimizer_summary.json': true,
  'TIMETABLE_OPTIMIZATION_REPORT.md': true,
  'candidate_summary.csv': true,
  'candidate_explanations.csv': true,
  'pareto_candidates.csv': true,
  'summary.json': true,
  'DISPATCH_CASE_REPORT.md': true,
  'HEAVY_EMPTY_NETWORK_REPORT.md': true,
  'kpi_summary.csv': true,
  'kpi_comparison.csv': true,
  'baseline_schedule.csv': true,
  'optimized_schedule.csv': true,
  'resource_conflicts.csv': true,
  'OPTIMIZATION_ATTRIBUTION_REPORT.md': true,
  'optimization_attribution_summary.json': true,
  'benchmark_summary.json': true,
  'SYNTHETIC_ROLLING_RESCHEDULING_REPORT.md': true,
  'HISTORICAL_DISTURBANCE_REPLAY_REPORT.md': true,
  'rolling_cycles.csv': true,
  'rolling_state_timeline.png': true,
  'disturbance_replay_manifest.json': true,
  'disturbance_replay_cycles.csv': true,
  'joint_robustness_summary.json': true,
  'JOINT_PARAMETER_ROBUSTNESS_REPORT.md': true,
  'timetable.png': true,
  'energy_flow_baseline.png': true,
  'energy_flow_optimized.png': true,
  'soc_curve.png': true,
  'cost_comparison.png': true,
  'resource_conflict_timeline.png': true
}

function parentFolder(relativePath) {
  const parts = String(relativePath || '').replace(/\\/g, '/').split('/')
  return parts.length > 1 ? parts[parts.length - 2] : ''
}

function basename(relativePath) {
  const parts = String(relativePath || '').replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || ''
}

export function isOperatorFacingArtifact(relativePath) {
  const name = basename(relativePath)
  if (OPERATOR_ARTIFACT_FILES[name]) {
    return true
  }
  const folder = parentFolder(relativePath)
  if (folder === 'candidate_timetables') {
    return true
  }
  return folder === 'figures' && /\.(png|jpe?g|svg|webp)$/i.test(name)
}

function extension(name) {
  const index = name.lastIndexOf('.')
  return index >= 0 ? name.slice(index) : ''
}

export function artifactDisplayName(relativePath) {
  const normalized = String(relativePath || '').replace(/\\/g, '/')
  const name = basename(normalized)
  if (FILE_NAMES[name]) {
    return FILE_NAMES[name]
  }
  const folder = parentFolder(normalized)
  if (folder && FOLDER_NAMES[folder]) {
    return FOLDER_NAMES[folder] + '：' + name
  }
  return name || '未命名文件'
}

export function artifactDownloadName(relativePath) {
  const name = basename(relativePath)
  const ext = extension(name)
  const display = artifactDisplayName(relativePath)
  if (!ext || display.indexOf(ext) === display.length - ext.length) {
    return display
  }
  return display + ext
}

const PREVIEW_IMAGE_ORDER = [
  'timetable.png',
  'timetable_profile.png',
  'energy_flow_baseline.png',
  'energy_flow_optimized.png',
  'soc_curve.png',
  'cost_comparison.png',
  'scenario_energy_comparison.png',
  'power_arm_energy_timeline.png',
  'top_power_arm_energy.png',
  'resource_conflict_timeline.png',
  'rolling_state_timeline.png',
  'pareto_front.png',
  'candidate_adjustments.png',
  'scenario_score_comparison.png'
]

const HIDDEN_PREVIEW_IMAGES = {
  'evolution_progress.png': true
}

const PRIMARY_REPORT_BY_RUN_TYPE = {
  timetable_audit: ['TIMETABLE_ENERGY_AUDIT_REPORT.md'],
  timetable_optimization: ['TIMETABLE_OPTIMIZATION_REPORT.md'],
  dispatch: ['DISPATCH_CASE_REPORT.md', 'HEAVY_EMPTY_NETWORK_REPORT.md'],
  rolling_rescheduling: ['SYNTHETIC_ROLLING_RESCHEDULING_REPORT.md', 'HISTORICAL_DISTURBANCE_REPLAY_REPORT.md'],
  joint_parameter_robustness: ['JOINT_PARAMETER_ROBUSTNESS_REPORT.md']
}

const PREVIEW_TABLE_FILES_BY_RUN_TYPE = {
  timetable_audit: ['audit_issues.csv', 'optimization_suggestions.csv', 'validation_issues.csv'],
  timetable_optimization: ['candidate_summary.csv'],
  dispatch: ['resource_conflicts.csv', 'kpi_comparison.csv'],
  rolling_rescheduling: ['rolling_cycles.csv', 'disturbance_replay_cycles.csv'],
  joint_parameter_robustness: []
}

const FALLBACK_TABLE_FILES = [
  'audit_issues.csv',
  'candidate_summary.csv',
  'kpi_comparison.csv',
  'kpi_summary.csv',
  'rolling_cycles.csv',
  'optimization_suggestions.csv',
  'pareto_candidates.csv'
]

const SUMMARY_JSON_BY_RUN_TYPE = {
  timetable_optimization: ['optimizer_summary.json'],
  dispatch: ['summary.json'],
  rolling_rescheduling: ['benchmark_summary.json'],
  joint_parameter_robustness: ['joint_robustness_summary.json']
}

function findByNames(rows, names) {
  const list = rows || []
  for (let i = 0; i < names.length; i++) {
    const found = list.find(function(item) {
      return basename(item.relativePath) === names[i]
    })
    if (found) {
      return found
    }
  }
  return null
}

export function isPreviewImageArtifact(relativePath) {
  const name = basename(relativePath)
  if (HIDDEN_PREVIEW_IMAGES[name]) {
    return false
  }
  if (PREVIEW_IMAGE_ORDER.indexOf(name) >= 0) {
    return true
  }
  return parentFolder(relativePath) === 'figures' && /\.(png|jpe?g|svg|webp)$/i.test(name)
}

export function previewImageArtifacts(rows) {
  return (rows || []).filter(function(item) {
    return isOperatorFacingArtifact(item.relativePath) && isPreviewImageArtifact(item.relativePath)
  }).slice().sort(function(left, right) {
    const leftRank = PREVIEW_IMAGE_ORDER.indexOf(basename(left.relativePath))
    const rightRank = PREVIEW_IMAGE_ORDER.indexOf(basename(right.relativePath))
    if (leftRank !== rightRank) {
      return (leftRank < 0 ? 999 : leftRank) - (rightRank < 0 ? 999 : rightRank)
    }
    return String(left.relativePath || '').localeCompare(String(right.relativePath || ''))
  })
}

export function primaryReportArtifact(runType, rows) {
  const preferred = PRIMARY_REPORT_BY_RUN_TYPE[runType] || []
  const hit = findByNames(rows, preferred)
  if (hit) {
    return hit
  }
  return (rows || []).find(function(item) {
    return isOperatorFacingArtifact(item.relativePath) && /\.md$/i.test(basename(item.relativePath))
  }) || null
}

export function previewTableArtifacts(runType, rows, skipNames) {
  const skip = {}
  ;(skipNames || []).forEach(function(name) {
    skip[name] = true
  })
  const preferred = PREVIEW_TABLE_FILES_BY_RUN_TYPE[runType] || []
  const picked = preferred.map(function(name) {
    return (rows || []).find(function(item) {
      return basename(item.relativePath) === name
    })
  }).filter(function(item) {
    return item && !skip[basename(item.relativePath)]
  })
  if (picked.length) {
    return picked
  }
  const fallback = []
  FALLBACK_TABLE_FILES.forEach(function(name) {
    if (skip[name]) {
      return
    }
    const item = (rows || []).find(function(row) {
      return basename(row.relativePath) === name
    })
    if (item && isOperatorFacingArtifact(item.relativePath)) {
      fallback.push(item)
    }
  })
  return fallback
}

export function previewSummaryArtifact(runType, rows) {
  return findByNames(rows, SUMMARY_JSON_BY_RUN_TYPE[runType] || [])
}

export function formatEnergyArtifactSize(bytes) {
  const size = Number(bytes)
  if (!isFinite(size) || size < 0) {
    return '—'
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = size
  let unit = 0
  while (unit < units.length - 1 && value >= 1024) {
    value /= 1024
    unit += 1
  }
  if (unit === 0) {
    return Math.round(value) + ' B'
  }
  const rounded = Math.round(value * 10) / 10
  if (rounded >= 1024 && unit < units.length - 1) {
    unit += 1
    value = rounded / 1024
  } else {
    value = rounded
  }
  const text = Number.isInteger(value) ? String(value) : value.toFixed(1)
  return text + ' ' + units[unit]
}

export function sortEnergyArtifacts(rows) {
  const priority = [
    'TIMETABLE_ENERGY_AUDIT_REPORT.md',
    'TIMETABLE_OPTIMIZATION_REPORT.md',
    'DISPATCH_CASE_REPORT.md',
    'HEAVY_EMPTY_NETWORK_REPORT.md',
    'SYNTHETIC_ROLLING_RESCHEDULING_REPORT.md',
    'HISTORICAL_DISTURBANCE_REPLAY_REPORT.md',
    'OPTIMIZATION_ATTRIBUTION_REPORT.md',
    'JOINT_PARAMETER_ROBUSTNESS_REPORT.md',
    'audit_summary.json',
    'optimizer_summary.json',
    'summary.json',
    'benchmark_summary.json',
    'joint_robustness_summary.json',
    'audit_issues.csv',
    'kpi_summary.csv',
    'kpi_comparison.csv',
    'candidate_summary.csv',
    'optimization_suggestions.csv'
  ]
  return (rows || []).filter(function(item) {
    return isOperatorFacingArtifact(item.relativePath)
  }).slice().sort(function(left, right) {
    const leftName = basename(left.relativePath)
    const rightName = basename(right.relativePath)
    const leftRank = priority.indexOf(leftName)
    const rightRank = priority.indexOf(rightName)
    if (leftRank !== rightRank) {
      return (leftRank < 0 ? 999 : leftRank) - (rightRank < 0 ? 999 : rightRank)
    }
    return String(left.relativePath || '').localeCompare(String(right.relativePath || ''))
  })
}
