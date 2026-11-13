const TEN_THOUSAND_CUBIC_METRE_ALIASES = new Set([
  'wan_m3',
  '万m3',
  '万m³',
  '万立方米(万m3)',
  '万立方米(万m³)',
  '万立方米（万m3）',
  '万立方米（万m³）'
])

const TEN_THOUSAND_NORMAL_CUBIC_METRE_ALIASES = new Set([
  'wan_Nm3',
  '万Nm3',
  '万Nm³',
  '104 Nm3',
  '标准万立方米(万Nm3)',
  '标准万立方米(万Nm³)',
  '标准万立方米（万Nm3）',
  '标准万立方米（万Nm³）'
])

// 仅用于界面展示，接口载荷和数据库中的规范编码保持不变。
export function formatMeasurementUnit(value, fallback = '-') {
  if (value === undefined || value === null || value === '') return fallback
  const unit = String(value).trim()
  if (TEN_THOUSAND_CUBIC_METRE_ALIASES.has(unit)) return '万m3'
  if (TEN_THOUSAND_NORMAL_CUBIC_METRE_ALIASES.has(unit)) return '万Nm3'
  return unit
}
