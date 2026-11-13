export function reportPeriod(task) {
  if (!task) return null
  try {
    const meta = typeof task.metadataJson === 'object' ? task.metadataJson : JSON.parse(task.metadataJson || '{}')
    const value = meta && meta._report_period
    return value && value.version === 1 ? value : null
  } catch (e) { return null }
}

export function reportPeriodLabel(task) {
  const value = reportPeriod(task)
  if (value) return value.start + ' 至 ' + value.end
  return task && task.reportYear ? task.reportYear + '年' + (task.periodType === 'MONTH' ? task.reportMonth + '月' : '') : ''
}

export function reportArtifactName(task, extension) {
  const title = reportPeriod(task) ? task.title : '报告'
  return String(title || '报告').replace(/[\\/:*?"<>|\x00-\x1f\x7f]/g, '_').replace(/[. ]+$/, '') + '.' + extension
}

export function classifyReportPeriod(start, end) {
  if (!start || !end) return ''
  const year = Number(start.slice(0, 4))
  const month = Number(start.slice(5, 7))
  if (start === year + '-01-01' && end === year + '-12-31') return '完整自然年'
  const lastDay = new Date(year, month, 0).getDate()
  if (start.endsWith('-01') && end === start.slice(0, 8) + String(lastDay).padStart(2, '0')) return '完整自然月'
  return '期间报告'
}
