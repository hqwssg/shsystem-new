export const ORG_LABEL = {
  SHL: '公司本部',
  JLG: '机辆分公司',
  SNF: '肃宁分公司',
  YPF: '原平分公司'
}

export const VAR_LABEL = {
  TURNOVER: '货运周转量',
  GAS: '天然气',
  GASOLINE: '汽油',
  DIESEL: '柴油',
  ELEC_TOTAL: '电力总和',
  ELEC_TRAC: '牵引电力',
  ELEC_AUX: '辅助生产电力',
  HEAT: '热力（可比口径）',
  HEAT_REPORTED: '热力（报表口径）',
  DIESEL_LOCO_COUNT: '内燃机车台数',
  CO2_COMPARABLE: '碳排放（可比口径）',
  CO2_REPORTED: '碳排放（报表口径）'
}

export const DATA_FLAG_LABEL = {
  '': '—',
  GAS_2024_ANOMALY: '2024 年天然气异常',
  CALIBER_CHANGE_2025: '2025 年供热口径切换',
  LEVEL_SHIFT_2024: '2024 年电力水平位移',
  LOCO_RETIREMENT_2025: '2025 年内燃机车退役',
  ESTIMATED_2019_2020: '2019—2020 年周转量推算',
  ANOMALY_BREAKPOINT: '异常检测断点标记',
  MANUAL_BREAKPOINT: '人工复核断点标记'
}

export const QUALITY_LABEL = {
  valid: '有效',
  pending: '待审核',
  excluded: '已排除'
}

export const SOURCE_LABEL = {
  原始: '原始',
  '推算-电量系数法': '推算（电量系数法）',
  '推算-辅占比重构': '推算（辅占比重构）',
  '推算-供暖度日分摊': '推算（供暖度日分摊）',
  '异常剔除-同期补全': '异常剔除（同期补全）',
  口径还原: '口径还原',
  无此项: '无此项',
  人工修正: '人工修正'
}

export const ANOMALY_LEVEL_LABEL = {
  正常: '正常',
  关注: '关注',
  异常: '异常',
  严重异常: '严重异常'
}

export const ANOMALY_CATEGORY_LABEL = {
  C1: 'C1 单点错误/尖峰',
  C2: 'C2 连续漂移/质量台阶',
  C3: 'C3 真实业务跃变/结构断点',
  C4: 'C4 季节峰谷',
  UNDETERMINED: '未定类'
}

export const ANOMALY_STATUS_LABEL = {
  pending: '待审核',
  approved: '审核通过',
  rejected: '审核驳回',
  auto_closed: '自动关闭'
}

export const CHANNEL_LABEL = {
  raw: '原始森林',
  resid: '残差森林',
  joint: '联合佐证',
  rule: '规则'
}

export const CONTEXT_LABEL = {
  spring_festival: '春节',
  covid: '疫情',
  maintenance: '检修'
}

export const DISPOSITION_LABEL = {
  keep: '保留原值',
  correct: '修正数值',
  exclude: '排除数据',
  mark_breakpoint: '标记断点'
}

export const MODEL_TYPE_LABEL = {
  SW_LSTM: '滑动窗口 LSTM',
  RIDGE: '岭回归',
  GBM: '梯度提升树',
  HOLT_WINTERS: 'Holt-Winters',
  SEASONAL_NAIVE: '季节朴素',
  ENSEMBLE: '组合模型'
}

export const MODEL_STATUS_LABEL = {
  candidate: '候选',
  active: '启用',
  deprecated: '已弃用'
}

export const JOB_TYPE_LABEL = {
  TRAIN: '模型训练',
  FORECAST: '预测生成',
  GRA: '灰色关联分析',
  IMPORT: '数据导入'
}

export const JOB_STATUS_LABEL = {
  queued: '排队中',
  running: '运行中',
  succeeded: '成功',
  failed: '失败'
}

export const SCENARIO_LABEL = {
  BAU: '基准情景',
  COAL_HIGH: '煤价上行',
  COAL_LOW: '煤价下行',
  EFFICIENCY: '能效提升'
}

export const EVENT_TYPE_LABEL = {
  spring_festival: '春节假期',
  epidemic: '疫情事件',
  maintenance: '设备检修'
}

export const IMPACT_LABEL = {
  down: '下降',
  up: '上升',
  unknown: '未知'
}

export const POLICY_CATEGORY_LABEL = {
  price: '价格',
  supply: '供给',
  transport: '运输',
  power: '电力',
  weather: '气象',
  policy: '政策',
  operation: '运营'
}

export const SOURCE_LEVEL_LABEL = {
  national: '国家',
  provincial: '省级',
  market: '市场',
  enterprise: '企业',
  station: '站点'
}

export const label = (map, value, fallback = '—') => {
  if (value === null || value === undefined || value === '') return fallback
  return map[value] || value
}

export const tagType = (value) => {
  const map = {
    valid: 'success', 正常: 'success', approved: 'success', succeeded: 'success', active: 'success',
    pending: 'warning', 关注: 'warning', queued: 'warning', running: 'warning', candidate: 'warning',
    异常: 'danger', 严重异常: 'danger', excluded: 'info', rejected: 'danger', failed: 'danger',
    deprecated: 'info', auto_closed: 'info'
  }
  return map[value] || 'info'
}

export const formatNumber = (value, digits = 2) => {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return value
  return n.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  })
}

export const formatInt = (value) => {
  if (value === null || value === undefined || value === '') return '—'
  return Number(value).toLocaleString('zh-CN')
}

export const formatPeriod = (value) => {
  if (!value) return '—'
  return String(value).slice(0, 7)
}

export const formatChannels = (value) => {
  if (!value) return '—'
  return String(value).split('+').map((x) => CHANNEL_LABEL[x] || x).join(' + ')
}

export const formatContext = (value) => {
  if (!value) return '—'
  return String(value).split(',').map((x) => CONTEXT_LABEL[x.trim()] || x.trim()).join('、')
}
