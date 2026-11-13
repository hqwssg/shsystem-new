function text(row, key) {
  return String((row && row[key]) || '').trim()
}

function numberOf(row, key) {
  const raw = text(row, key).replace(/,/g, '')
  if (!raw) {
    return null
  }
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

function timeSeconds(row, key) {
  const raw = text(row, key)
  if (!raw) {
    return null
  }
  const match = raw.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/)
  if (!match) {
    return null
  }
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3] || 0)
}

function missing(field) {
  return { index: null, message: '「' + field + '」不能为空，这一行没有写入。' }
}

function badNumber(field) {
  return { index: null, message: '「' + field + '」不是数字，这一行没有写入。' }
}

function badTime(field) {
  return { index: null, message: '「' + field + '」要填 HH:MM:SS，这一行没有写入。' }
}

function selfConflict(message) {
  return { index: null, message: message }
}

function hit(index, message) {
  return { index: index, message: message + '，这一行没有写入。' }
}

function others(rows, editingIndex) {
  const list = []
  ;(rows || []).forEach(function(row, index) {
    if (index !== editingIndex) {
      list.push({ row: row, index: index })
    }
  })
  return list
}

function same(left, right) {
  return left !== '' && left === right
}

function rangesOverlap(start, end, otherStart, otherEnd) {
  return start < otherEnd && otherStart < end
}

function requireText(row, field) {
  if (!text(row, field)) {
    return missing(field)
  }
  return null
}

function requireNumber(row, field) {
  if (!text(row, field)) {
    return missing(field)
  }
  if (numberOf(row, field) === null) {
    return badNumber(field)
  }
  return null
}

function requireTime(row, field) {
  if (!text(row, field)) {
    return missing(field)
  }
  if (timeSeconds(row, field) === null) {
    return badTime(field)
  }
  return null
}

function duplicateField(rows, editingIndex, candidate, field, label) {
  const value = text(candidate, field)
  const found = others(rows, editingIndex).find(function(item) {
    return same(value, text(item.row, field))
  })
  if (!found) {
    return null
  }
  return hit(found.index, '与第' + (found.index + 1) + '行的' + label + '重复')
}

function duplicateKey(rows, editingIndex, candidate, fields, label) {
  const found = others(rows, editingIndex).find(function(item) {
    return fields.every(function(field) {
      return same(text(candidate, field), text(item.row, field))
    })
  })
  if (!found) {
    return null
  }
  return hit(found.index, '与第' + (found.index + 1) + '行的' + label + '重复')
}

function mileageOverlap(rows, editingIndex, candidate, idField, includeRow) {
  const startError = requireNumber(candidate, '起点km')
  if (startError) {
    return startError
  }
  const endError = requireNumber(candidate, '终点km')
  if (endError) {
    return endError
  }
  const start = numberOf(candidate, '起点km')
  const end = numberOf(candidate, '终点km')
  if (start >= end) {
    return selfConflict('起点km必须小于终点km，这一行没有写入。')
  }
  const found = others(rows, editingIndex).find(function(item) {
    if (includeRow && !includeRow(item.row)) {
      return false
    }
    const otherStart = numberOf(item.row, '起点km')
    const otherEnd = numberOf(item.row, '终点km')
    if (otherStart === null || otherEnd === null) {
      return false
    }
    return rangesOverlap(start, end, otherStart, otherEnd)
  })
  if (!found) {
    return null
  }
  const name = idField ? text(found.row, idField) : ''
  const who = name ? '（' + name + '）' : ''
  return hit(found.index, '里程与第' + (found.index + 1) + '行' + who + '重叠')
}

function checkStations(rows, editingIndex, candidate) {
  const idError = requireText(candidate, '车站编号')
  if (idError) {
    return idError
  }
  const nameError = requireText(candidate, '车站名称')
  if (nameError) {
    return nameError
  }
  const kmError = requireNumber(candidate, '里程km')
  if (kmError) {
    return kmError
  }
  const duplicatedId = duplicateField(rows, editingIndex, candidate, '车站编号', '车站编号')
  if (duplicatedId) {
    return duplicatedId
  }
  const duplicatedName = duplicateField(rows, editingIndex, candidate, '车站名称', '车站名称')
  if (duplicatedName) {
    return duplicatedName
  }
  const km = numberOf(candidate, '里程km')
  const found = others(rows, editingIndex).find(function(item) {
    return numberOf(item.row, '里程km') === km
  })
  if (!found) {
    return null
  }
  return hit(found.index, '与第' + (found.index + 1) + '行的里程重复')
}

