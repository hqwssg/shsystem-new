<template>
  <el-config-provider :locale="locale" :size="$store.getters.size">
  <div id="app">
    <router-view />
    <theme-picker />
  </div>
  </el-config-provider>
</template>

<script>
import ThemePicker from "@/components/ThemePicker"
import locale from 'element-plus/es/locale/lang/zh-cn'

export default {
  name: "App",
  data() { return { locale } },
  components: { ThemePicker }
}
</script>
<style scoped>
#app .theme-picker {
  display: none;
}
</style>
