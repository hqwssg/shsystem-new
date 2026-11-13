<template>
  <div class="app-container">
    <el-button :icon="$icon('el-icon-back')" size="small" class="back-button" @click="$router.push('/carbon/single-train')">返回</el-button>
    <version-maintenance ref="maintenance" />
  </div>
</template>
<script>
import VersionMaintenance from './VersionMaintenance'
export default { name: 'CarbonSingleTrainVersions', components: { VersionMaintenance }, beforeRouteLeave(to, from, next) { this.$refs.maintenance.confirmLeave().then(allowed => next(allowed)) } }
</script>
<style scoped>
.back-button { margin-bottom: 16px; }
</style>