function checkSegments(rows, editingIndex, candidate) {
  return requireText(candidate, '区间编号')
    || duplicateField(rows, editingIndex, candidate, '区间编号', '区间编号')
    || mileageOverlap(rows, editingIndex, candidate, '区间编号')
}

function checkTrainTypes(rows, editingIndex, candidate) {
  return requireText(candidate, '车型名称')
    || duplicateField(rows, editingIndex, candidate, '车型名称', '车型名称')
}

function checkStorageZones(rows, editingIndex, candidate) {
  const identity = function(row) {
    return text(row, '设施编号') || text(row, '储能区段编号')
  }
  const active = function(row) {
    const flag = text(row, '运行基线启用').toLowerCase()
    if (flag) {
      return ['false', '0', 'no', '否'].indexOf(flag) < 0
    }
    return ['planned', '规划'].indexOf(text(row, '实施状态').toLowerCase()) < 0
  }
  const key = identity(candidate)
  if (!key) {
    return missing('设施编号或储能区段编号')
  }
  const duplicated = others(rows, editingIndex).find(function(item) {
    return identity(item.row) === key
  })
  if (duplicated) {
    return hit(duplicated.index, '与第' + (duplicated.index + 1) + '行的设施编号或储能区段编号重复')
  }
  const operational = active(candidate) ? rows : []
  const idField = text(candidate, '设施编号') ? '设施编号' : '储能区段编号'
  return mileageOverlap(operational, editingIndex, candidate, idField, active)
}

function checkTimetableTrains(rows, editingIndex, candidate) {
  return requireText(candidate, '列车号')
    || duplicateField(rows, editingIndex, candidate, '列车号', '列车号')
}

function checkMetadata(rows, editingIndex, candidate) {
  return requireText(candidate, '键')
    || duplicateField(rows, editingIndex, candidate, '键', '键')
}

function checkHeadway(rows, editingIndex, candidate) {
  return requireText(candidate, '线路')
    || requireText(candidate, '适用范围')
    || duplicateKey(rows, editingIndex, candidate, ['线路', '适用范围'], '线路和适用范围')
}

function checkOperationTimes(rows, editingIndex, candidate) {
  return requireText(candidate, '车站名称')
    || requireText(candidate, '作业类型')
    || requireText(candidate, '辆数')
    || duplicateKey(rows, editingIndex, candidate, ['车站名称', '作业类型', '辆数'], '车站、作业类型和辆数')
}

function checkAssignments(rows, editingIndex, candidate) {
  return requireText(candidate, '车站名称')
    || requireText(candidate, '车型')
    || requireText(candidate, '方向')
    || duplicateKey(rows, editingIndex, candidate, ['车站名称', '车型', '方向'], '车站、车型和方向')
}

function checkPowerArms(rows, editingIndex, candidate) {
  const idError = requireText(candidate, '供电臂编号')
  if (idError) {
    return idError
  }
  const directionError = requireText(candidate, '方向')
  if (directionError) {
    return directionError
  }
  const duplicated = duplicateField(rows, editingIndex, candidate, '供电臂编号', '供电臂编号')
  if (duplicated) {
    return duplicated
  }
  const startError = requireNumber(candidate, '起点km')
  if (startError) {
    return startError
  }
  const endError = requireNumber(candidate, '终点km')
  if (endError) {
    return endError
  }
  const start = numberOf(candidate, '起点km')
  const end = numberOf(candidate, '终点km')
  if (start >= end) {
    return selfConflict('起点km必须小于终点km，这一行没有写入。')
  }
  const direction = text(candidate, '方向')
  const found = others(rows, editingIndex).find(function(item) {
    if (text(item.row, '方向') !== direction) {
      return false
    }
    const otherStart = numberOf(item.row, '起点km')
    const otherEnd = numberOf(item.row, '终点km')
    if (otherStart === null || otherEnd === null) {
      return false
    }
    return rangesOverlap(start, end, otherStart, otherEnd)
  })
  if (!found) {
    return null
  }
  return hit(found.index, '与第' + (found.index + 1) + '行同一方向的里程重叠')
}

function checkCycles(rows, editingIndex, candidate) {
  return requireText(candidate, '周期序号')
    || duplicateField(rows, editingIndex, candidate, '周期序号', '周期序号')
}

