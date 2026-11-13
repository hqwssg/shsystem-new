<template>
  <el-color-picker v-model="theme" :predefine="['#409EFF','#1890ff','#304156','#212121','#11a983','#13c2c2','#6959CD','#f5222d']" class="theme-picker" popper-class="theme-picker-dropdown" @change="change" />
</template>
<script>
import { applyTheme } from '@/utils/theme'
export default {
  emits: ['change'], data() { return { theme: '#409EFF' } },
  computed: { defaultTheme() { return this.$store.state.settings.theme } },
  watch: { defaultTheme: { immediate: true, handler(value) { this.theme = value; applyTheme(value) } } },
  methods: { change(value) { applyTheme(value); this.$emit('change', value) } }
}
</script>
<style>.theme-picker-dropdown .el-color-dropdown__link-btn { display: none; }</style>
