<template>
  <div class="goview-redirect">
    <el-icon class=""><component :is="$icon('el-icon-loading')" /></el-icon>
    <span>正在打开碳排放大屏展示...</span>
    <el-button size="small" type="primary" @click="openGoview">立即打开</el-button>
  </div>
</template>

<script>
import { buildGoviewPreviewUrl, getDefaultGoviewProjectId } from '@/utils/carbonAccess'

export default {
  name: 'CarbonScreen',
  mounted() {
    this.openGoview()
  },
  methods: {
    openGoview() {
      window.location.assign(buildGoviewPreviewUrl(getDefaultGoviewProjectId()))
    }
  }
}
</script>

<style scoped lang="scss">
.goview-redirect {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: calc(100vh - 50px);
  color: #526273;
  background: #f5f7fa;
  font-size: 15px;
}

.goview-redirect :is(i, .el-icon) {
  color: #1f8f6b;
  font-size: 22px;
}

@media (max-width: 560px) {
  .goview-redirect {
    flex-direction: column;
    padding: 24px;
    text-align: center;
  }
}
</style>