function checkEvents(rows, editingIndex, candidate) {
  const cycleError = requireText(candidate, '周期序号')
  if (cycleError) {
    return cycleError
  }
  const idError = requireText(candidate, '事件编号')
  if (idError) {
    return idError
  }
  const duplicated = others(rows, editingIndex).find(function(item) {
    return same(text(candidate, '周期序号'), text(item.row, '周期序号'))
      && same(text(candidate, '事件编号'), text(item.row, '事件编号'))
  })
  if (duplicated) {
    return hit(duplicated.index, '与第' + (duplicated.index + 1) + '行在同一周期的事件编号重复')
  }
  const eventType = text(candidate, '事件类型')
  const timed = eventType === '临时限速' || eventType === 'temporary_speed_restriction'
    || !!text(candidate, '开始秒') || !!text(candidate, '结束秒')
  if (!timed) {
    return null
  }
  const objectError = requireText(candidate, '对象编号')
  if (objectError) {
    return objectError
  }
  const startError = requireNumber(candidate, '开始秒')
  if (startError) {
    return startError
  }
  const endError = requireNumber(candidate, '结束秒')
  if (endError) {
    return endError
  }
  const start = numberOf(candidate, '开始秒')
  const end = numberOf(candidate, '结束秒')
  if (start >= end) {
    return selfConflict('开始秒必须小于结束秒，这一行没有写入。')
  }
  const objectId = text(candidate, '对象编号')
  const found = others(rows, editingIndex).find(function(item) {
    if (text(item.row, '对象编号') !== objectId) {
      return false
    }
    const otherStart = numberOf(item.row, '开始秒')
    const otherEnd = numberOf(item.row, '结束秒')
    if (otherStart === null || otherEnd === null) {
      return false
    }
    return rangesOverlap(start, end, otherStart, otherEnd)
  })
  if (!found) {
    return null
  }
  return hit(found.index, '与第' + (found.index + 1) + '行同一对象的时间重叠')
}

function checkParameterRanges(rows, editingIndex, candidate) {
  const code = text(candidate, '参数编码')
  const name = text(candidate, '中文名称')
  if (!code && !name) {
    return missing('参数编码或中文名称')
  }
  const lowerError = requireNumber(candidate, '下限')
  if (lowerError) {
    return lowerError
  }
  const upperError = requireNumber(candidate, '上限')
  if (upperError) {
    return upperError
  }
  if (numberOf(candidate, '下限') > numberOf(candidate, '上限')) {
    return selfConflict('下限不能大于上限，这一行没有写入。')
  }
  if (code) {
    const duplicatedCode = duplicateField(rows, editingIndex, candidate, '参数编码', '参数编码')
    if (duplicatedCode) {
      return duplicatedCode
    }
  }
  if (name) {
    return duplicateField(rows, editingIndex, candidate, '中文名称', '中文名称')
  }
  return null
}

function trainStopRows(rows, editingIndex, candidate) {
  const list = others(rows, editingIndex).map(function(item) {
    return { row: item.row, index: item.index }
  })
  list.push({ row: candidate, index: editingIndex })
  return list.filter(function(item) {
    return text(item.row, '列车号') === text(candidate, '列车号')
  }).sort(function(left, right) {
    const leftSeq = numberOf(left.row, '顺序')
    const rightSeq = numberOf(right.row, '顺序')
    return (leftSeq === null ? 0 : leftSeq) - (rightSeq === null ? 0 : rightSeq)
  })
}

