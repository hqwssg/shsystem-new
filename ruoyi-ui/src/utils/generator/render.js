import { h, resolveComponent } from 'vue'
import { resolveIcon } from '@/utils/icons'
export default {
  props: ['conf'], emits: ['update:modelValue'],
  render() {
    const c = this.conf, props = { ...c }, slots = {}
    for (const key of ['tag','vModel','defaultValue','options','prepend','append','children','layout','showTip','buttonText','optionType']) delete props[key]
    for (const key of ['prefix-icon','suffix-icon','icon']) if (props[key]) props[key] = resolveIcon(props[key])
    if (c.vModel) { props.modelValue = c.defaultValue; props['onUpdate:modelValue'] = value => this.$emit('update:modelValue', value) }
    const el = (name, props, children) => h(resolveComponent(name), props, children == null ? undefined : { default: () => children })
    if (c.tag === 'el-select') slots.default = () => (c.options || []).map(x => el('el-option', x))
    else if (c.tag === 'el-radio-group' || c.tag === 'el-checkbox-group') {
      const tag = c.tag === 'el-radio-group' ? 'el-radio' : 'el-checkbox'
      slots.default = () => (c.options || []).map(x => el(tag+(c.optionType === 'button' ? '-button' : ''), { value: x.value, border: c.border, disabled: x.disabled }, x.label))
    } else if (c.tag === 'el-button') slots.default = () => c.default
    else if (c.tag === 'el-upload') {
      slots.default = () => el('el-button', { type: 'primary' }, c.buttonText || '点击上传')
      if (c.showTip) slots.tip = () => h('div', { class: 'el-upload__tip' }, `只能上传不超过 ${c.fileSize}${c.sizeUnit} 的${c.accept}文件`)
    }
    for (const name of ['prepend','append']) if(c[name]) slots[name] = () => c[name]
    return h(resolveComponent(c.tag), props, slots)
  }
}
