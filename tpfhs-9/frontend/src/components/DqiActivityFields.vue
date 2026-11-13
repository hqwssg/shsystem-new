<template>
  <div class="dqi-section">
    <div class="dqi-title">活动数据质量（DQI）</div>
    <div class="dqi-grid">
      <div v-for="field in fields" :key="field.key" class="dqi-field">
        <div class="dqi-label">{{ field.label }}</div>
        <div class="dqi-control">
          <el-select :model-value="modelValue[field.key]" clearable placeholder="请选择"
                     @update:model-value="value => update(field, value)">
            <el-option v-for="option in field.options" :key="option.value"
                       :label="option.label" :value="option.value" />
          </el-select>
          <div class="score-value">{{ score(field) || '-' }} 分</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({ modelValue: { type: Object, required: true } })
const emit = defineEmits(['update:modelValue'])

const scored = labels => labels.map((item, index) => ({ ...item, score: 5 - index }))
const fields = [
  { key: 'adMeteringTier', scoreKey: 'dqiA1Score', label: 'A1 计量来源', options: scored([
    { value: 'online_meter', label: '在线计量表' }, { value: 'manual_ledger', label: '人工台账' },
    { value: 'statistical_report', label: '统计报表' }, { value: 'literature_thirdparty', label: '文献/第三方数据' },
    { value: 'default_or_estimated', label: '默认值/估算值' }
  ]) },
  { key: 'adMeterCalibration', scoreKey: 'dqiA2Score', label: 'A2 器具有效性', options: [
    { value: 'calib_valid_cert', label: '有效检定证书', score: 5 },
    { value: 'calib_valid_internal', label: '有效内部校准', score: 4 },
    { value: 'calib_overdue_verified', label: '超期但已核验', score: 3 },
    { value: 'calib_overdue_no_record', label: '超期且无记录', score: 2 },
    { value: 'calib_status_unknown', label: '状态未知', score: 1 },
    { value: 'calib_not_applicable', label: '不适用', score: 5 }
  ] },
  { key: 'adGeoBasis', scoreKey: 'dqiA4Score', label: 'A4 边界匹配', options: scored([
    { value: 'direct_metered', label: '直接计量' }, { value: 'ledger_complete', label: '完整台账' },
    { value: 'allocated', label: '合理分摊' }, { value: 'analogized', label: '类比推算' },
    { value: 'default_value', label: '默认值' }
  ]) }
]

const optionScore = (field, value) => field.options.find(item => item.value === value)?.score ?? null
const score = field => {
  const value = props.modelValue[field.key]
  return value == null || value === '' ? '' : (optionScore(field, value) ?? props.modelValue[field.scoreKey] ?? '')
}
const update = (field, value) => emit('update:modelValue', {
  ...props.modelValue,
  [field.key]: value || null,
  [field.scoreKey]: optionScore(field, value)
})
</script>

<style scoped>
.dqi-section { margin-top: 4px; padding-top: 12px; border-top: 1px solid var(--el-border-color-lighter); }
.dqi-title { margin-bottom: 12px; color: var(--el-text-color-primary); font-weight: 600; }
.dqi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
.dqi-field { min-width: 0; }
.dqi-label { margin-bottom: 6px; color: var(--el-text-color-regular); line-height: 20px; }
.dqi-control { display: grid; grid-template-columns: minmax(0, 1fr) 64px; gap: 8px; width: 100%; min-width: 0; }
.dqi-control :deep(.el-select) { width: 100%; min-width: 0; }
.score-value {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  height: 32px;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  border: 1px solid var(--el-border-color);
  border-radius: var(--el-border-radius-base);
  background: var(--el-fill-color-blank);
}
</style>
