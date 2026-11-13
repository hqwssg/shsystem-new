const PREFERRED_COLUMNS = {
  'storage_plan_rejections.csv': ['plan_id', 'site_codes', 'annual_saving_vs_no_build_cny', 'grid_reduction_vs_no_build_kwh_per_year', 'rejection_reasons'],
  'storage_economic_sensitivity.csv': ['plan_id', 'price_factor', 'grid_price_factor', 'annual_total_cost_cny', 'annual_saving_vs_no_build_cny', 'break_even_grid_price_cny_per_kwh'],
  'storage_device_scenario_results.csv': ['plan_id', 'scenario_code', 'site_code', 'technology_code', 'storage_charge_kwh', 'storage_discharge_kwh', 'final_soc_kwh'],
  'audit_issues.csv': ['issue_type', 'severity', 'power_arm_id', 'time_window_start', 'time_window_end', 'estimated_wasted_kwh', 'reason'],
  'optimization_suggestions.csv': ['action', 'expected_effect', 'priority', 'power_arm_id', 'time_window_start', 'time_window_end'],
  'validation_issues.csv': ['severity', 'issue_type', 'location', 'message', 'reason'],
  'candidate_summary.csv': ['candidate_id', 'action_type', 'total_adjustment_min', 'delay_min', 'feasible', 'resource_conflict_count', 'constraint_violation'],
  'pareto_candidates.csv': ['candidate_id', 'feasible', 'grid_kwh', 'wasted_kwh', 'constraint_violation'],
  'resource_conflicts.csv': ['conflict_type', 'severity', 'train_a', 'train_b', 'message'],
  'kpi_comparison.csv': ['metric', 'baseline', 'optimized', 'delta', 'delta_pct'],
  'kpi_summary.csv': ['case', 'feasible', 'grid_kwh', 'wasted_kwh', 'recovered_energy_kwh', 'recovery_rate'],
  'rolling_cycles.csv': ['cycle_index', 'current_time_s', 'commit_status', 'safety_state', 'core_robust_feasible'],
  'disturbance_replay_cycles.csv': ['cycle_index', 'current_time_s', 'commit_status', 'observed_heavy_delay_s', 'observed_empty_delay_s']
}

const COLUMN_LABELS = {
  plan_id: '方案编码', site_codes: '候选站点', site_code: '站点编码', technology_code: '技术编码', scenario_code: '场景编码',
  annual_saving_vs_no_build_cny: '相对基线年节约（元）', annual_total_cost_cny: '年总成本（元）',
  grid_reduction_vs_no_build_kwh_per_year: '年购电削减（kWh）', rejection_reasons: '淘汰原因',
  break_even_grid_price_cny_per_kwh: '盈亏平衡电价（元每kWh）',
  storage_charge_kwh: '储能充电（kWh）', storage_discharge_kwh: '储能放电（kWh）',
  issue_type: '问题类型',
  severity: '严重程度',
  power_arm_id: '供电臂',
  time_window_start: '开始时刻',
  time_window_end: '结束时刻',
  estimated_wasted_kwh: '影响电量 kWh',
  reason: '原因',
  action: '建议',
  expected_effect: '预期效果',
  priority: '优先级',
  location: '位置',
  message: '说明',
  candidate_id: '候选',
  action_type: '调整类型',
  total_adjustment_min: '调整分钟',
  delay_min: '延误分钟',
  feasible: '是否可行',
  resource_conflict_count: '资源冲突数',
  constraint_violation: '约束违反',
  conflict_type: '冲突类型',
  train_a: '列车 A',
  train_b: '列车 B',
  caseName: '方案',
  case_name: '方案',
  gridKwh: '电网购电 kWh',
  wastedKwh: '弃能 kWh',
  recoveredEnergyKwh: '有效回收 kWh',
  recoveryRate: '回收率',
  cycleIndex: '轮次',
  currentTimeS: '当前时刻',
  commitStatus: '下发状态',
  safetyState: '安全状态',
  coreRobustFeasible: '核心场景可行',
  cycle_index: '轮次',
  current_time_s: '当前时刻',
  commit_status: '下发状态',
  safety_state: '安全状态',
  core_robust_feasible: '核心场景可行',
  observed_heavy_delay_s: '重车晚点 s',
  observed_empty_delay_s: '空车晚点 s',
  metric: '指标',
  baseline: '原方案',
  optimized: '优化方案',
  delta: '差值',
  delta_pct: '变化',
  case: '方案',
  disturbance_scenario: '扰动场景',
  core_for_feasibility: '核心场景',
  feasible_ratio: '可行比例'
}

