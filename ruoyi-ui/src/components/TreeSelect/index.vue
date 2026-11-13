<template>
  <el-tree-select :model-value="modelValue" :data="nodes" node-key="id" :multiple="multiple" :check-strictly="!disableBranchNodes" filterable clearable :render-after-expand="false" v-bind="$attrs" @update:model-value="$emit('update:modelValue', $event)" />
</template>
<script>
export default {
  name: 'TreeSelect', inheritAttrs: false,
  props: { modelValue: [String, Number, Array], options: { type: Array, default: () => [] }, normalizer: Function, multiple: Boolean, disableBranchNodes: Boolean },
  emits: ['update:modelValue'],
  computed: { nodes() {
    const convert = item => { const n = this.normalizer ? this.normalizer(item) : item; return { ...item, ...n, id: n.id, label: n.label, children: n.children && n.children.map(convert) } }
    return this.options.map(convert)
  } }
}
</script>
