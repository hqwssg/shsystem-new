import reportNames from '../../../ruoyi-modules/ruoyi-energy/src/main/resources/energy-report-names.json'

const FILE_NAMES = reportNames.files

const FOLDER_NAMES = reportNames.folders

const OPERATOR_ARTIFACT_FILES = {
  'storage_planning_report.md': true,
  'storage_planning_summary.json': true,
  'no_build_baseline.csv': true,
  'energy_hotspots.csv': true,
  'storage_plan_candidates.csv': true,
  'storage_plan_devices.csv': true,
  'storage_plan_scenario_results.csv': true,
  'storage_plan_rejections.csv': true,
  'storage_plan_lifecycle.csv': true,
  'storage_economic_sensitivity.csv': true,
  'storage_device_scenario_results.csv': true,

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

export function localizeEnergyReportFiles(markdown, rows) {
  const aliases = new Map(Object.keys(FILE_NAMES).map(name => [name, artifactDownloadName(name)]))
  const basenames = new Map()
  ;(rows || []).forEach(item => {
    const original = String(item.relativePath || '').replace(/\\/g, '/')
    if (!original) return
    const mapped = artifactDownloadName(original)
    aliases.set(original, mapped)
    const name = basename(original)
    const candidates = basenames.get(name) || new Set()
    candidates.add(mapped)
    basenames.set(name, candidates)
  })
  basenames.forEach((candidates, name) => {
    if (candidates.size === 1) aliases.set(name, [...candidates][0])
    else aliases.delete(name)
  })
  // One pass avoids replacing a short filename inside a longer one or translating twice.
  ;[...aliases.values()].forEach(name => aliases.set(name, name))
  const escape = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const keys = [...aliases.keys()].sort((a, b) => b.length - a.length)
  if (!keys.length) return String(markdown || '')
  const pattern = new RegExp('(^|[^a-zA-Z0-9_./\\\\-])(?:\\./)?(' + keys.map(escape).join('|') + ')(?=$|[^a-zA-Z0-9_.-])', 'g')
  return String(markdown || '').split(/(https?:\/\/[^\s<>)`]+)/gi).map((part, index) =>
    index % 2 ? part : part.replace(pattern, (_, prefix, name) => prefix + aliases.get(name))
  ).join('')
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
  storage_planning: ['storage_planning_report.md'],
  timetable_audit: ['TIMETABLE_ENERGY_AUDIT_REPORT.md'],
  timetable_optimization: ['TIMETABLE_OPTIMIZATION_REPORT.md'],
  dispatch: ['DISPATCH_CASE_REPORT.md', 'HEAVY_EMPTY_NETWORK_REPORT.md'],
  rolling_rescheduling: ['SYNTHETIC_ROLLING_RESCHEDULING_REPORT.md', 'HISTORICAL_DISTURBANCE_REPLAY_REPORT.md'],
  joint_parameter_robustness: ['JOINT_PARAMETER_ROBUSTNESS_REPORT.md']
}

const PREVIEW_TABLE_FILES_BY_RUN_TYPE = {
  storage_planning: ['storage_plan_rejections.csv', 'storage_economic_sensitivity.csv', 'storage_device_scenario_results.csv'],
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
  timetable_audit: ['audit_summary.json'],
  storage_planning: ['storage_planning_summary.json'],
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
    'storage_planning_report.md',
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
  // Download every archived result. Preview selection remains independent.
  return (rows || []).slice().sort(function(left, right) {
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