const MAX_TABLE_ROWS = 30

const COMMIT_STATUS = {
  committed: '已下发',
  withheld_infeasible: '不可下发',
  hold: '暂不下发'
}

function field(source, keys) {
  if (!source) {
    return undefined
  }
  for (let i = 0; i < keys.length; i++) {
    const value = source[keys[i]]
    if (value !== undefined && value !== null && value !== '') {
      return value
    }
  }
  return undefined
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function inlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

function isTableSeparator(line) {
  return /^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(line)
}

function parseTableRow(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(function(cell) {
    return cell.trim()
  })
}

function closeList(html, inList) {
  if (inList.value) {
    html.push('</ul>')
    inList.value = false
  }
}

export function renderSimpleMarkdown(source) {
  const lines = String(source || '').replace(/\r\n/g, '\n').split('\n')
  const html = []
  const inList = { value: false }
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      closeList(html, inList)
      index += 1
      continue
    }
    if (line.trim().startsWith('|') && index + 1 < lines.length && isTableSeparator(lines[index + 1])) {
      closeList(html, inList)
      const headers = parseTableRow(line)
      index += 2
      html.push('<div class="md-table-wrap"><table><thead><tr>')
      headers.forEach(function(cell) {
        html.push('<th>' + inlineMarkdown(cell) + '</th>')
      })
      html.push('</tr></thead><tbody>')
      while (index < lines.length && lines[index].trim().startsWith('|')) {
        const cells = parseTableRow(lines[index])
        html.push('<tr>')
        headers.forEach(function(_, cellIndex) {
          html.push('<td>' + inlineMarkdown(cells[cellIndex] || '') + '</td>')
        })
        html.push('</tr>')
        index += 1
      }
      html.push('</tbody></table></div>')
      continue
    }
    const heading = line.match(/^(#{1,3})\s+(.*)$/)
    if (heading) {
      closeList(html, inList)
      const level = heading[1].length + 2
      html.push('<h' + level + '>' + inlineMarkdown(heading[2]) + '</h' + level + '>')
      index += 1
      continue
    }
    if (/^[-*]\s+/.test(line)) {
      if (!inList.value) {
        html.push('<ul>')
        inList.value = true
      }
      html.push('<li>' + inlineMarkdown(line.replace(/^[-*]\s+/, '')) + '</li>')
      index += 1
      continue
    }
    closeList(html, inList)
    html.push('<p>' + inlineMarkdown(line) + '</p>')
    index += 1
  }
  closeList(html, inList)
  return html.join('')
}

export function parseCsv(text) {
  const source = String(text || '').replace(/^\uFEFF/, '')
  const rows = []
  let row = []
  let cell = ''
  let quoted = false
  for (let i = 0; i < source.length; i++) {
    const ch = source[i]
    if (quoted) {
      if (ch === '"') {
        if (source[i + 1] === '"') {
          cell += '"'
          i += 1
        } else {
          quoted = false
        }
      } else {
        cell += ch
      }
    } else if (ch === '"') {
      quoted = true
    } else if (ch === ',') {
      row.push(cell)
      cell = ''
    } else if (ch === '\n') {
      row.push(cell)
      if (row.some(function(item) { return String(item).trim() !== '' })) {
        rows.push(row)
      }
      row = []
      cell = ''
    } else if (ch !== '\r') {
      cell += ch
    }
  }
  if (cell !== '' || row.length) {
    row.push(cell)
    if (row.some(function(item) { return String(item).trim() !== '' })) {
      rows.push(row)
    }
  }
  if (!rows.length) {
    return { headers: [], records: [] }
  }
  const headers = rows[0]
  const records = rows.slice(1).map(function(values) {
    const item = {}
    headers.forEach(function(key, index) {
      item[key] = values[index] == null ? '' : values[index]
    })
    return item
  })
  return { headers: headers, records: records }
}

function columnLabel(key) {
  return COLUMN_LABELS[key] || key
}

function selectColumns(headers, fileName) {
  const preferred = PREFERRED_COLUMNS[fileName] || []
  const picked = preferred.filter(function(key) {
    return headers.indexOf(key) >= 0
  })
  if (picked.length) {
    return picked
  }
  return headers.slice(0, 7)
}

function formatCell(key, value) {
  if (value === true || value === 'true' || value === 1 || value === '1') {
    if (/feasible|available|pareto/i.test(key)) {
      return '是'
    }
  }
  if (value === false || value === 'false' || value === 0 || value === '0') {
    if (/feasible|available|pareto/i.test(key)) {
      return '否'
    }
  }
  if (key === 'recoveryRate' || key === 'recovery_rate') {
    const rate = Number(value)
    if (!isFinite(rate)) {
      return '—'
    }
    return (Math.round(rate * 1000) / 10) + '%'
  }
  return value == null || value === '' ? '—' : String(value)
}

export function csvToPreviewTable(text, title, fileName) {
  const parsed = parseCsv(text)
  if (!parsed.records.length) {
    return null
  }
  const columns = selectColumns(parsed.headers, fileName).map(function(key) {
    return { prop: key, label: columnLabel(key) }
  })
  const truncated = parsed.records.length > MAX_TABLE_ROWS
  const rows = parsed.records.slice(0, MAX_TABLE_ROWS).map(function(record, index) {
    const row = { _row: index }
    columns.forEach(function(column) {
      row[column.prop] = formatCell(column.prop, record[column.prop])
    })
    return row
  })
  return {
    title: title,
    columns: columns,
    rows: rows,
    truncated: truncated,
    total: parsed.records.length
  }
}

export function formatEnergyMeasure(value, unit) {
  const number = Number(value)
  if (!isFinite(number)) {
    return '—'
  }
  const rounded = Math.abs(number) >= 100 ? Math.round(number) : Math.round(number * 10) / 10
  const text = String(rounded)
  return unit ? text + ' ' + unit : text
}

export function parseJsonObject(text) {
  try {
    const parsed = JSON.parse(String(text || ''))
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch (err) {
    return null
  }
}

function yesNo(value) {
  if (value === true || value === 'true' || value === 1 || value === '1') {
    return '是'
  }
  if (value === false || value === 'false' || value === 0 || value === '0') {
    return '否'
  }
  return value == null || value === '' ? '—' : String(value)
}

function energyCardsFromKpis(summary) {
  const kpis = (summary && summary.kpis) || []
  const audit = (summary && summary.auditSummary) || {}
  const optimized = kpis.find(function(item) {
    return String(item.caseName || item.case_name) === 'optimized'
  })
  const baseline = kpis.find(function(item) {
    return String(item.caseName || item.case_name) === 'baseline'
  })
  const primary = optimized || baseline || kpis[0] || {}
  const cards = [
    { label: '电网购电', value: formatEnergyMeasure(field(primary, ['gridKwh', 'grid_kwh']) ?? field(audit, ['baselineGridKwh', 'baseline_grid_kwh']), 'kWh') },
    { label: '弃能', value: formatEnergyMeasure(field(primary, ['wastedKwh', 'wasted_kwh']) ?? field(audit, ['baselineWastedKwh', 'baseline_wasted_kwh']), 'kWh') },
    { label: '有效回收', value: formatEnergyMeasure(field(primary, ['recoveredEnergyKwh', 'recovered_energy_kwh']), 'kWh') },
    { label: '回收率', value: formatCell('recoveryRate', field(primary, ['recoveryRate', 'recovery_rate'])) }
  ]
  const issueCount = field(audit, ['issueCount', 'issue_count'])
  if (issueCount !== undefined) {
    cards.push({ label: '问题数', value: String(issueCount) })
  }
  return cards
}

function optimizationCards(decision, optimizer) {
  const source = (decision && (decision.action || field(decision, ['gridImprovementKwh', 'grid_improvement_kwh']) !== undefined))
    ? decision
    : ((optimizer && optimizer.optimization_decision) || {})
  const cards = []
  const gridImprove = field(source, ['gridImprovementKwh', 'grid_improvement_kwh'])
  const lossImprove = field(source, ['effectiveRegenLossImprovementKwh', 'effective_regen_loss_improvement_kwh'])
  const baselineGrid = field(source, ['baselineGridKwh', 'baseline_grid_kwh'])
  const unassessed = source.action === 'no_feasible_solution' || source.energy_comparison_eligible === false
  if (unassessed) {
    cards.push({ label: '购电改善', value: '未评价' }, { label: '再生损失改善', value: '未评价' })
  } else if (gridImprove !== undefined) {
    cards.push({ label: '购电改善', value: formatEnergyMeasure(gridImprove, 'kWh') })
  }
  if (!unassessed && lossImprove !== undefined) {
    cards.push({ label: '再生损失改善', value: formatEnergyMeasure(lossImprove, 'kWh') })
  }
  if (baselineGrid !== undefined) {
    cards.push({ label: '原方案购电', value: formatEnergyMeasure(baselineGrid, 'kWh') })
  }
  const candidateCount = field(optimizer, ['candidate_count', 'candidateCount'])
  const paretoCount = field(optimizer, ['pareto_count', 'paretoCount'])
  const feasibleCount = field(optimizer, ['feasible_candidate_count', 'feasibleCandidateCount'])
  if (candidateCount !== undefined) {
    cards.push({ label: '候选数', value: String(candidateCount) })
  }
  if (feasibleCount !== undefined) {
    cards.push({ label: '可行候选', value: String(feasibleCount) })
  }
  if (paretoCount !== undefined) {
    cards.push({ label: '帕累托数', value: String(paretoCount) })
  }
  return cards
}

function rollingCards(events, benchmark) {
  const cards = []
  const list = events || []
  const latest = list.length ? list[list.length - 1] : null
  const cycleCount = field(benchmark, ['cycle_count', 'cycleCount']) || (list.length || undefined)
  if (cycleCount !== undefined) {
    cards.push({ label: '滚动轮次', value: String(cycleCount) })
  }
  if (latest) {
    const status = latest.commitStatus || latest.commit_status || ''
    cards.push({ label: '末轮下发', value: COMMIT_STATUS[status] || status || '—' })
    cards.push({ label: '核心场景可行', value: yesNo(latest.coreRobustFeasible == null ? latest.core_robust_feasible : latest.coreRobustFeasible) })
  }
  const infeasible = field(benchmark, ['robust_infeasible_cycle_count', 'robustInfeasibleCycleCount'])
  if (infeasible !== undefined) {
    cards.push({ label: '回退轮次', value: String(infeasible) })
  }
  return cards
}

function jointCards(joint) {
  if (!joint) {
    return []
  }
  const outcome = joint.outcome || {}
  const coverage = joint.coverage || {}
  return [
    { label: '联合稳健', value: yesNo(outcome.tested_joint_robust) },
    { label: '核心可行组合', value: outcome.core_feasible_combination_count == null ? '—' : String(outcome.core_feasible_combination_count) },
    { label: '测试组合数', value: coverage.combination_count == null ? '—' : String(coverage.combination_count) },
    { label: '最大购电', value: formatEnergyMeasure(outcome.max_grid_kwh, 'kWh') },
    { label: '最大弃能', value: formatEnergyMeasure(outcome.max_wasted_kwh, 'kWh') }
  ]
}

export function buildKpiCards(summary, runType, extra) {
  extra = extra || {}
  const raw = extra.result || {}
  const decision = { ...((summary && summary.decision) || {}), ...(raw.optimization_decision || {}) }
  if (raw.comparison && raw.comparison.energy_comparison_eligible === false) decision.energy_comparison_eligible = false
  let cards = []
  if (runType === 'timetable_optimization') {
    cards = optimizationCards(decision, extra.optimizer || extra)
  } else if (runType === 'rolling_rescheduling') {
    cards = rollingCards(summary && summary.rollingEvents, extra.benchmark || extra)
  } else if (runType === 'joint_parameter_robustness') {
    cards = jointCards(extra.joint || extra)
  } else {
    cards = energyCardsFromKpis(summary)
    if (raw.comparison && raw.comparison.energy_comparison_eligible === false) cards.push({ label: '节能改善', value: '未评价' })
  }
  return (cards || []).filter(function(card) {
    return card.value && card.value !== '—'
  })
}

export function jointPreviewTable(joint) {
  const rows = ((joint && joint.disturbance_outcomes) || []).map(function(item, index) {
    const feasible = item.feasible_count
    const total = item.combination_count
    return {
      _row: index,
      disturbance_scenario: item.disturbance_scenario || '—',
      core_for_feasibility: yesNo(item.core_for_feasibility),
      feasible_ratio: feasible == null || total == null ? '—' : (feasible + '/' + total)
    }
  })
  if (!rows.length) {
    return null
  }
  return {
    title: '扰动场景覆盖',
    columns: [
      { prop: 'disturbance_scenario', label: '扰动场景' },
      { prop: 'core_for_feasibility', label: '核心场景' },
      { prop: 'feasible_ratio', label: '可行比例' }
    ],
    rows: rows.slice(0, MAX_TABLE_ROWS),
    truncated: rows.length > MAX_TABLE_ROWS,
    total: rows.length
  }
}

export function kpiPreviewTable(kpis) {
  const rows = (kpis || []).map(function(item, index) {
    return {
      _row: index,
      caseName: item.caseName === 'optimized' || item.case_name === 'optimized' ? '优化方案' : (item.caseName === 'baseline' || item.case_name === 'baseline' ? '原方案' : (item.caseName || item.case_name || '方案')),
      gridKwh: formatEnergyMeasure(field(item, ['gridKwh', 'grid_kwh']), 'kWh'),
      wastedKwh: formatEnergyMeasure(field(item, ['wastedKwh', 'wasted_kwh']), 'kWh'),
      recoveredEnergyKwh: formatEnergyMeasure(field(item, ['recoveredEnergyKwh', 'recovered_energy_kwh']), 'kWh'),
      recoveryRate: formatCell('recoveryRate', field(item, ['recoveryRate', 'recovery_rate'])),
      feasible: formatCell('feasible', field(item, ['feasible']))
    }
  })
  if (!rows.length) {
    return null
  }
  return {
    title: '基线与优化指标对比',
    columns: [
      { prop: 'caseName', label: '方案' },
      { prop: 'gridKwh', label: '电网购电' },
      { prop: 'wastedKwh', label: '弃能' },
      { prop: 'recoveredEnergyKwh', label: '有效回收' },
      { prop: 'recoveryRate', label: '回收率' },
      { prop: 'feasible', label: '是否可行' }
    ],
    rows: rows,
    truncated: false,
    total: rows.length
  }
}

function formatClock(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  return [hours, minutes, secs].map(function(item) {
    return String(item).padStart(2, '0')
  }).join(':')
}

export function rollingPreviewTable(events) {
  const rows = (events || []).map(function(item, index) {
    const status = item.commitStatus || item.commit_status || ''
    return {
      _row: index,
      cycleIndex: item.cycleIndex == null ? item.cycle_index : item.cycleIndex,
      currentTimeS: formatClock(item.currentTimeS == null ? item.current_time_s : item.currentTimeS),
      commitStatus: COMMIT_STATUS[status] || status || '—',
      safetyState: item.safetyState || item.safety_state || '—',
      coreRobustFeasible: formatCell('feasible', item.coreRobustFeasible == null ? item.core_robust_feasible : item.coreRobustFeasible)
    }
  })
  if (!rows.length) {
    return null
  }
  return {
    title: '滚动各轮结果',
    columns: [
      { prop: 'cycleIndex', label: '轮次' },
      { prop: 'currentTimeS', label: '当前时刻' },
      { prop: 'commitStatus', label: '下发状态' },
      { prop: 'safetyState', label: '安全状态' },
      { prop: 'coreRobustFeasible', label: '核心场景可行' }
    ],
    rows: rows.slice(0, MAX_TABLE_ROWS),
    truncated: rows.length > MAX_TABLE_ROWS,
    total: rows.length
  }
}

export function decisionCopy(action, reason) {
  if (action === 'optimize') {
    return { type: 'success', title: '建议采用优化方案', description: '候选方案相对原运行图有可核验的改善。' }
  }
  if (action === 'keep_baseline') {
    return { type: 'info', title: '继续采用原运行图', description: '没有足够证据替换基线。' }
  }
  if (action === 'no_feasible_solution') {
    return { type: 'warning', title: '本轮未推荐可采用方案', description: reason === 'baseline_infeasible' ? '基线未通过硬约束检查，能耗仅供诊断，节能改善未评价。请核对始发间隔、股道及区段占用。' : '请查看约束诊断，不可采用不可行候选。' }
  }
  return null
}
