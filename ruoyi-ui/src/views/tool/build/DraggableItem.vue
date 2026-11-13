<script lang="jsx">
import { h } from 'vue'
import { CopyDocument, Delete } from '@element-plus/icons-vue'
import draggable from 'vuedraggable'
import render from '@/utils/generator/render'

const components = {
  itemBtns(h, element, index, parent) {
    const copyItem = (...args) => this.$emit('copyItem', ...args), deleteItem = (...args) => this.$emit('deleteItem', ...args)
    return [
      <span class="drawing-item-copy" title="复制" onClick={event => {
        copyItem(element, parent); event.stopPropagation()
      }}>
        <el-icon><CopyDocument /></el-icon>
      </span>,
      <span class="drawing-item-delete" title="删除" onClick={event => {
        deleteItem(index, parent); event.stopPropagation()
      }}>
        <el-icon><Delete /></el-icon>
      </span>
    ]
  }
}
const layouts = {
  colFormItem(h, element, index, parent) {
    const activeItem = (...args) => this.$emit('activeItem', ...args)
    let className = this.activeId === element.formId ? 'drawing-item active-from-item' : 'drawing-item'
    if (this.formConf.unFocusedComponentBorder) className += ' unfocus-bordered'
    return (
      <el-col span={element.span} class={className}
        onClick={event => { activeItem(element); event.stopPropagation() }}>
        <el-form-item label-width={element.labelWidth ? `${element.labelWidth}px` : null}
          label={element.label} required={element.required}>
          <render key={element.renderKey} conf={element} onUpdate:modelValue={ event => {
            (element)['defaultValue'] = event
          }} />
        </el-form-item>
        {components.itemBtns.apply(this, arguments)}
      </el-col>
    )
  },
  rowFormItem(h, element, index, parent) {
    const activeItem = (...args) => this.$emit('activeItem', ...args)
    const className = this.activeId === element.formId ? 'drawing-row-item active-from-item' : 'drawing-row-item'
    return (
      <el-col span={element.span}>
        <el-row gutter={element.gutter} class={className}
          onClick={event => { activeItem(element); event.stopPropagation() }}>
          <span class="component-name">{element.componentName}</span>
          <draggable list={element.children} itemKey="renderKey" animation={340} group="componentsGroup" class="drag-wrapper" v-slots={{ item: ({element: nested, index: nestedIndex}) => layouts[nested.layout].call(this, h, nested, nestedIndex, element.children) }} />
          {components.itemBtns.apply(this, arguments)}
        </el-row>
      </el-col>
    )
  }
}

function renderChildren(h, element, index, parent) {
  if (!Array.isArray(element.children)) return null
  return element.children.map((el, i) => {
    const layout = layouts[el.layout]
    if (layout) {
      return layout.call(this, h, el, i, element.children)
    }
    return layoutIsNotFound()
  })
}

function layoutIsNotFound() {
  throw new Error(`没有与${this.element.layout}匹配的layout`)
}

export default {
  emits: ['activeItem', 'copyItem', 'deleteItem'],
  components: {
    render,
    draggable
  },
  props: [
    'element',
    'index',
    'drawingList',
    'activeId',
    'formConf'
  ],
  render() {
    const layout = layouts[this.element.layout]

    if (layout) {
      return layout.call(this, h, this.element, this.index, this.drawingList)
    }
    return layoutIsNotFound()
  }
}
</script>