function checkTimetableStops(rows, editingIndex, candidate) {
  const trainError = requireText(candidate, '列车号')
  if (trainError) {
    return trainError
  }
  const seqError = requireNumber(candidate, '顺序')
  if (seqError) {
    return seqError
  }
  const stationError = requireText(candidate, '车站名称')
  if (stationError) {
    return stationError
  }
  const arrivalError = requireTime(candidate, '到达时刻')
  if (arrivalError) {
    return arrivalError
  }
  const departureError = requireTime(candidate, '出发时刻')
  if (departureError) {
    return departureError
  }
  if (timeSeconds(candidate, '到达时刻') > timeSeconds(candidate, '出发时刻')) {
    return selfConflict('到达时刻不能晚于出发时刻，这一行没有写入。')
  }
  const sameTrainSeq = others(rows, editingIndex).find(function(item) {
    return same(text(candidate, '列车号'), text(item.row, '列车号'))
      && numberOf(candidate, '顺序') !== null
      && numberOf(item.row, '顺序') === numberOf(candidate, '顺序')
  })
  if (sameTrainSeq) {
    return hit(sameTrainSeq.index, '与第' + (sameTrainSeq.index + 1) + '行是同一列车的同一顺序')
  }
  const sameTrainStation = others(rows, editingIndex).find(function(item) {
    return same(text(candidate, '列车号'), text(item.row, '列车号'))
      && same(text(candidate, '车站名称'), text(item.row, '车站名称'))
  })
  if (sameTrainStation) {
    return hit(sameTrainStation.index, '与第' + (sameTrainStation.index + 1) + '行是同一列车的同一车站')
  }
  const ordered = trainStopRows(rows, editingIndex, candidate)
  for (let i = 1; i < ordered.length; i++) {
    const previous = ordered[i - 1]
    const next = ordered[i]
    const previousDeparture = timeSeconds(previous.row, '出发时刻')
    const nextArrival = timeSeconds(next.row, '到达时刻')
    if (previousDeparture === null || nextArrival === null || nextArrival >= previousDeparture) {
      continue
    }
    const other = previous.index === editingIndex ? next : previous
    if (other.index === null || other.index < 0) {
      return selfConflict('同一列车后一站到达早于前一站出发，这一行没有写入。')
    }
    return hit(other.index, '与第' + (other.index + 1) + '行相比，同一列车的到发时间重叠')
  }
  const arrival = timeSeconds(candidate, '到达时刻')
  const departure = timeSeconds(candidate, '出发时刻')
  const station = text(candidate, '车站名称')
  const trainId = text(candidate, '列车号')
  const occupied = others(rows, editingIndex).find(function(item) {
    if (text(item.row, '车站名称') !== station || text(item.row, '列车号') === trainId) {
      return false
    }
    const otherArrival = timeSeconds(item.row, '到达时刻')
    const otherDeparture = timeSeconds(item.row, '出发时刻')
    if (otherArrival === null || otherDeparture === null) {
      return false
    }
    return rangesOverlap(arrival, departure, otherArrival, otherDeparture)
  })
  if (!occupied) {
    return null
  }
  return hit(occupied.index, '与第' + (occupied.index + 1) + '行在同一车站的占用时间重叠')
}

function hasColumn(columns, name) {
  return (columns || []).indexOf(name) >= 0
}

export function findSheetConflict(sheetName, rows, candidate, editingIndex, columns) {
  const planningKeys = { '候选站点': ['站点编码'], '储能技术': ['技术编码'], '站点技术配置': ['站点编码', '技术编码'], '规划场景': ['场景编码'], '场景集': ['场景集编码'], '规划策略': ['策略编码'] }
  if (planningKeys[sheetName]) {
    const keys = planningKeys[sheetName]
    for (const key of keys) { const error = requireText(candidate, key); if (error) return error }
    const duplicate = others(rows, editingIndex).find(item => keys.every(key => same(text(candidate, key), text(item.row, key))))
    if (duplicate) return hit(duplicate.index, '与第' + (duplicate.index + 1) + '行的编码重复')
    if (sheetName === '规划场景') {
      const value = numberOf(candidate, '场景权重')
      if (value === null || value <= 0 || value > 1) return selfConflict('场景权重必须大于0且不超过1。')
    }
    return null
  }
  if (sheetName === '车站') {
    return checkStations(rows, editingIndex, candidate)
  }
  if (sheetName === '区间') {
    return checkSegments(rows, editingIndex, candidate)
  }
  if (sheetName === '列车' && hasColumn(columns, '车型名称')) {
    return checkTrainTypes(rows, editingIndex, candidate)
  }
  if (sheetName === '列车' && hasColumn(columns, '列车号')) {
    return checkTimetableTrains(rows, editingIndex, candidate)
  }
  if (sheetName === '储能区段') {
    return checkStorageZones(rows, editingIndex, candidate)
  }
  if (sheetName === '时刻表') {
    return checkTimetableStops(rows, editingIndex, candidate)
  }
  if (sheetName === '元数据') {
    return checkMetadata(rows, editingIndex, candidate)
  }
  if (sheetName === '追踪间隔') {
    return checkHeadway(rows, editingIndex, candidate)
  }
  if (sheetName === '技术作业时分') {
    return checkOperationTimes(rows, editingIndex, candidate)
  }
  if (sheetName === '作业适用范围') {
    return checkAssignments(rows, editingIndex, candidate)
  }
  if (sheetName === '供电臂') {
    return checkPowerArms(rows, editingIndex, candidate)
  }
  if (sheetName === '周期') {
    return checkCycles(rows, editingIndex, candidate)
  }
  if (sheetName === '事件') {
    return checkEvents(rows, editingIndex, candidate)
  }
  if (sheetName === '参数区间') {
    return checkParameterRanges(rows, editingIndex, candidate)
  }
  return null
}
