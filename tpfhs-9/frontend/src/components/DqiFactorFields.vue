<template>
  <div class="dqi-section">
    <div class="dqi-title">排放因子质量（DQI）</div>
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
      <div class="dqi-field">
        <div class="dqi-label">E4 因子年份</div>
        <el-input-number :model-value="modelValue.efDataYear" :min="1900" :max="2100" :step="1"
                         :precision="0" controls-position="right" class="full-width-control"
                         @update:model-value="value => patch({ efDataYear: value })" />
      </div>
      <div class="dqi-field">
        <div class="dqi-label">E4 固定评分</div>
        <el-select :model-value="modelValue.dqiE4Score || 0" class="full-width-control"
                   @update:model-value="value => patch({ dqiE4Score: value || null })">
          <el-option label="自动按核算年度计算" :value="0" />
          <el-option v-for="value in [5,4,3,2,1]" :key="value" :label="`${value} 分`" :value="value" />
        </el-select>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({ modelValue: { type: Object, required: true } })
const emit = defineEmits(['update:modelValue'])
const scored = items => items.map((item, index) => ({ ...item, score: 5 - index }))
const fields = [
  { key: 'efSourceAuthority', scoreKey: 'dqiE1Score', label: 'E1 来源权威性', options: scored([
    { value: 'official_national', label: '国家官方数据' }, { value: 'national_standard', label: '国家/行业标准' },
    { value: 'ipcc_default', label: 'IPCC 默认值' }, { value: 'authoritative_literature', label: '权威文献' },
    { value: 'general_or_estimated', label: '一般来源/估算' }
  ]) },
  { key: 'efCompletenessScope', scoreKey: 'dqiE2Score', label: 'E2 组分完整性', options: scored([
    { value: 'full', label: '组分完整' }, { value: 'minor_missing', label: '少量缺失' },
    { value: 'partial_missing', label: '部分缺失' }, { value: 'major_only', label: '仅主要组分' },
    { value: 'unknown', label: '未知' }
  ]) },
  { key: 'efDataRegion', scoreKey: 'dqiE3Score', label: 'E3 地理适用性', options: scored([
    { value: 'in_boundary', label: '核算边界内' }, { value: 'same_grid', label: '同电网/同区域' },
    { value: 'national', label: '全国数据' }, { value: 'similar_economy', label: '相似经济区域' },
    { value: 'other_country', label: '其他国家/地区' }
  ]) },
  { key: 'efTechApplicability', scoreKey: 'dqiE5Score', label: 'E5 技术适用性', options: scored([
    { value: 'same_equipment_condition', label: '同设备同工况' }, { value: 'railway_same_traction', label: '铁路同牵引类型' },
    { value: 'railway_generic', label: '铁路通用数据' }, { value: 'adjacent_industry', label: '相邻行业数据' },
    { value: 'generic_default', label: '通用默认值' }
  ]) },
  { key: 'efConversionChain', scoreKey: 'dqiE6Score', label: 'E6 换算可靠性', options: scored([
    { value: 'direct_match', label: '单位直接匹配' }, { value: 'standard_single', label: '标准单步换算' },
    { value: 'multi_step', label: '多步换算' }, { value: 'derived_from_other', label: '由其他数据推导' },
    { value: 'unclear', label: '换算链不明确' }
  ]) }
]
const patch = values => emit('update:modelValue', { ...props.modelValue, ...values })
const optionScore = (field, value) => field.options.find(item => item.value === value)?.score ?? null
const score = field => optionScore(field, props.modelValue[field.key]) ?? props.modelValue[field.scoreKey] ?? ''
const update = (field, value) => patch({ [field.key]: value || null, [field.scoreKey]: optionScore(field, value) })
</script>

<style scoped>
.dqi-section { margin-top: 4px; padding-top: 12px; border-top: 1px solid var(--el-border-color-lighter); }
.dqi-title { margin-bottom: 12px; color: var(--el-text-color-primary); font-weight: 600; }
.dqi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
.dqi-field { min-width: 0; }
.dqi-label { margin-bottom: 6px; color: var(--el-text-color-regular); line-height: 20px; }
.dqi-control { display: grid; grid-template-columns: minmax(0, 1fr) 64px; gap: 8px; width: 100%; min-width: 0; }
.dqi-control :deep(.el-select) { width: 100%; min-width: 0; }
.full-width-control { width: 100%; }
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
