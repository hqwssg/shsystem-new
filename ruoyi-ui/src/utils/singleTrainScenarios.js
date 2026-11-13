export function scenarioName(key) {
  if (!key) return ''
  if (key === 'eco_driving') return '节能驾驶区段'
  if (key.startsWith('s1_')) return '平直线路常规制动'
  if (key.startsWith('s2_')) return '长大下坡持续制动'
  if (key.startsWith('sR_')) return '当前线路区段制动'
  if (key.startsWith('s3_')) return key.includes('0.6') ? '较轻编组制动' : '较重编组制动'
  if (key.startsWith('s4_')) return '制动强度变化'
  if (key.startsWith('s5_')) return key.includes('0.89') ? '储能接近满电（89%）' : '储能接近满电（85%）'
  if (key.startsWith('s6_')) return key.includes('converter') ? '变流器参数偏差' : '储能参数偏差'
  if (key.startsWith('s7_')) return '复杂坡度与制动变化'
  if (key.startsWith('s8_')) return key.includes('5pct') ? '较大测量扰动' : '小幅测量扰动'
  if (key.startsWith('s9_')) return '列车模型参数偏差'
  return key
}
