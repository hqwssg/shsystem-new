export function replaceFactorSnapshot(target, result) {
  const valuePresent = result && result.factorValue !== undefined && result.factorValue !== null && result.factorValue !== ''
  const unit = result && typeof result.factorUnit === 'string' ? result.factorUnit.trim() : ''
  const source = result && typeof result.factorSource === 'string' ? result.factorSource.trim() : ''
  const factorIdPresent = result && result.factorId !== undefined && result.factorId !== null
  if (!valuePresent || !unit || !source || !factorIdPresent) {
    throw new Error('所选碳排放因子缺少数值、单位或正式来源，不能建立节点覆盖')
  }
  Object.assign(target, {
    carbonEmissionFactor: result.factorValue,
    carbonEmissionFactorUnit: unit,
    carbonEmissionFactorDescription: result.description || '',
    carbonEmissionFactorSource: source,
    carbonEmissionFactorId: result.factorId,
    carbonEmissionFactorName: result.factorName || '',
    carbonEmissionFactorReselected: true
  })
}

export function clearFactorSnapshot(target) {
  Object.assign(target, {
    carbonEmissionFactor: null,
    carbonEmissionFactorUnit: null,
    carbonEmissionFactorDescription: null,
    carbonEmissionFactorSource: null,
    carbonEmissionFactorId: null,
    carbonEmissionFactorName: null,
    carbonEmissionFactorReselected: false
  })
}
