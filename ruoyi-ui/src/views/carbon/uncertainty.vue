<template>
  <div class="carbon-uncertainty">
    <iframe
      ref="frame"
      title="碳排放报告不确定性分析"
      src="/uncertainty/uncertainty-wizard.html"
      @load="onLoad"
    />
  </div>
</template>

<script>
export default {
  name: 'CarbonUncertainty',
  methods: {
    onLoad() {
      this.$emit('ready')
    }
  }
}
</script>

<style scoped>
.carbon-uncertainty {
  min-height: calc(100vh - 84px);
  background: #f5f7fa;
}

.carbon-uncertainty iframe {
  display: block;
  width: 100%;
  min-height: calc(100vh - 84px);
  height: 1000px;
  border: 0;
  background: #f5f7fa;
}
</style>
